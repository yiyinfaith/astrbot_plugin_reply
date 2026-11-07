from __future__ import annotations

import asyncio
import random
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from reply_core import webui
from reply_core.engine import ReplyEngine, render_variables
from reply_core.matcher import allowed_time, matching_candidates, scope_allowed
from reply_core.models import default_rule, normalize_rule
from reply_core.storage import ReplyStore


class ReplyCoreTests(unittest.TestCase):
    def test_all_match_modes_and_stable_priority(self):
        rules = [
            default_rule(name="contains", keywords=["menu"], match_type="contains", priority=1),
            default_rule(name="exact", keywords=["menu"], match_type="exact", priority=4),
            default_rule(name="prefix", keywords=["menu"], match_type="prefix", priority=2),
            default_rule(name="regex", keywords=[r"m.nu"], match_type="regex", priority=0),
        ]
        names = [row.rule["name"] for row in matching_candidates(rules, " MENU ")]
        self.assertEqual(names[0], "exact")
        self.assertIn("contains", names)
        self.assertIn("prefix", names)
        self.assertIn("regex", names)

    def test_scope_priority_and_time_window(self):
        rule = default_rule(keywords=["hello"], scope={"mode": "whitelist", "group_ids": ["g1"], "user_ids": []})
        self.assertTrue(scope_allowed(rule, group_id="g1"))
        self.assertFalse(scope_allowed(rule, group_id="g2"))
        overnight = default_rule(keywords=["hello"], time_range={"start": "23:00", "end": "02:00"})
        self.assertTrue(allowed_time(overnight, datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc)))
        self.assertTrue(allowed_time(overnight, datetime(2026, 1, 2, 1, 30, tzinfo=timezone.utc)))
        self.assertFalse(allowed_time(overnight, datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)))

    def test_random_reply_and_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReplyStore(directory)
            engine = ReplyEngine(store, rng=random.Random(2))
            rule = default_rule(reply_type="random", keywords=["hi"], random_replies=["{nickname}", "{sender}"])
            store.upsert_rule(rule)
            self.assertEqual(engine.choose_reply(rule, {"nickname": "小吟", "sender": "42"}), "小吟")
            self.assertEqual(render_variables("{unknown} {sender}", {"sender": "42"}), "{unknown} 42")

    def test_cooldown_and_persistent_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReplyStore(directory)
            engine = ReplyEngine(store)
            rule = default_rule(keywords=["ping"], content="pong", cooldown={"user_seconds": 60})
            store.upsert_rule(rule)
            first = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            self.assertIsNotNone(engine.select("ping", user_id="u1", now=first))
            engine.record_trigger(rule["id"], user_id="u1", now=first)
            self.assertIsNone(engine.select("ping", user_id="u1", now=datetime(2026, 1, 1, 0, 0, 30, tzinfo=timezone.utc)))
            self.assertIsNotNone(engine.select("ping", user_id="u1", now=datetime(2026, 1, 1, 0, 1, 1, tzinfo=timezone.utc)))
            reloaded = ReplyStore(directory)
            self.assertEqual(reloaded.state["rules"][0]["stats"]["trigger_count"], 1)

    def test_webui_requires_authenticated_admin(self):
        holder = object.__new__(webui.ReplyWebUI)
        holder.store = SimpleNamespace(state={"settings": {"webui_admins": []}})
        with patch.object(webui, "request", SimpleNamespace(username=None)):
            response = holder._guard()
            self.assertEqual(getattr(response, "status_code", None), 401)
        holder.store.state["settings"]["webui_admins"] = ["root"]
        with patch.object(webui, "request", SimpleNamespace(username="guest")):
            response = holder._guard()
            self.assertEqual(getattr(response, "status_code", None), 403)
        with patch.object(webui, "request", SimpleNamespace(username="root")):
            self.assertIsNone(holder._guard())

    def test_folder_crud_move_and_delete_preserves_replies(self):
        self.assertEqual(normalize_rule({})["folder_id"], "")
        with tempfile.TemporaryDirectory() as directory:
            store = ReplyStore(directory)
            folder = store.upsert_folder({"name": "菜单", "description": "常用菜单"})
            reply = default_rule(name="帮助", keywords=["help"], content="ok")
            reply = store.upsert_rule(reply)
            moved = store.set_rule_folder(reply["id"], folder["id"])
            self.assertEqual(moved["folder_id"], folder["id"])
            self.assertEqual(store.list_folders()[0]["name"], "菜单")
            updated = store.upsert_folder({"id": folder["id"], "name": "菜单回复", "description": "更新"})
            self.assertEqual(updated["name"], "菜单回复")
            self.assertTrue(store.delete_folder(folder["id"]))
            self.assertEqual(store.state["rules"][0]["folder_id"], "")
            self.assertEqual(store.state["rules"][0]["name"], "帮助")

    def test_folder_webui_api_requires_auth_and_filters(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReplyStore(directory)
            engine = ReplyEngine(store)
            holder = object.__new__(webui.ReplyWebUI)
            holder.store = store
            holder.engine = engine

            class Request:
                username = "root"

                def __init__(self):
                    self.query = {}
                    self.payload = {}

                async def json(self, default=None):
                    return self.payload

            request = Request()
            with patch.object(webui, "request", request):
                request.payload = {"name": "菜单"}
                saved = asyncio.run(holder.save_folder())
                folder = saved["folder"]
                reply = default_rule(name="菜单", keywords=["menu"], content="ok", folder_id=folder["id"])
                store.upsert_rule(reply)
                request.query = {"folder_id": folder["id"]}
                listing = asyncio.run(holder.rules())
                self.assertEqual(listing["total"], 1)
                request.payload = {"id": folder["id"]}
                denied_delete = asyncio.run(holder.delete_folder())
                self.assertEqual(denied_delete.status_code, 400)
                request.payload = {"id": folder["id"], "confirm": True}
                self.assertTrue(asyncio.run(holder.delete_folder())["deleted"])


if __name__ == "__main__":
    unittest.main()
