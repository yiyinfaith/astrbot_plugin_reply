"""Data model and validation helpers for reply rules.

The JSON representation is deliberately plain so it remains easy to export,
inspect, and migrate without adding a runtime dependency.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

MATCH_TYPES = {"exact", "contains", "prefix", "regex"}
REPLY_TYPES = {"text", "random", "composite", "media"}
SCOPE_MODES = {"blacklist", "whitelist"}
MEDIA_TYPES = {"image", "video", "record", "voice", "file", "at"}

DEFAULT_SETTINGS: dict[str, Any] = {
    "require_wake": True,
    "scope_mode": "blacklist",
    "group_ids": [],
    "user_ids": [],
    "webui_admins": [],
    "normalization": {"unicode_nfkc": True, "collapse_whitespace": True},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_rule(**overrides: Any) -> dict[str, Any]:
    now = utc_now()
    rule: dict[str, Any] = {
        "id": str(uuid4()),
        "name": "新回复规则",
        "keywords": [],
        "match_type": "exact",
        "case_sensitive": False,
        "reply_type": "text",
        "content": "",
        "random_replies": [],
        "components": [],
        "scope": {"mode": "blacklist", "group_ids": [], "user_ids": []},
        "priority": 0,
        "enabled": True,
        "cooldown": {"rule_seconds": 0, "user_seconds": 0, "group_seconds": 0},
        "daily_limit": 0,
        "time_range": {"start": "", "end": ""},
        "stats": {"trigger_count": 0, "last_trigger_at": ""},
        "created_at": now,
        "updated_at": now,
    }
    rule.update(deepcopy(overrides))
    return normalize_rule(rule)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = value.replace("\r\n", "\n").split("\n")
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _non_negative_int(value: Any, default: int = 0, maximum: int = 365 * 24 * 3600) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(number, maximum))


def normalize_rule(raw: Any) -> dict[str, Any]:
    """Return a safe, complete rule copy suitable for storage and runtime."""
    source = raw if isinstance(raw, dict) else {}
    base = default_rule() if not isinstance(raw, dict) else deepcopy(raw)
    base["id"] = str(base.get("id") or uuid4())[:80]
    base["name"] = str(base.get("name") or "未命名规则").strip()[:120]
    base["keywords"] = _string_list(base.get("keywords"))[:100]
    base["match_type"] = str(base.get("match_type") or "exact").lower()
    if base["match_type"] not in MATCH_TYPES:
        base["match_type"] = "exact"
    base["case_sensitive"] = bool(base.get("case_sensitive", False))
    base["reply_type"] = str(base.get("reply_type") or "text").lower()
    if base["reply_type"] not in REPLY_TYPES:
        base["reply_type"] = "text"
    base["content"] = str(base.get("content") or "")[:100_000]
    base["random_replies"] = [str(x)[:100_000] for x in _string_list(base.get("random_replies"))[:100]]
    components = base.get("components")
    if not isinstance(components, list):
        components = []
    safe_components: list[dict[str, Any]] = []
    for item in components[:100]:
        if not isinstance(item, dict):
            continue
        component = {str(k): v for k, v in item.items() if isinstance(k, str) and len(k) < 64}
        component["type"] = str(component.get("type") or "").lower()
        if component["type"] in MEDIA_TYPES:
            safe_components.append(component)
    base["components"] = safe_components
    scope = base.get("scope") if isinstance(base.get("scope"), dict) else {}
    mode = str(scope.get("mode") or "blacklist").lower()
    base["scope"] = {
        "mode": mode if mode in SCOPE_MODES else "blacklist",
        "group_ids": _string_list(scope.get("group_ids"))[:1000],
        "user_ids": _string_list(scope.get("user_ids"))[:1000],
    }
    try:
        priority = int(source.get("priority", 0) or 0)
    except (TypeError, ValueError):
        priority = 0
    base["priority"] = max(-100_000, min(priority, 100_000))
    base["enabled"] = bool(base.get("enabled", True))
    cooldown = base.get("cooldown") if isinstance(base.get("cooldown"), dict) else {}
    base["cooldown"] = {
        "rule_seconds": _non_negative_int(cooldown.get("rule_seconds")),
        "user_seconds": _non_negative_int(cooldown.get("user_seconds")),
        "group_seconds": _non_negative_int(cooldown.get("group_seconds")),
    }
    base["daily_limit"] = _non_negative_int(base.get("daily_limit"), 0, 1_000_000)
    time_range = base.get("time_range") if isinstance(base.get("time_range"), dict) else {}
    base["time_range"] = {
        "start": str(time_range.get("start") or "")[:5],
        "end": str(time_range.get("end") or "")[:5],
    }
    stats = base.get("stats") if isinstance(base.get("stats"), dict) else {}
    base["stats"] = {
        "trigger_count": _non_negative_int(stats.get("trigger_count"), 0, 2_147_483_647),
        "last_trigger_at": str(stats.get("last_trigger_at") or ""),
    }
    base["created_at"] = str(base.get("created_at") or utc_now())
    base["updated_at"] = str(base.get("updated_at") or utc_now())
    return base
