"""Atomic JSON persistence for reply rules."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from .models import DEFAULT_SETTINGS, normalize_rule, utc_now


class ReplyStore:
    """Owns the canonical reply state file."""

    def __init__(self, data_dir: str | os.PathLike[str]):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "reply_rules.json"
        self._lock = threading.RLock()
        self.state = self._load()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "schema_version": 2,
            "rules": [],
            "settings": deepcopy(DEFAULT_SETTINGS),
            "usage": {},
            "updated_at": utc_now(),
        }

    @staticmethod
    def _read(path: Path, fallback: Any) -> Any:
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                return json.load(handle)
        except (OSError, ValueError, TypeError):
            return fallback

    def _load(self) -> dict[str, Any]:
        with self._lock:
            state = self._read(self.state_path, self._empty_state())
            if not isinstance(state, dict):
                state = self._empty_state()
            state.setdefault("schema_version", 2)
            state["rules"] = [normalize_rule(item) for item in state.get("rules", []) if isinstance(item, dict)]
            settings = state.get("settings") if isinstance(state.get("settings"), dict) else {}
            state["settings"] = {**deepcopy(DEFAULT_SETTINGS), **settings}
            state.setdefault("usage", {})
            return state

    @staticmethod
    def _atomic_write(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def save(self) -> None:
        with self._lock:
            self.state["updated_at"] = utc_now()
            self._atomic_write(self.state_path, self.state)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self.state)

    def replace_rules(self, rules: list[dict[str, Any]]) -> None:
        with self._lock:
            self.state["rules"] = [normalize_rule(rule) for rule in rules]
            self.save()

    def upsert_rule(self, rule: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            normalized = normalize_rule(rule)
            normalized["updated_at"] = utc_now()
            rows = self.state["rules"]
            for index, existing in enumerate(rows):
                if existing.get("id") == normalized["id"]:
                    normalized["created_at"] = existing.get("created_at", normalized["created_at"])
                    rows[index] = normalized
                    break
            else:
                rows.append(normalized)
            self.save()
            return deepcopy(normalized)

    def delete_rule(self, rule_id: str) -> bool:
        with self._lock:
            before = len(self.state["rules"])
            self.state["rules"] = [row for row in self.state["rules"] if row.get("id") != rule_id]
            if len(self.state["rules"]) == before:
                return False
            self.save()
            return True

    def update_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            merged = {**deepcopy(DEFAULT_SETTINGS), **settings}
            merged["scope_mode"] = "whitelist" if merged.get("scope_mode") == "whitelist" else "blacklist"
            merged["group_ids"] = [str(x).strip() for x in merged.get("group_ids", []) if str(x).strip()]
            merged["user_ids"] = [str(x).strip() for x in merged.get("user_ids", []) if str(x).strip()]
            merged["webui_admins"] = [str(x).strip() for x in merged.get("webui_admins", []) if str(x).strip()]
            self.state["settings"] = merged
            self.save()
            return deepcopy(merged)
