"""Authenticated AstrBot plugin-page API for reply rule administration."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, cast
from uuid import uuid4

from astrbot.api import logger
from astrbot.api.web import error_response, json_response, request

from .engine import ReplyEngine
from .matcher import regex_error
from .models import (
    DEFAULT_SETTINGS,
    MATCH_TYPES,
    REPLY_TYPES,
    SCOPE_MODES,
    normalize_folder,
    normalize_rule,
    utc_now,
)

PLUGIN_NAME = "astrbot_plugin_reply"


class ReplyWebUI:
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
            ("rules/move", self.move_rule, ["POST"]),
            ("folders", self.folders, ["GET"]),
            ("folders/save", self.save_folder, ["POST"]),
            ("folders/delete", self.delete_folder, ["POST"]),
            ("test", self.test_rule, ["POST"]),
            ("export", self.export_rules, ["GET"]),
            ("import", self.import_rules, ["POST"]),
            ("stats", self.stats, ["GET"]),
            ("settings", self.settings, ["GET"]),
            ("settings/save", self.save_settings, ["POST"]),
        )
        for endpoint, handler, methods in routes:
            self.context.register_web_api(f"/{PLUGIN_NAME}/{endpoint}", handler, methods, f"Reply WebUI: {endpoint}")

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
        if not str(rule.get("name") or "").strip():
            return None, "回复名称不能为空"
        raw_match_type = str(rule.get("match_type") or "exact").strip().lower()
        if raw_match_type not in MATCH_TYPES:
            return None, "匹配方式无效"
        raw_reply_type = str(rule.get("reply_type") or "text").strip().lower()
        if raw_reply_type not in REPLY_TYPES:
            return None, "回复类型无效"
        raw_keywords = rule.get("keywords")
        if isinstance(raw_keywords, str):
            raw_keywords = raw_keywords.replace("\r\n", "\n").split("\n")
        if isinstance(raw_keywords, (list, tuple)) and any(len(str(item)) > 2000 for item in raw_keywords):
            return None, "单个关键词长度不能超过 2000 个字符"
        if "time_range" in rule and rule.get("time_range") is not None and not isinstance(rule.get("time_range"), dict):
            return None, "允许时间段格式无效"
        raw_time = cast(dict[str, Any], rule.get("time_range")) if isinstance(rule.get("time_range"), dict) else {}
        raw_start = str(raw_time.get("start") or "").strip()
        raw_end = str(raw_time.get("end") or "").strip()
        if bool(raw_start) != bool(raw_end):
            return None, "允许时间段必须同时填写开始和结束时间"
        for value in (raw_start, raw_end):
            if value and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                return None, "允许时间段必须使用 HH:MM 格式"
        raw_scope = cast(dict[str, Any], rule.get("scope")) if isinstance(rule.get("scope"), dict) else {}
        raw_scope_mode = str(raw_scope.get("mode") or "blacklist").strip().lower()
        if raw_scope_mode not in SCOPE_MODES:
            return None, "作用域模式无效"
        if "components" in rule and rule.get("components") is not None and not isinstance(rule.get("components"), list):
            return None, "消息组件必须是数组"
        normalized = normalize_rule(rule)
        if not normalized["keywords"]:
            return None, "至少填写一个关键词"
        if normalized["reply_type"] == "text" and not normalized["content"].strip():
            return None, "固定文本回复不能为空"
        if normalized["reply_type"] == "composite" and not normalized["content"].strip():
            return None, "多段文本回复不能为空"
        if normalized["reply_type"] == "composite" and sum(1 for line in normalized["content"].splitlines() if line.strip()) > 100:
            return None, "多段文本最多 100 段，每段会单独发送一条消息"
        if normalized["reply_type"] == "random" and not normalized["random_replies"]:
            return None, "随机回复至少需要一条内容"
        if normalized["reply_type"] == "media" and not normalized["components"]:
            return None, "多媒体回复至少需要一个消息组件"
        if normalized["match_type"] == "regex":
            for keyword in normalized["keywords"]:
                if len(keyword) > 2000:
                    return None, "正则表达式长度不能超过 2000 个字符"
                if problem := regex_error(keyword):
                    return None, f"正则表达式无效：{problem}"
        for component in normalized["components"]:
            kind = component.get("type")
            if not str(component.get("value") or component.get("url") or component.get("file") or "").strip():
                return None, f"{kind} 组件缺少资源地址或路径"
        return normalized, None

    @staticmethod
    def _validate_folder(folder: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        if not str(folder.get("name") or "").strip():
            return None, "文件夹名称不能为空"
        return normalize_folder(folder), None

    async def overview(self):
        if (failure := self._guard()) is not None:
            return failure
        rules = self.store.state.get("rules", [])
        enabled = [row for row in rules if row.get("enabled")]
        top = sorted(rules, key=lambda row: int((row.get("stats") or {}).get("trigger_count", 0) or 0), reverse=True)[:5]
        star = self.context.get_registered_star(PLUGIN_NAME)
        return json_response({
            "version": getattr(star, "version", "") or "",
            "total": len(rules),
            "enabled": len(enabled),
            "disabled": len(rules) - len(enabled),
            "top_rules": [{"id": row["id"], "name": row["name"], "trigger_count": row.get("stats", {}).get("trigger_count", 0)} for row in top],
            "folder_total": len(self.store.state.get("folders", [])),
            "settings": deepcopy(self.store.state.get("settings", {})),
        })

    async def rules(self):
        if (failure := self._guard()) is not None:
            return failure
        query = request.query
        search = str(query.get("search", "") or "").casefold()
        match_type = str(query.get("match_type", "") or "").lower()
        group_id = str(query.get("group_id", "") or "").strip()
        folder_id = str(query.get("folder_id", "") or "").strip()
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
            if folder_id == "__none__" and row.get("folder_id"):
                continue
            if folder_id and folder_id != "__none__" and row.get("folder_id") != folder_id:
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
        return error_response("未找到回复", status_code=404)

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
            logger.exception("自定义回复保存失败")
            return error_response(f"保存失败：{exc}", status_code=400 if isinstance(exc, ValueError) else 500)
        return json_response({"saved": True, "rule": saved})

    async def folders(self):
        if (failure := self._guard()) is not None:
            return failure
        return json_response({"rows": self.store.list_folders(), "total": len(self.store.state.get("folders", []))})

    async def save_folder(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        folder, error = self._validate_folder(payload)
        if error:
            return error_response(error, status_code=400)
        try:
            saved = self.store.upsert_folder(folder)
        except (OSError, ValueError, TypeError) as exc:
            logger.exception("回复文件夹保存失败")
            return error_response(f"保存失败：{exc}", status_code=500 if not isinstance(exc, ValueError) else 400)
        return json_response({"saved": True, "folder": saved})

    async def delete_folder(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        if not isinstance(payload, dict) or payload.get("confirm") is not True:
            return error_response("删除文件夹需要二次确认。", status_code=400)
        folder_id = str(payload.get("id") or "").strip()
        if not folder_id:
            return error_response("缺少文件夹 ID", status_code=400)
        if not self.store.delete_folder(folder_id):
            return error_response("未找到文件夹", status_code=404)
        return json_response({"deleted": True, "id": folder_id})

    async def move_rule(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        if not isinstance(payload, dict) or not payload.get("id"):
            return error_response("需要回复 ID", status_code=400)
        try:
            moved = self.store.set_rule_folder(str(payload["id"]), str(payload.get("folder_id") or ""))
        except ValueError as exc:
            return error_response(str(exc), status_code=400)
        if moved is None:
            return error_response("未找到回复", status_code=404)
        return json_response({"saved": True, "rule": moved})

    async def delete_rule(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        if not isinstance(payload, dict) or payload.get("confirm") is not True:
            return error_response("删除操作需要二次确认。", status_code=400)
        rule_id = str(payload.get("id") or "").strip()
        if not rule_id:
            return error_response("缺少回复 ID", status_code=400)
        if not self.store.delete_rule(rule_id):
            return error_response("未找到回复", status_code=404)
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
        return error_response("未找到回复", status_code=404)

    async def duplicate_rule(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        rule_id = str(payload.get("id") or "") if isinstance(payload, dict) else ""
        source = next((row for row in self.store.state.get("rules", []) if row.get("id") == rule_id), None)
        if source is None:
            return error_response("未找到回复", status_code=404)
        copy = deepcopy(source)
        copy["id"] = str(uuid4())
        copy["name"] = f"{copy.get('name', '回复')}（副本）"
        copy["stats"] = {"trigger_count": 0, "last_trigger_at": ""}
        copy["created_at"] = copy["updated_at"] = utc_now()
        return json_response({"saved": True, "rule": self.store.upsert_rule(copy)})

    async def test_rule(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        message = str(payload.get("message") or "")
        if not message:
            return error_response("模拟消息不能为空", status_code=400)
        context = cast(dict[str, Any], payload.get("context")) if isinstance(payload.get("context"), dict) else {}
        return json_response(self.engine.preview(message, group_id=str(context.get("group_id") or ""), user_id=str(context.get("sender") or ""), context=context))

    async def export_rules(self):
        if (failure := self._guard()) is not None:
            return failure
        return json_response({"schema_version": 2, "exported_at": utc_now(), "folders": deepcopy(self.store.state.get("folders", [])), "rules": deepcopy(self.store.state.get("rules", [])), "settings": deepcopy(self.store.state.get("settings", {}))})

    async def import_rules(self):
        if (failure := self._guard()) is not None:
            return failure
        payload = await request.json(default={})
        if not isinstance(payload, dict) or not isinstance(payload.get("rules"), list):
            return error_response("导入文件必须包含 rules 数组", status_code=400)
        validated = []
        rule_ids: set[str] = set()
        for raw in payload["rules"]:
            if not isinstance(raw, dict):
                return error_response("rules 中包含无效项目", status_code=400)
            rule, error = self._validate_rule(raw)
            if error:
                return error_response(f"导入失败：{error}", status_code=400)
            if rule is None:
                return error_response("导入失败：回复数据无效", status_code=400)
            if rule["id"] in rule_ids:
                return error_response("导入失败：回复 ID 重复", status_code=400)
            rule_ids.add(rule["id"])
            validated.append(rule)
        folders = payload.get("folders", [])
        if not isinstance(folders, list):
            return error_response("folders 必须是数组", status_code=400)
        normalized_folders = []
        folder_ids: set[str] = set()
        for raw_folder in folders:
            if not isinstance(raw_folder, dict):
                return error_response("folders 中包含无效项目", status_code=400)
            folder, error = self._validate_folder(raw_folder)
            if error:
                return error_response(f"导入失败：{error}", status_code=400)
            if folder is None:
                return error_response("导入失败：文件夹数据无效", status_code=400)
            if folder["id"] in folder_ids:
                return error_response("导入失败：文件夹 ID 重复", status_code=400)
            folder_ids.add(folder["id"])
            normalized_folders.append(folder)
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else None
        if settings is not None:
            # A file from another instance must not lock out the current administrators.
            settings = {key: value for key, value in settings.items() if key != "webui_admins"}
        self.store.replace_state(validated, folders=normalized_folders, settings=settings, reset_usage=True)
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
        try:
            settings = self.store.update_settings(payload, acting_admin=request.username)
        except ValueError as exc:
            return error_response(str(exc), status_code=400)
        return json_response({"saved": True, "settings": settings})
