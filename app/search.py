"""Small, reusable fuzzy-search primitives for desktop interfaces.

The module deliberately has no Qt dependency.  Interfaces provide their own
objects and a text extractor, while tests can exercise ranking deterministically.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TypeVar


T = TypeVar("T")
_SEPARATOR = re.compile(r"[^\w\u3400-\u9fff]+", re.UNICODE)


@dataclass(frozen=True)
class SearchText:
    spaced: str
    compact: str


def normalize_search_text(value: object) -> SearchText:
    """Normalize case, width, punctuation and whitespace without losing CJK."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    spaced = " ".join(part for part in _SEPARATOR.split(normalized) if part)
    return SearchText(spaced=spaced, compact=spaced.replace(" ", ""))


def _subsequence_gap(needle: str, haystack: str) -> int | None:
    """Return total skipped characters for an ordered subsequence match."""

    if not needle:
        return 0
    position = -1
    gaps = 0
    for character in needle:
        next_position = haystack.find(character, position + 1)
        if next_position < 0:
            return None
        if position >= 0:
            gaps += next_position - position - 1
        position = next_position
    return gaps


def fuzzy_score(query: object, values: Iterable[object]) -> int | None:
    """Score a query against several fields; ``None`` means no useful match.

    Every normalized query token must match.  Exact phrases and compact
    substrings outrank ordered subsequences, so results remain predictable for
    Chinese names while still tolerating omitted separators and a few gaps.
    """

    normalized_query = normalize_search_text(query)
    if not normalized_query.compact:
        return 0

    fields = [normalize_search_text(value) for value in values]
    fields = [field for field in fields if field.compact]
    if not fields:
        return None
    combined_spaced = " ".join(field.spaced for field in fields)
    combined_compact = "".join(field.compact for field in fields)
    tokens = normalized_query.spaced.split() or [normalized_query.compact]

    total = 0
    for token in tokens:
        compact_token = token.replace(" ", "")
        if token == combined_spaced:
            token_score = 1500
        elif combined_spaced.startswith(token):
            token_score = 1350 - min(len(combined_spaced) - len(token), 120)
        elif token in combined_spaced:
            token_score = 1200 - min(combined_spaced.index(token), 180)
        elif compact_token in combined_compact:
            token_score = 1000 - min(combined_compact.index(compact_token), 180)
        else:
            gap = _subsequence_gap(compact_token, combined_compact)
            # Very sparse matches are noise rather than fuzziness.
            if gap is None or gap > max(8, len(compact_token) * 3):
                return None
            token_score = 720 - gap * 18
        total += token_score + min(len(compact_token), 40)

    if normalized_query.compact in combined_compact:
        total += 240
    return total


def rank_items(
    items: Sequence[T] | Iterable[T],
    query: object,
    text_getter: Callable[[T], Iterable[object]],
    *,
    limit: int | None = None,
) -> list[T]:
    """Return matching items by descending score with stable input-order ties."""

    scored: list[tuple[int, int, T]] = []
    for index, item in enumerate(items):
        score = fuzzy_score(query, text_getter(item))
        if score is not None:
            scored.append((-score, index, item))
    scored.sort(key=lambda row: (row[0], row[1]))
    ranked = [row[2] for row in scored]
    if limit is not None:
        return ranked[:max(0, limit)]
    return ranked
