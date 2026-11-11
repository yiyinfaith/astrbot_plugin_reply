"""Deterministic keyword matching, scopes and trigger limits."""

from __future__ import annotations

import re
import time as clock
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time
from functools import lru_cache
from typing import Any

import regex
from astrbot.api import logger

from .models import normalize_rule

MATCH_RANK = {"exact": 4, "prefix": 3, "contains": 2, "regex": 1}

# The match loop runs on the event loop, so one search may only hold it briefly.
REGEX_TIMEOUT_SECONDS = 0.05
# A pattern that timed out is skipped for a while, so it cannot slow every later message.
REGEX_SUSPEND_SECONDS = 60.0
# Counted repeats are expanded while compiling and the timeout does not cover that step.
REGEX_MAX_EXPANSION = 200_000

_COUNTED_REPEAT = re.compile(r"\{\s*(\d*)\s*(?:,\s*(\d*)\s*)?\}")
_suspended_until: dict[tuple[str, int], float] = {}


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


def _class_end(pattern: str, start: int) -> int:
    """Return the index just past the character class opening at ``start``."""
    index = start + 1
    if pattern[index:index + 1] == "^":
        index += 1
    if pattern[index:index + 1] == "]":
        index += 1
    while index < len(pattern) and pattern[index] != "]":
        index += 2 if pattern[index] == "\\" else 1
    return index + 1


def _expansion_cost(pattern: str) -> int:
    """Estimate the number of nodes a pattern needs once counted repeats are expanded."""
    totals = [0]
    last = 0
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "(":
            totals.append(0)
            last = 0
            index += 1
        elif char == ")":
            last = totals.pop() if len(totals) > 1 else 0
            totals[-1] += last
            index += 1
        elif char == "{" and (repeat := _COUNTED_REPEAT.match(pattern, index)):
            count = max(1, *(int(bound) for bound in repeat.groups(default="") if bound))
            totals[-1] += last * (count - 1)
            last *= count
            index = repeat.end()
        else:
            if char == "\\":
                index += 2
            elif char == "[":
                index = _class_end(pattern, index)
            else:
                index += 1
            last = 1
            totals[-1] += 1
    return sum(totals)


@lru_cache(maxsize=2048)
def _compile_regex(keyword: str, flags: int) -> tuple[Any, str]:
    if _expansion_cost(keyword) > REGEX_MAX_EXPANSION:
        return None, "重复次数过大，请减小 {n} 中的数值"
    try:
        return regex.compile(keyword, flags), ""
    except (regex.error, IndexError, MemoryError, OverflowError, RecursionError, ValueError) as exc:
        return None, str(exc) or type(exc).__name__


def regex_error(keyword: str) -> str:
    """Return why a pattern cannot be used, or an empty string when it is valid."""
    return _compile_regex(keyword, 0)[1]


def _regex_search(keyword: str, message: str, flags: int) -> bool:
    key = (keyword, flags)
    if clock.monotonic() < _suspended_until.get(key, 0.0):
        return False
    _suspended_until.pop(key, None)
    pattern = _compile_regex(keyword, flags)[0]
    if pattern is None:
        return False
    try:
        return pattern.search(message, timeout=REGEX_TIMEOUT_SECONDS) is not None
    except TimeoutError:
        _suspended_until[key] = clock.monotonic() + REGEX_SUSPEND_SECONDS
        logger.warning(
            "正则 %r 匹配超过 %d 毫秒，已暂停 %d 秒，请简化这条正则",
            keyword[:200],
            REGEX_TIMEOUT_SECONDS * 1000,
            REGEX_SUSPEND_SECONDS,
        )
        return False
    except (MemoryError, OverflowError, RecursionError):
        return False


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
        if rule["match_type"] == "exact" and value == candidate:
            return True, len(candidate), candidate
        if rule["match_type"] == "contains" and candidate in value:
            return True, len(candidate), candidate
        if rule["match_type"] == "prefix" and value.startswith(candidate):
            return True, len(candidate), candidate
        if rule["match_type"] == "regex" and _regex_search(keyword, message, regex.IGNORECASE if not rule["case_sensitive"] else 0):
            return True, len(candidate), candidate
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
