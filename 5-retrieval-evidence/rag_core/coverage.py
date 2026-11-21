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
    "Most Favored Nation": [r"\bmost[- ]favou?red\b", r"\b(?:more|no less) favou?rable\b", r"\bmfn\b"],
    "Non-Compete": [r"\bcompet(?:e|es|ing|ition|itive|itors?)\b", r"\bnon[- ]?compet\w*"],
    "Exclusivity": [r"\bexclusiv\w*", r"\bsole (?:source|supplier|distributor)\b", r"\ball (?:of )?(?:its |its own )?requirements\b"],
    "No-Solicit Of Customers": [r"\bsolicit\w*", r"\bdivert\w*", r"\bpoach\w*"],
    "Competitive Restriction Exception": [r"\bexcept\w*", r"\bnotwithstanding\b", r"\bshall not (?:apply|prevent|restrict)\b", r"\bnothing (?:herein|in this)\b"],
    "No-Solicit Of Employees": [r"\bsolicit\w*", r"\brecruit\w*", r"\bhir(?:e|es|ed|ing)\b", r"\bentic\w*"],
    "Non-Disparagement": [r"\bdisparag\w*", r"\bderogat\w*", r"\bdefam\w*"],
    "Rofr/Rofo/Rofn": [r"\bfirst (?:refusal|offer|negotiation)\b", r"\brof[ron]\b", r"\bmatching right\b"],
    "Change Of Control": [r"\bchange (?:of|in) control\b", r"\bmerg(?:e|er)\w*", r"\bsubstantially all\b", r"\bcontrolling interest\b"],
    "Anti-Assignment": [r"\bassign(?:ment|ments|ed|s)?\b", r"\boperation of law\b"],
    "Revenue/Profit Sharing": [r"\brevenues?\b", r"\bprofits?\b", r"\broyalt(?:y|ies)\b", r"\bnet (?:sales|receipts)\b"],
    "Price Restrictions": [r"\bpric(?:e|es|ing)\b", r"\brate (?:adjustment|increase)\b", r"\bfee increase\b"],
    "Minimum Commitment": [r"\bminimum\b", r"\btake[- ]or[- ]pay\b", r"\bpurchase commitment\b", r"\bat least\b"],
    "Volume Restriction": [r"\b(?:usage|volume) (?:limit|threshold|cap)\w*", r"\boverage\w*", r"\bexceed\w*", r"\bmaximum\b"],
    "Ip Ownership Assignment": [r"\bassign\w*", r"\bvest\w*", r"\bwork(?:s)? (?:made )?for hire\b", r"\bwork product\b"],
    "Joint Ip Ownership": [r"\bjoint(?:ly)?\b", r"\bco[- ]?own\w*", r"\bshared ownership\b", r"\bundivided interest\b"],
    "License Grant": [r"\blicen[cs]\w*", r"\bright to use\b", r"\bhereby grants?\b"],
    "Non-Transferable License": [r"\bnon[- ]?(?:transferable|assignable)\b", r"\bmay not (?:be )?(?:transfer|assign)\w*", r"\bpersonal licen[cs]e\b"],
    "Affiliate License-Licensor": [r"\baffiliat\w*", r"\bsubsidiar\w*"],
    "Affiliate License-Licensee": [r"\baffiliat\w*", r"\bsubsidiar\w*"],
    "Unlimited/All-You-Can-Eat-License": [r"\bunlimited\b", r"\benterprise[- ]wide\b", r"\ball[- ]you[- ]can[- ]eat\b", r"\bunrestricted (?:use|usage)\b"],
    "Irrevocable Or Perpetual License": [r"\birrevocab\w*", r"\bperpetu\w*", r"\bnon[- ]?revocable\b"],
    "Source Code Escrow": [r"\bescrow\w*", r"\bsource[- ]code\b", r"\brelease condition\w*"],
    "Post-Termination Services": [r"\b(?:upon|after|following) (?:the )?(?:termination|expiration)\b", r"\bpost[- ]termination\b", r"\btransition\w*", r"\bwind[- ]down\b", r"\blast[- ]buy\b"],
    "Uncapped Liability": [r"\buncapped\b", r"\bunlimited liability\b", r"\bwithout limit\w*", r"\bliability\b", r"\blimitation\w*"],
    "Cap On Liability": [r"\bliabilit(?:y|ies)\b", r"\bnot (?:exceed|exceeding)\b", r"\baggregate damages\b", r"\bclaim\w*"],
    "Liquidated Damages": [r"\bliquidated damages\b", r"\btermination (?:fee|charge)\b", r"\bearly termination\b"],
    "Warranty Duration": [r"\bwarrant(?:y|ies|s|ed)\b", r"\bdefects?\b"],
    "Covenant Not To Sue": [r"\bnot to sue\b", r"\b(?:not |never )(?:to )?(?:assert|challenge|contest)\b", r"\bnon[- ]assert\w*"],
    "Third Party Beneficiary": [r"\bbeneficiar\w*", r"\bthird[- ]part(?:y|ies)\b", r"\bnon[- ]part(?:y|ies)\b"],
}


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
    patterns = ANCHORS.get(category, [])
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
