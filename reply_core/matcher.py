"""Deterministic keyword matching, scopes and trigger limits."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from .models import normalize_rule

MATCH_RANK = {"exact": 4, "prefix": 3, "contains": 2, "regex": 1}


def normalize_text(
    value: Any,
    *,
    case_sensitive: bool = False,
    unicode_nfkc: bool = True,
    collapse_whitespace: bool = True,
) -> str:
    text = str(value or "").replace("\u200b", "")
    if unicode_nfkc:
        text = unicodedata.normalize("NFKC", text)
    if collapse_whitespace:
        text = " ".join(text.strip().split())
    else:
        text = text.strip()
    return text if case_sensitive else text.casefold()


def _in_scope(rule: dict[str, Any], group_id: str, user_id: str) -> bool:
    scope = rule.get("scope") or {}
    mode = scope.get("mode", "blacklist")
    groups = {str(x) for x in scope.get("group_ids", []) if str(x).strip()}
    users = {str(x) for x in scope.get("user_ids", []) if str(x).strip()}
    matched = (group_id and group_id in groups) or (user_id and user_id in users)
    return not matched if mode == "blacklist" else bool(matched)


def scope_allowed(rule: dict[str, Any], group_id: str = "", user_id: str = "") -> bool:
    """Check a rule's per-rule group/user scope."""
    return _in_scope(normalize_rule(rule), str(group_id or ""), str(user_id or ""))


def match_keyword(
    rule: dict[str, Any],
    message: str,
    *,
    normalization: dict[str, Any] | None = None,
) -> tuple[bool, int, str]:
    rule = normalize_rule(rule)
    normalization = normalization or {}
    unicode_nfkc = bool(normalization.get("unicode_nfkc", True))
    collapse_whitespace = bool(normalization.get("collapse_whitespace", True))
    value = normalize_text(message, case_sensitive=rule["case_sensitive"], unicode_nfkc=unicode_nfkc, collapse_whitespace=collapse_whitespace)
    for keyword in rule["keywords"]:
        candidate = normalize_text(keyword, case_sensitive=rule["case_sensitive"], unicode_nfkc=unicode_nfkc, collapse_whitespace=collapse_whitespace)
        if not candidate:
            continue
        try:
            if rule["match_type"] == "exact" and value == candidate:
                return True, len(candidate), candidate
            if rule["match_type"] == "contains" and candidate in value:
                return True, len(candidate), candidate
            if rule["match_type"] == "prefix" and value.startswith(candidate):
                return True, len(candidate), candidate
            if rule["match_type"] == "regex" and re.search(keyword, message, re.IGNORECASE if not rule["case_sensitive"] else 0):
                return True, len(candidate), candidate
        except (re.error, OverflowError, RecursionError):
            continue
    return False, 0, ""


def _parse_hhmm(value: str) -> time | None:
    if not value:
        return None
    try:
        hour, minute = (int(x) for x in value.split(":", 1))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            return None
        return time(hour, minute)
    except (TypeError, ValueError):
        return None


def allowed_time(rule: dict[str, Any], now: datetime | None = None) -> bool:
    time_range = rule.get("time_range") or {}
    raw_start = str(time_range.get("start") or "").strip()
    raw_end = str(time_range.get("end") or "").strip()
    if not raw_start and not raw_end:
        return True
    # A partially configured or malformed window must fail closed. Otherwise a
    # corrupted state file could silently turn a restricted reply into an
    # unrestricted one.
    if not raw_start or not raw_end:
        return False
    start = _parse_hhmm(raw_start)
    end = _parse_hhmm(raw_end)
    if start is None or end is None:
        return False
    current = (now or datetime.now().astimezone()).time().replace(second=0, microsecond=0)
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


@dataclass(frozen=True)
class Candidate:
    rule: dict[str, Any]
    match_length: int
    keyword: str


def matching_candidates(
    rules: list[dict[str, Any]],
    message: str,
    *,
    group_id: str = "",
    user_id: str = "",
    now: datetime | None = None,
    normalization: dict[str, Any] | None = None,
) -> list[Candidate]:
    result: list[Candidate] = []
    for raw in rules:
        rule = normalize_rule(raw)
        if not rule["enabled"] or not _in_scope(rule, group_id, user_id) or not allowed_time(rule, now):
            continue
        matched, length, keyword = match_keyword(rule, message, normalization=normalization)
        if matched:
            result.append(Candidate(rule, length, keyword))
    result.sort(
        key=lambda candidate: (
            -int(candidate.rule.get("priority", 0)),
            -MATCH_RANK.get(candidate.rule.get("match_type", "exact"), 0),
            -candidate.match_length,
            str(candidate.rule.get("id", "")),
        )
    )
    return result
