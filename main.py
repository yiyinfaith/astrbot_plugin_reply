"""AstrBot Reply plugin entry point."""

from __future__ import annotations

from typing import Any

from astrbot.api import logger
from astrbot.api.event.filter import EventMessageType, event_message_type
from astrbot.api.star import Context, Star, StarTools, register

from .reply_core.engine import ReplyEngine
from .reply_core.storage import ReplyStore
from .reply_core.webui import ReplyWebUI

PLUGIN_NAME = "astrbot_plugin_reply"


@register(
    name="reply",
    desc="回复管理：关键词匹配、动态回复、作用域、冷却和 WebUI 规则管理。",
    version="v1.0.0",
    author="一吟Faith",
    repo="https://github.com/yiyinfaith/astrbot_plugin_reply",
)
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
            "回复管理已加载：%d 条规则（启用 %d 条），数据目录：%s",
            len(self.store.state.get("rules", [])),
            sum(1 for rule in self.store.state.get("rules", []) if rule.get("enabled")),
            self.data_dir,
        )

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
            reply = self.engine.choose_reply(candidate.rule, context)
            chain = self.engine.build_chain(reply)
            if not chain:
                logger.warning("规则 %s 生成了空消息链，跳过发送", candidate.rule.get("id"))
                return
            self.engine.record_trigger(candidate.rule["id"], user_id=user_id, group_id=group_id)
            yield event.chain_result(chain)
        except (AttributeError, ImportError, IndexError, KeyError, LookupError, OSError, RuntimeError, TypeError, ValueError):
            logger.exception("回复规则执行失败")
