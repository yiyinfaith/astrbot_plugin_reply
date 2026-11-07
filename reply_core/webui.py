"""Authenticated AstrBot plugin-page API for reply rule administration."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from uuid import uuid4

try:  # Keep pure unit tests runnable without installing the full AstrBot extras.
    from astrbot.api import logger
    from astrbot.api.web import error_response, json_response, request
except ImportError:  # pragma: no cover - only used outside an AstrBot runtime
    import logging
    from types import SimpleNamespace

    logger = logging.getLogger("astrbot_plugin_reply")

    def error_response(message, status_code=400):
        return SimpleNamespace(status_code=status_code, message=message)

    def json_response(payload):
        return payload

    request = SimpleNamespace(username=None, query={}, json=None)

from .engine import ReplyEngine
from .models import DEFAULT_SETTINGS, normalize_rule, utc_now


class ReplyWebUI:
    PREFIXES = ("astrbot_plugin_reply", "reply")

    def __init__(self, context, store, engine: ReplyEngine):
        self.context = context
        self.store = store
        self.engine = engine
        self._register_routes()

    def _register_routes(self) -> None:
        routes = (
            ("overview", self.overview, ["GET"]),
            ("rules", self.rules, ["GET"]),
            ("rules/<rule_id>", self.rule, ["GET"]),
            ("rules/save", self.save_rule, ["POST"]),
            ("rules/delete", self.delete_rule, ["POST"]),
            ("rules/toggle", self.toggle_rule, ["POST"]),
            ("rules/duplicate", self.duplicate_rule, ["POST"]),
            ("test", self.test_rule, ["POST"]),
            ("export", self.export_rules, ["GET"]),
            ("import", self.import_rules, ["POST"]),
            ("stats", self.stats, ["GET"]),
            ("settings", self.settings, ["GET"]),
            ("settings/save", self.save_settings, ["POST"]),
        )
        for prefix in self.PREFIXES:
            for endpoint, handler, methods in routes:
                self.context.register_web_api(f"/{prefix}/{endpoint}", handler, methods, f"Reply WebUI: {endpoint}")

    def _guard(self):
        username = getattr(request, "username", None)
        if not isinstance(username, str) or not username.strip():
            return error_response("请先登录 AstrBot 管理面板。", status_code=401)
        allowed = self.store.state.get("settings", {}).get("webui_admins", [])
        if allowed and username not in {str(item) for item in allowed}:
            return error_response("当前账号没有回复管理权限。", status_code=403)
        return None

    @staticmethod
    def _validate_rule(rule: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        normalized = normalize_rule(rule)
        if not normalized["name"]:
            return None, "规则名称不能为空"
        if not normalized["keywords"]:
            return None, "至少填写一个关键词"
        if normalized["reply_type"] == "text" and not normalized["content"]:
            return None, "固定文本回复不能为空"
        if normalized["reply_type"] == "random" and not normalized["random_replies"]:
            return None, "随机回复至少需要一条内容"
        if normalized["reply_type"] == "media" and not normalized["components"]:
            return None, "多媒体回复至少需要一个消息组件"
        if normalized["match_type"] == "regex":
            for keyword in normalized["keywords"]:
                try:
                    re.compile(keyword)
                except re.error as exc:
                    return None, f"正则表达式无效：{exc}"
        for value in normalized["time_range"].values():
            if value and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                return None, "允许时间段必须使用 HH:MM 格式"
        for component in normalized["components"]:
            kind = component.get("type")
            if kind != "at" and not str(component.get("value") or component.get("url") or component.get("file") or "").strip():
                return None, f"{kind} 组件缺少资源地址或路径"
        return normalized, None

    async def overview(self):
        if (failure := self._guard()) is not None:
            return failure
        rules = self.store.state.get("rules", [])
        enabled = [row for row in rules if row.get("enabled")]
        top = sorted(rules, key=lambda row: int((row.get("stats") or {}).get("trigger_count", 0) or 0), reverse=True)[:5]
        return json_response({
            "total": len(rules),
            "enabled": len(enabled),
            "disabled": len(rules) - len(enabled),
            "top_rules": [{"id": row["id"], "name": row["name"], "trigger_count": row.get("stats", {}).get("trigger_count", 0)} for row in top],
            "settings": deepcopy(self.store.state.get("settings", {})),
        })

    async def rules(self):
        if (failure := self._guard()) is not None:
            return failure
        query = request.query
        search = str(query.get("search", "") or "").casefold()
        match_type = str(query.get("match_type", "") or "").lower()
        group_id = str(query.get("group_id", "") or "").strip()
        enabled = str(query.get("enabled", "") or "").lower()
        try:
            page = max(1, int(query.get("page", 1) or 1))
            page_size = max(1, min(100, int(query.get("page_size", 20) or 20)))
        except (TypeError, ValueError):
            return error_response("分页参数无效", status_code=400)
        rows = []
        for row in self.store.state.get("rules", []):
            haystack = " ".join([row.get("name", ""), *row.get("keywords", [])]).casefold()
            if search and search not in haystack:
                continue
            if match_type and row.get("match_type") != match_type:
                continue
            if enabled in {"true", "false"} and row.get("enabled") is not (enabled == "true"):
                continue
            if group_id:
                scope = row.get("scope", {})
                if group_id not in {str(item) for item in scope.get("group_ids", [])}:
                    continue
            rows.append(deepcopy(row))
        rows.sort(key=lambda row: (-int(row.get("priority", 0)), str(row.get("name", "")).casefold(), row.get("id", "")))
        total = len(rows)
        start = (page - 1) * page_size
        return json_response({"rows": rows[start : start + page_size], "total": total, "page": page, "page_size": page_size, "total_pages": max(1, (total + page_size - 1) // page_size)})

    async def rule(self, rule_id: str):
        if (failure := self._guard()) is not None:
            return failure
        for row in self.store.state.get("rules", []):
            if row.get("id") == rule_id:
                return json_response(deepcopy(row))
        return error_response("未找到规则", status_code=404)

    async def save_rule(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        rule, error = self._validate_rule(payload)
        if error:
            return error_response(error, status_code=400)
        try:
            saved = self.store.upsert_rule(rule)
        except (OSError, ValueError, TypeError) as exc:
            logger.exception("回复规则保存失败")
            return error_response(f"保存失败：{exc}", status_code=500)
        return json_response({"saved": True, "rule": saved})

    async def delete_rule(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        if not isinstance(payload, dict) or not payload.get("confirm"):
            return error_response("删除操作需要二次确认。", status_code=400)
        rule_id = str(payload.get("id") or "").strip()
        if not rule_id:
            return error_response("缺少规则 ID", status_code=400)
        if not self.store.delete_rule(rule_id):
            return error_response("未找到规则", status_code=404)
        return json_response({"deleted": True, "id": rule_id})

    async def toggle_rule(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        if not isinstance(payload, dict) or not payload.get("id") or not isinstance(payload.get("enabled"), bool):
            return error_response("需要 id 和布尔型 enabled", status_code=400)
        for row in self.store.state.get("rules", []):
            if row.get("id") == str(payload["id"]):
                row["enabled"] = payload["enabled"]
                row["updated_at"] = utc_now()
                self.store.save()
                return json_response({"saved": True, "enabled": row["enabled"]})
        return error_response("未找到规则", status_code=404)

    async def duplicate_rule(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        rule_id = str(payload.get("id") or "") if isinstance(payload, dict) else ""
        source = next((row for row in self.store.state.get("rules", []) if row.get("id") == rule_id), None)
        if source is None:
            return error_response("未找到规则", status_code=404)
        copy = deepcopy(source)
        copy["id"] = str(uuid4())
        copy["name"] = f"{copy.get('name', '规则')}（副本）"
        copy["stats"] = {"trigger_count": 0, "last_trigger_at": ""}
        copy["created_at"] = copy["updated_at"] = utc_now()
        self.store.upsert_rule(copy)
        return json_response({"saved": True, "rule": copy})

    async def test_rule(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        message = str(payload.get("message") or "")
        if not message:
            return error_response("模拟消息不能为空", status_code=400)
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        return json_response(self.engine.preview(message, group_id=str(context.get("group_id") or ""), user_id=str(context.get("sender") or ""), context=context))

    async def export_rules(self):
        if (failure := self._guard()) is not None:
            return failure
        return json_response({"schema_version": 2, "exported_at": utc_now(), "rules": deepcopy(self.store.state.get("rules", [])), "settings": deepcopy(self.store.state.get("settings", {}))})

    async def import_rules(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        if not isinstance(payload, dict) or not isinstance(payload.get("rules"), list):
            return error_response("导入文件必须包含 rules 数组", status_code=400)
        validated = []
        for raw in payload["rules"]:
            if not isinstance(raw, dict):
                return error_response("rules 中包含无效项目", status_code=400)
            rule, error = self._validate_rule(raw)
            if error:
                return error_response(f"导入失败：{error}", status_code=400)
            validated.append(rule)
        self.store.replace_rules(validated)
        if isinstance(payload.get("settings"), dict):
            self.store.update_settings(payload["settings"])
        return json_response({"imported": len(validated)})

    async def stats(self):
        if (failure := self._guard()) is not None:
            return failure
        rows = []
        for row in self.store.state.get("rules", []):
            stats = row.get("stats", {})
            rows.append({"id": row["id"], "name": row["name"], "enabled": row["enabled"], "trigger_count": int(stats.get("trigger_count", 0) or 0), "last_trigger_at": stats.get("last_trigger_at", "")})
        rows.sort(key=lambda item: (-item["trigger_count"], item["name"].casefold()))
        return json_response({"rows": rows, "total": len(rows), "most_triggered": rows[0] if rows else None})

    async def settings(self):
        if (failure := self._guard()) is not None:
            return failure
        return json_response(deepcopy(self.store.state.get("settings", DEFAULT_SETTINGS)))

    async def save_settings(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        settings = self.store.update_settings(payload)
        return json_response({"saved": True, "settings": settings})
