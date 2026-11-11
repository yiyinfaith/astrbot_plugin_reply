"""AstrBot Reply plugin entry point."""

from __future__ import annotations

from typing import Any

from astrbot.api import logger
from astrbot.api.event.filter import EventMessageType, event_message_type
from astrbot.api.star import Context, Star, StarTools

from .reply_core.engine import ReplyEngine
from .reply_core.storage import ReplyStore
from .reply_core.webui import PLUGIN_NAME, ReplyWebUI


class KeywordReplyPlugin(Star):
    """Native AstrBot message handler backed by an atomic JSON rule store."""

    def __init__(self, context: Context, config: Any | None = None):
        super().__init__(context)
        self.context = context
        self.config = config
        self.data_dir = StarTools.get_data_dir(PLUGIN_NAME)
        self.store = ReplyStore(self.data_dir)
        self.engine = ReplyEngine(self.store)
        self.webui = ReplyWebUI(context, self.store, self.engine)
        logger.info(
            "回复管理已加载：%d 条回复（启用 %d 条），数据目录：%s",
            len(self.store.state.get("rules", [])),
            sum(1 for rule in self.store.state.get("rules", []) if rule.get("enabled")),
            self.data_dir,
        )

    async def terminate(self):
        self.store.close()

    @staticmethod
    async def _lookup_group_name(event) -> str:
        try:
            group = await event.get_group()
        except (AttributeError, LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
            # 群名只用于文本替换，平台接口失败时仍要发送回复。
            logger.warning("查询群名称失败：%s", exc)
            return ""
        return str(getattr(group, "group_name", "") or "")

    @event_message_type(EventMessageType.ALL)
    async def handle_message(self, event):
        settings = self.store.state.get("settings", {})
        if settings.get("require_wake", True) and not getattr(event, "is_at_or_wake_command", False):
            return
        try:
            message = event.get_message_str() if hasattr(event, "get_message_str") else getattr(event, "message_str", "")
            message = str(message or "").strip()
            if not message:
                return
            user_id = str(event.get_sender_id() or "") if hasattr(event, "get_sender_id") else ""
            group_id = str(event.get_group_id() or "") if hasattr(event, "get_group_id") else ""
            candidate = self.engine.select(message, user_id=user_id, group_id=group_id)
            if candidate is None:
                return
            context = self.engine.event_context(event)
            if group_id and not context["group_name"] and self.engine.uses_group_name(candidate.rule):
                context["group_name"] = await self._lookup_group_name(event)
                # 查询期间其他消息可能已占用冷却或每日次数，需要重新判定。
                candidate = self.engine.select(message, user_id=user_id, group_id=group_id)
                if candidate is None:
                    return
            reply = self.engine.choose_reply(candidate.rule, context)
            messages = self.engine.build_messages(reply)
            if not messages:
                logger.warning("回复 %s 生成了空消息链，跳过发送", candidate.rule.get("id"))
                return
            self.engine.record_trigger(candidate.rule["id"], user_id=user_id, group_id=group_id)
            for chain in messages:
                yield event.chain_result(chain)
        except (AttributeError, ImportError, IndexError, KeyError, LookupError, OSError, RuntimeError, TypeError, ValueError):
            logger.exception("自定义回复执行失败")
