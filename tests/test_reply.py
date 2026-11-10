from __future__ import annotations

import asyncio
import importlib
import json
import random
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from reply_core import webui
from reply_core.engine import ReplyEngine, render_variables
from reply_core.matcher import (
    allowed_time,
    match_keyword,
    matching_candidates,
    scope_allowed,
)
from reply_core.models import default_rule, normalize_rule
from reply_core.storage import ReplyStore

ROOT = Path(__file__).resolve().parents[1]


def load_plugin_main():
    """Import main.py as a package so its relative imports resolve."""
    package = sys.modules.get("astrbot_plugin_reply")
    if package is None:
        package = types.ModuleType("astrbot_plugin_reply")
        package.__path__ = [str(ROOT)]
        sys.modules["astrbot_plugin_reply"] = package
    return importlib.import_module("astrbot_plugin_reply.main")


class FakeRequest:
    def __init__(self, username="root"):
        self.username = username
        self.query = {}
        self.payload = {}

    async def json(self, default=None):
        return self.payload


def web_patches(request):
    """Use plain payloads so assertions work against stubs and real AstrBot."""
    return patch.multiple(
        webui,
        request=request,
        json_response=lambda payload: payload,
        error_response=lambda message, status_code=400: SimpleNamespace(status_code=status_code, message=message),
    )


def webui_holder(store):
    holder = object.__new__(webui.ReplyWebUI)
    holder.store = store
    holder.engine = ReplyEngine(store)
    holder.context = SimpleNamespace(get_registered_star=lambda name: SimpleNamespace(version="v9.9.9"))
    return holder


class FakeEvent:
    def __init__(self, message="ping", group_id="g1", group=None, is_wake=True, group_lookup=None):
        self.message_str = message
        self.is_at_or_wake_command = is_wake
        self.message_obj = SimpleNamespace(group=group)
        self._group_id = group_id
        self._group_lookup = group_lookup
        self.group_lookups = 0
        self.results = []

    def get_message_str(self):
        return self.message_str

    def get_sender_id(self):
        return "u1"

    def get_sender_name(self):
        return "小吟"

    def get_group_id(self):
        return self._group_id

    async def get_group(self):
        self.group_lookups += 1
        if isinstance(self._group_lookup, Exception):
            raise self._group_lookup
        return self._group_lookup

    def chain_result(self, chain):
        return chain


def run_handler(plugin, event):
    async def collect():
        return [item async for item in plugin.handle_message(event)]

    return asyncio.run(collect())


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
        self.assertFalse(allowed_time(default_rule(keywords=["hello"], time_range={"start": "09:00", "end": ""}), datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc)))

    def test_boolean_and_normalization_settings_are_safe(self):
        rule = default_rule(enabled="false", case_sensitive="false", keywords=["hello"])
        self.assertFalse(rule["enabled"])
        self.assertFalse(rule["case_sensitive"])
        with tempfile.TemporaryDirectory() as directory:
            store = ReplyStore(directory)
            settings = store.update_settings({"require_wake": "false", "normalization": {"collapse_whitespace": False}})
            self.assertFalse(settings["require_wake"])
            self.assertFalse(settings["normalization"]["collapse_whitespace"])

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

    def test_malformed_usage_and_global_scope_preview_fail_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReplyStore(directory)
            store.state["usage"] = {"bad": {"last": "not-a-number", "users": [], "groups": {}, "daily": {"today": "bad"}}}
            rule = default_rule(name="受限", keywords=["secret"], content="no", scope={"mode": "whitelist", "group_ids": ["g1"], "user_ids": []})
            store.upsert_rule(rule)
            engine = ReplyEngine(store)
            self.assertIsNone(engine.select("secret", group_id="g2"))
            self.assertFalse(engine.preview("secret", group_id="g2")["matched"])
            self.assertIsNotNone(engine.select("secret", group_id="g1"))

    def test_import_replaces_rules_atomically_and_preserves_unspecified_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReplyStore(directory)
            store.update_settings({"user_ids": ["u1"], "normalization": {"collapse_whitespace": False}})
            store.upsert_rule(default_rule(name="old", keywords=["old"], content="old"))
            store.replace_state(
                [default_rule(name="new", keywords=["new"], content="new")],
                folders=[],
                settings={"scope_mode": "whitelist"},
                reset_usage=True,
            )
            self.assertEqual([row["name"] for row in store.state["rules"]], ["new"])
            self.assertEqual(store.state["settings"]["user_ids"], ["u1"])
            self.assertFalse(store.state["settings"]["normalization"]["collapse_whitespace"])
            self.assertEqual(store.state["settings"]["scope_mode"], "whitelist")

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

            request = FakeRequest()
            with web_patches(request):
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
                request.payload = {"id": folder["id"], "confirm": "false"}
                denied_string_delete = asyncio.run(holder.delete_folder())
                self.assertEqual(denied_string_delete.status_code, 400)
                request.payload = {"id": folder["id"], "confirm": True}
                self.assertTrue(asyncio.run(holder.delete_folder())["deleted"])

    def test_webui_rejects_unsafe_or_incomplete_reply_payloads(self):
        holder = object.__new__(webui.ReplyWebUI)
        invalid_name, error = holder._validate_rule({"keywords": ["x"], "content": "ok"})
        self.assertIsNone(invalid_name)
        self.assertIn("名称", error)
        invalid_time, error = holder._validate_rule({"name": "x", "keywords": ["x"], "content": "ok", "time_range": {"start": "09:00", "end": ""}})
        self.assertIsNone(invalid_time)
        self.assertIn("同时", error)
        invalid_at, error = holder._validate_rule({"name": "x", "keywords": ["x"], "reply_type": "media", "components": [{"type": "at"}]})
        self.assertIsNone(invalid_at)
        self.assertIn("at", error)

    def test_composite_reply_keeps_line_breaks_in_one_message(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = ReplyEngine(ReplyStore(directory))
            rule = default_rule(reply_type="composite", keywords=["x"], content="第一段\n\n第二段")
            chain = engine.build_chain(engine.choose_reply(rule, {}))
            self.assertEqual([item.text for item in chain], ["第一段\n第二段"])

    def test_group_name_comes_from_message_group(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = ReplyEngine(ReplyStore(directory))
            event = FakeEvent(group=SimpleNamespace(group_id="g1", group_name="吟窝"))
            self.assertEqual(engine.event_context(event)["group_name"], "吟窝")
            self.assertEqual(engine.event_context(FakeEvent(group=None))["group_name"], "")

    def _plugin_with_rule(self, directory, **fields):
        main = load_plugin_main()
        plugin = object.__new__(main.KeywordReplyPlugin)
        plugin.store = ReplyStore(directory)
        plugin.engine = ReplyEngine(plugin.store)
        rule = default_rule(name="r", keywords=["ping"], **fields)
        plugin.store.upsert_rule(rule)
        return plugin

    def test_handler_looks_up_group_name_only_when_the_reply_uses_it(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = self._plugin_with_rule(directory, content="欢迎来到 {group_name}")
            event = FakeEvent(group=SimpleNamespace(group_id="g1", group_name=None), group_lookup=SimpleNamespace(group_name="吟窝"))
            self.assertEqual(run_handler(plugin, event)[0][0].text, "欢迎来到 吟窝")
            self.assertEqual(event.group_lookups, 1)
        with tempfile.TemporaryDirectory() as directory:
            plugin = self._plugin_with_rule(directory, content="pong")
            event = FakeEvent()
            self.assertEqual(run_handler(plugin, event)[0][0].text, "pong")
            self.assertEqual(event.group_lookups, 0)

    def test_handler_still_replies_when_group_lookup_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = self._plugin_with_rule(directory, content="群：{group_name}")
            event = FakeEvent(group_lookup=ConnectionError("platform down"))
            self.assertEqual(run_handler(plugin, event)[0][0].text, "群：")

    def test_group_lookup_does_not_let_concurrent_messages_skip_the_cooldown(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = self._plugin_with_rule(directory, content="{group_name}", cooldown={"rule_seconds": 3600})
            rule_id = plugin.store.state["rules"][0]["id"]

            class RacingEvent(FakeEvent):
                async def get_group(self):
                    plugin.engine.record_trigger(rule_id, user_id="other")
                    return SimpleNamespace(group_name="吟窝")

            self.assertEqual(run_handler(plugin, RacingEvent()), [])

    def test_media_with_empty_value_after_rendering_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = ReplyEngine(ReplyStore(directory))
            self.assertEqual(engine.build_chain([{"type": "image", "value": ""}, {"type": "at", "value": ""}]), [])

    def test_file_without_display_name_uses_the_real_file_name(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = ReplyEngine(ReplyStore(directory))
            local, remote, named = engine.build_chain([
                {"type": "file", "value": "/data/report.pdf"},
                {"type": "file", "value": "https://example.com/a/b.zip?x=1"},
                {"type": "file", "value": "/data/report.pdf", "name": "周报"},
            ])
            self.assertEqual((local.name, remote.name, named.name), ("report.pdf", "b.zip", "周报"))

    def test_editing_a_reply_keeps_its_live_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReplyStore(directory)
            saved = store.upsert_rule(default_rule(name="a", keywords=["a"], content="a"))
            ReplyEngine(store).record_trigger(saved["id"])
            store.upsert_rule({**saved, "content": "edited"})
            self.assertEqual(store.state["rules"][0]["content"], "edited")
            self.assertEqual(store.state["rules"][0]["stats"]["trigger_count"], 1)

    def test_infinite_numbers_do_not_crash_normalization(self):
        rule = normalize_rule({"keywords": ["x"], "priority": float("inf"), "daily_limit": float("inf"), "cooldown": {"rule_seconds": float("-inf")}})
        self.assertEqual((rule["priority"], rule["daily_limit"], rule["cooldown"]["rule_seconds"]), (0, 0, 0))

    def test_corrupt_state_file_is_kept_instead_of_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reply_rules.json"
            path.write_text("{broken", encoding="utf-8")
            store = ReplyStore(directory)
            self.assertEqual(store.state["rules"], [])
            store.save()
            kept = list(Path(directory).glob("reply_rules.json.corrupt-*"))
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0].read_text(encoding="utf-8"), "{broken")

    def test_malformed_state_collections_do_not_block_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reply_rules.json"
            path.write_text(json.dumps({"rules": 3, "folders": None}), encoding="utf-8")
            store = ReplyStore(directory)
            self.assertEqual((store.state["rules"], store.state["folders"]), ([], []))

    def test_blank_text_and_composite_replies_are_rejected(self):
        holder = object.__new__(webui.ReplyWebUI)
        for reply_type in ("text", "composite"):
            rule, error = holder._validate_rule({"name": "x", "keywords": ["x"], "reply_type": reply_type, "content": " \n "})
            self.assertIsNone(rule, reply_type)
            self.assertIn("不能为空", error)

    def test_oversized_regex_is_a_validation_error_and_never_raises_at_runtime(self):
        holder = object.__new__(webui.ReplyWebUI)
        rule, error = holder._validate_rule({"name": "x", "keywords": ["a{99999999999}"], "match_type": "regex", "content": "ok"})
        self.assertIsNone(rule)
        self.assertIn("正则", error)
        bad = default_rule(keywords=["a{99999999999}"], match_type="regex", content="ok")
        self.assertEqual(match_keyword(bad, "aaa"), (False, 0, ""))

    def test_time_range_with_spaces_is_normalized_exactly(self):
        rule = normalize_rule({"keywords": ["x"], "time_range": {"start": " 09:30", "end": "10:45 "}})
        self.assertEqual(rule["time_range"], {"start": "09:30", "end": "10:45"})

    def test_preview_renders_every_documented_variable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReplyStore(directory)
            store.upsert_rule(default_rule(name="v", keywords=["v"], content="{nickname}|{time}|{date}|{random}"))
            result = ReplyEngine(store).preview("v", user_id="42", context={"sender": "42"})
            nickname, clock, date, number = result["reply"].split("|")
            self.assertEqual(nickname, "42")
            self.assertRegex(clock, r"^\d{2}:\d{2}:\d{2}$")
            self.assertRegex(date, r"^\d{4}-\d{2}-\d{2}$")
            self.assertRegex(number, r"^\d+$")

    def test_settings_drop_unknown_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = ReplyStore(directory).update_settings({"scope_mode": "whitelist", "evil": {"x": 1}})
            self.assertNotIn("evil", settings)
            self.assertEqual(settings["scope_mode"], "whitelist")

    def test_admin_cannot_lock_themselves_out(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReplyStore(directory)
            holder = webui_holder(store)
            request = FakeRequest(username="root")
            with web_patches(request):
                request.payload = {"webui_admins": ["someone-else"]}
                denied = asyncio.run(holder.save_settings())
                self.assertEqual(denied.status_code, 400)
                self.assertEqual(store.state["settings"]["webui_admins"], [])
                request.payload = {"webui_admins": ["root", "someone-else"]}
                self.assertTrue(asyncio.run(holder.save_settings())["saved"])
                self.assertEqual(store.state["settings"]["webui_admins"], ["root", "someone-else"])

    def test_import_cannot_replace_webui_admins(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReplyStore(directory)
            store.update_settings({"webui_admins": ["root"]})
            holder = webui_holder(store)
            request = FakeRequest(username="root")
            with web_patches(request):
                request.payload = {"rules": [], "settings": {"webui_admins": ["attacker"], "scope_mode": "whitelist"}}
                self.assertEqual(asyncio.run(holder.import_rules())["imported"], 0)
            self.assertEqual(store.state["settings"]["webui_admins"], ["root"])
            self.assertEqual(store.state["settings"]["scope_mode"], "whitelist")

    def test_routes_use_only_the_plugin_name_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReplyStore(directory)
            routes = []
            webui.ReplyWebUI(SimpleNamespace(register_web_api=lambda route, *_: routes.append(route)), store, ReplyEngine(store))
            self.assertIn("/astrbot_plugin_reply/rules/<rule_id>", routes)
            self.assertTrue(all(route.startswith("/astrbot_plugin_reply/") for route in routes))

    def test_duplicate_returns_the_normalized_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReplyStore(directory)
            holder = webui_holder(store)
            source = store.upsert_rule(default_rule(name="长" * 120, keywords=["x"], content="ok"))
            request = FakeRequest()
            with web_patches(request):
                request.payload = {"id": source["id"]}
                copied = asyncio.run(holder.duplicate_rule())["rule"]
            self.assertLessEqual(len(copied["name"]), 120)
            self.assertEqual(copied, next(row for row in store.state["rules"] if row["id"] == copied["id"]))

    def test_overview_reports_the_installed_version(self):
        with tempfile.TemporaryDirectory() as directory:
            holder = webui_holder(ReplyStore(directory))
            with web_patches(FakeRequest()):
                self.assertEqual(asyncio.run(holder.overview())["version"], "v9.9.9")


if __name__ == "__main__":
    unittest.main()
