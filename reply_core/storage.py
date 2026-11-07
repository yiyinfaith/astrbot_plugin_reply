"""Atomic JSON persistence and legacy configuration migration."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from .models import DEFAULT_SETTINGS, default_rule, normalize_rule, utc_now


class ReplyStore:
    """Owns canonical state and performs one-time legacy migration."""

    def __init__(self, data_dir: str | os.PathLike[str]):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "reply_rules.json"
        self.legacy_path = self.data_dir / "keyword_reply_config.json"
        self.migration_path = self.data_dir / "migration.json"
        self._lock = threading.RLock()
        self._pending_migration_marker: dict[str, Any] | None = None
        self.state = self._load()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "schema_version": 2,
            "rules": [],
            "settings": deepcopy(DEFAULT_SETTINGS),
            "usage": {},
            "migrated_legacy": False,
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
            state.setdefault("migrated_legacy", False)
            migrated = self._migrate_if_needed(state)
            if migrated:
                self._atomic_write(self.state_path, state)
                if self._pending_migration_marker is not None:
                    self._atomic_write(self.migration_path, self._pending_migration_marker)
                    self._pending_migration_marker = None
            return state

    def _migrate_if_needed(self, state: dict[str, Any]) -> bool:
        if state.get("migrated_legacy") or not self.legacy_path.is_file():
            return False
        legacy = self._read(self.legacy_path, None)
        if not isinstance(legacy, dict):
            return False
        checksum = hashlib.sha256(self.legacy_path.read_bytes()).hexdigest()
        marker = self._read(self.migration_path, {})
        if isinstance(marker, dict) and marker.get("source_sha256") == checksum:
            state["migrated_legacy"] = True
            return True
        existing_keys = {str(k) for rule in state["rules"] for k in rule.get("keywords", [])}
        migrated_ids: list[str] = []
        for keyword, reply in legacy.items():
            key = str(keyword).strip()
            if not key or key in existing_keys:
                continue
            rule = default_rule(
                name=f"旧规则：{key}",
                keywords=[key],
                match_type="exact",
                case_sensitive=False,
                reply_type="text",
                content=str(reply),
                scope={"mode": "blacklist", "group_ids": [], "user_ids": []},
            )
            state["rules"].append(rule)
            migrated_ids.append(rule["id"])
        state["migrated_legacy"] = True
        state["updated_at"] = utc_now()
        self._pending_migration_marker = {
            "source": str(self.legacy_path.name),
            "source_sha256": checksum,
            "rule_ids": migrated_ids,
            "completed_at": utc_now(),
        }
        return True

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
