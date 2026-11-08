"""Atomic JSON persistence for reply rules."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from .models import DEFAULT_SETTINGS, normalize_folder, normalize_rule, utc_now


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
            "folders": [],
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
            state["folders"] = [normalize_folder(item) for item in state.get("folders", []) if isinstance(item, dict)]
            folder_ids = {folder["id"] for folder in state["folders"]}
            state["rules"] = [normalize_rule(item) for item in state.get("rules", []) if isinstance(item, dict)]
            for rule in state["rules"]:
                if rule.get("folder_id") not in folder_ids:
                    rule["folder_id"] = ""
            settings = state.get("settings") if isinstance(state.get("settings"), dict) else {}
            state["settings"] = self._normalize_settings(settings)
            state["usage"] = state.get("usage") if isinstance(state.get("usage"), dict) else {}
            return state

    @staticmethod
    def _normalize_settings(settings: dict[str, Any]) -> dict[str, Any]:
        merged = {**deepcopy(DEFAULT_SETTINGS), **settings}
        wake = merged.get("require_wake", True)
        merged["require_wake"] = (
            wake if isinstance(wake, bool) else str(wake).strip().casefold() not in {"", "0", "false", "no", "off"}
        )
        merged["scope_mode"] = "whitelist" if merged.get("scope_mode") == "whitelist" else "blacklist"
        for key in ("group_ids", "user_ids", "webui_admins"):
            value = merged.get(key, [])
            if isinstance(value, str):
                value = value.replace("\r\n", "\n").replace(",", "\n").split("\n")
            if not isinstance(value, (list, tuple)):
                value = []
            merged[key] = list(dict.fromkeys(str(x).strip() for x in value if str(x).strip()))
        normalization = merged.get("normalization")
        merged["normalization"] = {
            **deepcopy(DEFAULT_SETTINGS["normalization"]),
            **normalization,
        } if isinstance(normalization, dict) else deepcopy(DEFAULT_SETTINGS["normalization"])
        for key in ("unicode_nfkc", "collapse_whitespace"):
            value = merged["normalization"].get(key, True)
            merged["normalization"][key] = value if isinstance(value, bool) else str(value).strip().casefold() not in {"", "0", "false", "no", "off"}
        return merged

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

    @contextmanager
    def locked(self):
        """Hold the store lock for a compound read/modify/write operation."""
        with self._lock:
            yield self.state

    def replace_rules(self, rules: list[dict[str, Any]], folders: list[dict[str, Any]] | None = None) -> None:
        self.replace_state(rules, folders=folders, reset_usage=True)

    def replace_state(
        self,
        rules: list[dict[str, Any]],
        *,
        folders: list[dict[str, Any]] | None = None,
        settings: dict[str, Any] | None = None,
        reset_usage: bool = False,
    ) -> None:
        """Atomically replace imported state after all records are validated."""
        with self._lock:
            if folders is not None:
                self.state["folders"] = [normalize_folder(folder) for folder in folders]
            folder_ids = {folder["id"] for folder in self.state.get("folders", [])}
            self.state["rules"] = [normalize_rule(rule) for rule in rules]
            for rule in self.state["rules"]:
                if rule.get("folder_id") not in folder_ids:
                    rule["folder_id"] = ""
            if settings is not None:
                current_settings = cast(dict[str, Any], self.state.get("settings")) if isinstance(self.state.get("settings"), dict) else {}
                self.state["settings"] = self._normalize_settings({**current_settings, **settings})
            if reset_usage:
                self.state["usage"] = {}
            self.save()

    def upsert_rule(self, rule: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            normalized = normalize_rule(rule)
            if normalized.get("folder_id") and normalized["folder_id"] not in {folder["id"] for folder in self.state.get("folders", [])}:
                raise ValueError("文件夹不存在")
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
            self.state.setdefault("usage", {}).pop(rule_id, None)
            self.save()
            return True

    def list_folders(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self.state.get("folders", []))

    def upsert_folder(self, folder: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if not str(folder.get("name") or "").strip():
                raise ValueError("文件夹名称不能为空")
            normalized = normalize_folder(folder)
            rows = self.state.setdefault("folders", [])
            for index, existing in enumerate(rows):
                if existing.get("id") == normalized["id"]:
                    normalized["created_at"] = existing.get("created_at", normalized["created_at"])
                    rows[index] = normalized
                    break
            else:
                rows.append(normalized)
            self.save()
            return deepcopy(normalized)

    def delete_folder(self, folder_id: str) -> bool:
        with self._lock:
            folder_id = str(folder_id or "").strip()
            before = len(self.state.get("folders", []))
            self.state["folders"] = [folder for folder in self.state.get("folders", []) if folder.get("id") != folder_id]
            if len(self.state["folders"]) == before:
                return False
            for rule in self.state.get("rules", []):
                if rule.get("folder_id") == folder_id:
                    rule["folder_id"] = ""
                    rule["updated_at"] = utc_now()
            self.save()
            return True

    def set_rule_folder(self, rule_id: str, folder_id: str = "") -> dict[str, Any] | None:
        with self._lock:
            rule_id = str(rule_id or "").strip()
            folder_id = str(folder_id or "").strip()
            if folder_id and folder_id not in {folder["id"] for folder in self.state.get("folders", [])}:
                raise ValueError("文件夹不存在")
            for rule in self.state.get("rules", []):
                if rule.get("id") == rule_id:
                    rule["folder_id"] = folder_id
                    rule["updated_at"] = utc_now()
                    self.save()
                    return deepcopy(rule)
            return None

    def update_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = cast(dict[str, Any], self.state.get("settings")) if isinstance(self.state.get("settings"), dict) else {}
            merged = self._normalize_settings({**current, **settings})
            self.state["settings"] = merged
            self.save()
            return deepcopy(merged)
