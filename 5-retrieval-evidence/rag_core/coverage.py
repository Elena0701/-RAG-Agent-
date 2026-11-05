"""Absence coverage: can a "No" answer be trusted?

An empty ``evidence_checks`` list proves nothing.  To accept ``No`` the tool must
show that retrieval actually *looked* at every place the topic is mentioned.
The test used here is mechanical and explainable:

1. find every occurrence of the category's anchor terms in the frozen text;
2. check which of them fell inside a chunk that was actually retrieved;
3. if any occurrence was never retrieved, the absence claim is INSUFFICIENT and
   the uncovered positions are returned so the agent knows what to re-query.

This is a heuristic, not a proof: it can only be as good as the anchor list, and
the report says so explicitly.
"""
from __future__ import annotations

import re

__all__ = ["ANCHORS", "absence_coverage"]

# Regex anchors per category.  They are deliberately narrow: generic words like
# "agreement" would make almost every document look covered.
ANCHORS: dict[str, list[str]] = {
    "Insurance": [r"\binsur\w*", r"certificate of insurance", r"policy of insurance"],
    "Audit Rights": [r"\baudit\w*", r"\binspect\w*", r"\bexamin\w*", r"books and records"],
    "Termination For Convenience": [r"without cause", r"for convenience", r"for any reason",
                                    r"\bterminat\w*"],
    "Renewal Term": [r"\brenew\w*"],
    "Notice Period To Terminate Renewal": [r"non-?renew\w*", r"notice of termination",
                                           r"\bterminat\w*", r"\brenew\w*"],
    "Governing Law": [r"\bgovern\w*", r"laws? of", r"\bjurisdiction\b", r"\bvenue\b"],
    "Document Name": [r"\b(?:agreement|contract)\b"],
    "Parties": [r"\b(?:between|among|party|parties)\b"],
    "Agreement Date": [r"\bdated\b", r"date of (?:this|the) agreement", r"\bas of\b"],
    "Effective Date": [r"effective (?:date|as of)", r"\bcommence\w*"],
    "Expiration Date": [r"\bexpir\w*", r"initial term", r"\bterminate on\b"],
}

_DEFAULT_ANCHORS = [r"\b(?:agreement|contract)\b"]


def _occurrences(text: str, patterns: list[str]):
    found = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            found.append((match.start(), match.end(), match.group(0)))
    found.sort()
    return found


def absence_coverage(text: str, category: str, retrieved_spans: list[tuple[int, int]],
                     max_reported: int = 5) -> dict:
    """Decide whether the absence of a clause is adequately covered."""
    patterns = ANCHORS.get(category) or _DEFAULT_ANCHORS
    occurrences = _occurrences(text, patterns)
    if not occurrences:
        return {
            "status": "INSUFFICIENT",
            "reason": (f"全文未出现 {category} 的词法锚定词；这可能是同义表述或词表遗漏，"
                       "不能仅据此确认条款不存在。"),
            "total_occurrences": 0,
            "covered_occurrences": 0,
            "uncovered": [],
            "anchors": patterns,
            "basis": "NO_LEXICAL_ANCHOR",
        }
    uncovered = []
    covered = 0
    for start, end, term in occurrences:
        if any(span_start <= start and end <= span_end for span_start, span_end in retrieved_spans):
            covered += 1
        elif len(uncovered) < max_reported:
            uncovered.append({"term": term, "start": start, "end": end})
    missing = len(occurrences) - covered
    if missing == 0:
        return {
            "status": "SUFFICIENT",
            "reason": f"{category} 的 {len(occurrences)} 处锚定词均已被检索覆盖；这不代表条款不存在。",
            "total_occurrences": len(occurrences),
            "covered_occurrences": covered,
            "uncovered": [],
            "anchors": patterns,
            "basis": "LEXICAL_ANCHOR_COVERAGE",
        }
    return {
        "status": "INSUFFICIENT",
        "reason": (f"{category} 有 {missing} 处锚定词落在已检索片段之外，"
                   f"不能据此判定不存在该条款。"),
        "total_occurrences": len(occurrences),
        "covered_occurrences": covered,
        "uncovered": uncovered[:max_reported],
        "anchors": patterns,
        "basis": "LEXICAL_ANCHOR_COVERAGE",
    }
