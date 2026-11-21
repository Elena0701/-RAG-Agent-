"""Candidate selection using ranks and optional contract-opening evidence.

No labels or answers are used here. Structural candidates are original indexed
chunks, so their IDs and offsets remain valid for Agent citations.
"""
from __future__ import annotations

import re

POLICIES = ("protected", "rrf", "structured_protected", "structured_rrf")


def select_candidates(dense, sparse, chunks, category, top_k, *, policy="protected",
                      rrf_k=60, dense_weight=1.0, sparse_weight=1.2,
                      admission_threshold=0.75):
    if policy not in POLICIES:
        raise ValueError(f"Unknown ranking policy: {policy}")
    def key(hit):
        return hit["start"], hit["end"], hit.get("parent")
    fused = {}
    for source, weight, hits in (("embedding", dense_weight, dense),
                                 ("bm25", sparse_weight, sparse)):
        for rank, hit in enumerate(hits, 1):
            item = fused.setdefault(key(hit), {
                **hit, "fusion_score": 0.0, "dense_score": None, "bm25_score": None,
                "dense_rank": None, "bm25_rank": None, "retrieval_sources": [],
            })
            item["fusion_score"] += weight / (rrf_k + rank)
            item["dense_rank" if source == "embedding" else "bm25_rank"] = rank
            item["dense_score" if source == "embedding" else "bm25_score"] = hit["score"]
            item["retrieval_sources"].append(source)
    ordered = sorted(fused.values(), key=lambda h: (-h["fusion_score"], h["start"]))
    if policy.endswith("protected"):
        keep = sparse[:top_k]
        keep_keys = {key(h) for h in keep}
        admission = next((h for h in dense if key(h) not in keep_keys
                          and h["score"] >= admission_threshold), None)
        if admission is not None:
            keep = keep[:max(0, top_k - 1)] + [admission]
        keys = {key(h) for h in keep}
        for hit in ordered:
            if len(keys) >= top_k:
                break
            keys.add(key(hit))
        selected = [h for h in ordered if key(h) in keys]
        selected.sort(key=lambda h: (h["bm25_rank"] is None,
                                    h["bm25_rank"] or 10**9, -h["fusion_score"]))
    else:
        selected = ordered

    if policy.startswith("structured_"):
        opening = []
        patterns = {
            "Parties": r"\b(between|among)\b",
            "Agreement Date": r"\b(dated|as of|entered into|made on)\b",
            "Effective Date": r"\beffective\b|\bcommenc\w*",
        }
        for chunk in chunks:
            if chunk["start"] >= 2400:
                break
            matches = (category == "Document Name" and chunk == chunks[0]) or (
                category in patterns and re.search(patterns[category], chunk["text"], re.I))
            if matches:
                item = dict(fused.get(key(chunk)) or {
                    **chunk, "fusion_score": 0.0, "dense_score": None,
                    "bm25_score": None, "dense_rank": None, "bm25_rank": None,
                    "retrieval_sources": [],
                })
                item["retrieval_sources"] = list(item["retrieval_sources"])
                item["retrieval_sources"].append("structure")
                opening.append(item)
                if len(opening) >= min(2, top_k):
                    break
        # Preserve lexical/semantic candidates beyond the existing top-k so
        # near-duplicate overlapping spans can be replaced without shrinking k.
        selected = opening + selected + ordered
    result, used = [], set()
    for hit in selected:
        if key(hit) in used:
            continue
        if policy.startswith("structured_") and any(
            max(0, min(hit["end"], old["end"]) - max(hit["start"], old["start"]))
            / max(1, min(hit["end"] - hit["start"], old["end"] - old["start"])) > 0.85
            for old in result
        ):
            continue
        used.add(key(hit))
        result.append({**hit, "score": round(hit["fusion_score"], 8),
                       "fusion_score": round(hit["fusion_score"], 8)})
        if len(result) == top_k:
            break
    return result
