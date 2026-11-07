"""Runtime matching, cooldown accounting and native AstrBot message chains."""

from __future__ import annotations

import random
import re
from copy import deepcopy
from datetime import datetime
from typing import Any

from .matcher import Candidate, matching_candidates
from .models import normalize_rule, utc_now

VARIABLE_NAMES = {
    "sender",
    "nickname",
    "group_id",
    "group_name",
    "time",
    "date",
    "random",
}


def render_variables(value: Any, context: dict[str, Any]) -> Any:
    """Recursively replace documented variables without calling ``format``."""
    if isinstance(value, str):
        values = {name: str(context.get(name, "")) for name in VARIABLE_NAMES}
        return re.sub(r"\{([a-z_]+)\}", lambda match: values.get(match.group(1), match.group(0)), value)
    if isinstance(value, list):
        return [render_variables(item, context) for item in value]
    if isinstance(value, dict):
        return {key: render_variables(item, context) for key, item in value.items()}
    return value


def _timestamp(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


class ReplyEngine:
    def __init__(self, store, *, rng: random.Random | None = None):
        self.store = store
        self.rng = rng or random.Random()

    @staticmethod
    def event_context(event) -> dict[str, str]:
        sender_id = str(event.get_sender_id() or "") if hasattr(event, "get_sender_id") else ""
        nickname = str(event.get_sender_name() or "") if hasattr(event, "get_sender_name") else ""
        group_id = str(event.get_group_id() or "") if hasattr(event, "get_group_id") else ""
        message_obj = getattr(event, "message_obj", None)
        group_name = str(getattr(message_obj, "group_name", "") or "")
        now = datetime.now().astimezone()
        return {
            "sender": sender_id,
            "nickname": nickname or sender_id,
            "group_id": group_id,
            "group_name": group_name,
            "time": now.strftime("%H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "random": str(random.randint(0, 999999)),
        }

    def _global_scope_allowed(self, group_id: str, user_id: str) -> bool:
        settings = self.store.state.get("settings", {})
        mode = settings.get("scope_mode", "blacklist")
        groups = {str(x) for x in settings.get("group_ids", [])}
        users = {str(x) for x in settings.get("user_ids", [])}
        hit = (group_id and group_id in groups) or (user_id and user_id in users)
        return not hit if mode == "blacklist" else bool(hit)

    def _usage(self, rule_id: str) -> dict[str, Any]:
        usage = self.store.state.setdefault("usage", {})
        row = usage.setdefault(rule_id, {"last": 0.0, "users": {}, "groups": {}, "daily": {}})
        row.setdefault("users", {})
        row.setdefault("groups", {})
        row.setdefault("daily", {})
        return row

    def _eligible(self, candidate: Candidate, user_id: str, group_id: str, now: datetime) -> bool:
        rule = candidate.rule
        usage = self._usage(rule["id"])
        limits = rule.get("cooldown", {})
        stamp = now.timestamp()
        if stamp - float(usage.get("last", 0.0) or 0.0) < int(limits.get("rule_seconds", 0) or 0):
            return False
        if user_id and stamp - float(usage["users"].get(user_id, 0.0) or 0.0) < int(limits.get("user_seconds", 0) or 0):
            return False
        if group_id and stamp - float(usage["groups"].get(group_id, 0.0) or 0.0) < int(limits.get("group_seconds", 0) or 0):
            return False
        today = now.date().isoformat()
        daily = usage["daily"]
        count = int(daily.get(today, 0) or 0)
        limit = int(rule.get("daily_limit", 0) or 0)
        return not limit or count < limit

    def select(self, message: str, *, group_id: str = "", user_id: str = "", now: datetime | None = None) -> Candidate | None:
        if not self._global_scope_allowed(str(group_id), str(user_id)):
            return None
        current = now or datetime.now().astimezone()
        for candidate in matching_candidates(self.store.state.get("rules", []), message, group_id=group_id, user_id=user_id, now=current):
            if self._eligible(candidate, str(user_id), str(group_id), current):
                return candidate
        return None

    def record_trigger(self, rule_id: str, *, user_id: str = "", group_id: str = "", now: datetime | None = None) -> None:
        current = now or datetime.now().astimezone()
        stamp = current.timestamp()
        usage = self._usage(rule_id)
        usage["last"] = stamp
        if user_id:
            usage["users"][str(user_id)] = stamp
        if group_id:
            usage["groups"][str(group_id)] = stamp
        today = current.date().isoformat()
        usage["daily"][today] = int(usage["daily"].get(today, 0) or 0) + 1
        for key in list(usage["daily"]):
            if key != today:
                try:
                    if (current.date() - datetime.fromisoformat(key).date()).days > 7:
                        usage["daily"].pop(key, None)
                except ValueError:
                    usage["daily"].pop(key, None)
        for key in ("users", "groups"):
            if len(usage[key]) > 5000:
                ordered = sorted(usage[key].items(), key=lambda pair: float(pair[1]))[-2500:]
                usage[key] = dict(ordered)
        for rule in self.store.state.get("rules", []):
            if rule.get("id") == rule_id:
                stats = rule.setdefault("stats", {})
                stats["trigger_count"] = int(stats.get("trigger_count", 0) or 0) + 1
                stats["last_trigger_at"] = utc_now()
                rule["updated_at"] = utc_now()
                break
        self.store.save()

    def choose_reply(self, rule: dict[str, Any], context: dict[str, Any]) -> Any:
        rule = normalize_rule(rule)
        if rule["reply_type"] == "random":
            options = rule.get("random_replies") or [rule.get("content", "")]
            return render_variables(self.rng.choice(options), context)
        if rule["reply_type"] == "composite":
            raw = rule.get("content", "")
            parts = raw.split("\n") if isinstance(raw, str) else raw
            return render_variables([part for part in parts if str(part).strip()], context)
        if rule["reply_type"] == "media":
            return render_variables(rule.get("components", []), context)
        return render_variables(rule.get("content", ""), context)

    def preview(self, message: str, *, group_id: str = "", user_id: str = "", context: dict[str, Any] | None = None) -> dict[str, Any]:
        candidate = None
        for item in matching_candidates(self.store.state.get("rules", []), message, group_id=group_id, user_id=user_id):
            candidate = item
            break
        if candidate is None:
            return {"matched": False, "reply": "", "rule": None}
        ctx = {**(context or {}), "sender": user_id, "group_id": group_id}
        reply = self.choose_reply(candidate.rule, ctx)
        return {"matched": True, "rule": deepcopy(candidate.rule), "keyword": candidate.keyword, "reply": reply}

    def build_chain(self, reply: Any):
        """Convert a stored reply into AstrBot native components."""
        from astrbot.api.message_components import At, File, Image, Plain, Record, Video

        if isinstance(reply, str):
            return [Plain(reply)] if reply else []
        if isinstance(reply, list) and all(isinstance(item, str) for item in reply):
            return [Plain(item) for item in reply if item]
        components = []
        for item in reply if isinstance(reply, list) else []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "").lower()
            value = str(item.get("value") or item.get("url") or item.get("file") or "")
            if kind == "image":
                components.append(Image.fromURL(value) if value.startswith(("http://", "https://")) else Image.fromFileSystem(value))
            elif kind == "video":
                components.append(Video.fromURL(value) if value.startswith(("http://", "https://")) else Video.fromFileSystem(value))
            elif kind in {"record", "voice"}:
                components.append(Record.fromURL(value) if value.startswith(("http://", "https://")) else Record.fromFileSystem(value))
            elif kind == "file":
                components.append(File(name=str(item.get("name") or "file"), file=value if not value.startswith(("http://", "https://")) else "", url=value if value.startswith(("http://", "https://")) else ""))
            elif kind == "at":
                components.append(At(name=str(item.get("name") or ""), qq=value))
        return components
