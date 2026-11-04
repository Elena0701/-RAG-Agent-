"""Contract-local BM25 and exact citation checks. Python 3.10+, standard library only.

This runtime module never loads CUAD annotations. Offsets are Python Unicode code
points, zero-based half-open intervals; scores are not confidence probabilities.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORD_RE = re.compile(r"\w+", re.UNICODE)
CHUNK_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def terms(text: str) -> list[str]:
    return WORD_RE.findall(text.casefold())


def load_categories(path: Path | None = None) -> dict:
    return json.loads((path or HERE / "categories.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class ChunkConfig:
    max_tokens: int = 350
    overlap_tokens: int = 60
    paragraph_min_fraction: float = 0.65

    def __post_init__(self):
        if type(self.max_tokens) is not int or type(self.overlap_tokens) is not int:
            raise ValueError("Chunk sizes must be integers")
        if not 0 <= self.overlap_tokens < self.max_tokens:
            raise ValueError("Require 0 <= overlap_tokens < max_tokens")
        if not 0 < self.paragraph_min_fraction <= 1:
            raise ValueError("paragraph_min_fraction must be in (0, 1]")


def split_context(context: str, config: ChunkConfig) -> list[dict]:
    """Split by regex words/punctuation, preferring late paragraph boundaries.

    Regex tokens are NOT model tokens. Original characters are never rewritten.
    """
    if not isinstance(context, str) or not context.strip():
        raise ValueError("context must be nonempty text")
    tokens = list(CHUNK_TOKEN_RE.finditer(context))
    ends = [t.end() for t in tokens]
    paragraph_ends = [m.end() for m in re.finditer(r"\n[ \t\r]*\n", context)]
    result, i = [], 0
    while i < len(tokens):
        j = min(i + config.max_tokens, len(tokens))
        if j < len(tokens):
            lower = i + max(config.overlap_tokens + 1,
                            math.ceil(config.max_tokens * config.paragraph_min_fraction))
            if lower <= j:
                a = bisect.bisect_left(paragraph_ends, tokens[lower - 1].end())
                b = bisect.bisect_right(paragraph_ends, tokens[j - 1].end())
                if a < b:
                    cut = bisect.bisect_right(ends, paragraph_ends[b - 1])
                    if cut > i + config.overlap_tokens:
                        j = cut
        start = 0 if i == 0 else tokens[i].start()
        end = len(context) if j == len(tokens) else tokens[j].start()
        result.append({"start": start, "end": end, "text": context[start:end],
                       "regex_token_count": j - i})
        if j == len(tokens):
            break
        i = j - config.overlap_tokens
    return result


class ContractRetriever:
    def __init__(self, config: ChunkConfig | None = None, *, k1=1.5, b=0.75):
        if not math.isfinite(k1) or k1 <= 0 or not math.isfinite(b) or not 0 <= b <= 1:
            raise ValueError("Invalid BM25 parameters")
        self.config = config or ChunkConfig()
        self.k1, self.b = k1, b
        self._contexts: dict[tuple[str, str], str] = {}
        self._chunks: dict[tuple[str, str], list[dict]] = {}
        registry = load_categories()
        self.category_version = registry["version"]
        self.categories = {c["id"]: c for c in registry["categories"]}

    def index_contract(self, contract_id: str, context: str, context_id="0") -> dict:
        if not isinstance(contract_id, str) or not contract_id:
            raise ValueError("contract_id must be a nonempty string")
        if not isinstance(context_id, str) or not context_id:
            raise ValueError("context_id must be a nonempty string")
        key = (contract_id, context_id)
        if key in self._contexts and self._contexts[key] != context:
            raise ValueError("Text changed: use a new retriever/version; do not overwrite an index")
        chunks = split_context(context, self.config)
        version = text_sha256(context)
        for i, chunk in enumerate(chunks):
            chunk.update(contract_id=contract_id, context_id=context_id,
                         context_sha256=version, chunk_id=f"{context_id}:{i:04d}")
        self._contexts[key], self._chunks[key] = context, chunks
        return {"contract_id": contract_id, "context_id": context_id,
                "context_sha256": version, "context_chars": len(context),
                "chunk_count": len(chunks)}

    def retrieve(self, contract_id: str, clause_type: str, top_k=5,
                 *, query: str | None = None) -> dict:
        if clause_type not in self.categories:
            raise ValueError(f"Unknown clause_type: {clause_type}")
        if type(top_k) is not int or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        keys = sorted(k for k in self._chunks if k[0] == contract_id)
        if not keys:
            raise KeyError(f"Contract not indexed: {contract_id}")
        if query is not None and (not isinstance(query, str) or not query.strip()):
            raise ValueError("query must be nonempty text")
        actual_query = self.categories[clause_type]["query"] if query is None else query
        query_terms = set(terms(actual_query))
        # IDF and ranking use only the current contract, never another contract.
        chunks = [c for k in keys for c in self._chunks[k]]
        counts = [Counter(terms(c["text"])) for c in chunks]
        lengths = [sum(c.values()) for c in counts]
        average = sum(lengths) / len(lengths) or 1.0
        df = Counter(t for count in counts for t in count)
        scored = []
        for chunk, count, length in zip(chunks, counts, lengths):
            score = 0.0
            for term in sorted(query_terms):
                frequency = count[term]
                if frequency:
                    idf = math.log(1 + (len(chunks) - df[term] + 0.5) / (df[term] + 0.5))
                    score += idf * frequency * (self.k1 + 1) / (
                        frequency + self.k1 * (1 - self.b + self.b * length / average))
            if score > 0:
                scored.append({**chunk, "score": round(score, 8)})
        scored.sort(key=lambda c: (-c["score"], c["context_id"], c["start"]))
        candidates = [{**c, "rank": i + 1} for i, c in enumerate(scored[:top_k])]
        return {"contract_id": contract_id, "clause_type": clause_type,
                "query": actual_query, "top_k": top_k,
                "status": "candidates_found" if candidates else "no_candidates",
                "clause_presence": "undetermined", "candidates": candidates,
                "note": "Candidates and BM25 scores do not establish clause presence or semantic support."}

    def verify_citation(self, contract_id: str, context_id: str, start: int,
                        end: int, quote: str, context_sha256: str) -> dict:
        """The caller supplies the task's expected contract ID, not a model-selected ID."""
        reasons = []
        context = self._contexts.get((contract_id, context_id))
        if context is None:
            reasons.append("unknown_contract_or_context")
        else:
            if context_sha256 != text_sha256(context):
                reasons.append("text_version_mismatch")
            valid_bounds = (type(start) is int and type(end) is int
                            and 0 <= start < end <= len(context))
            if not valid_bounds:
                reasons.append("invalid_offsets")
            if not isinstance(quote, str) or not quote.strip():
                reasons.append("empty_or_invalid_quote")
            elif valid_bounds and context[start:end] != quote:
                reasons.append("quote_mismatch")
        return {"location_valid": not reasons, "reasons": reasons,
                "semantic_support": "not_evaluated",
                "requires_semantic_review": True}

    def locate_quote(self, contract_id: str, context_id: str, quote: str) -> dict:
        context = self._contexts.get((contract_id, context_id))
        if context is None:
            return {"status": "unknown_contract_or_context", "matches": []}
        if not isinstance(quote, str) or not quote.strip():
            return {"status": "invalid_quote", "matches": []}
        matches, pos = [], 0
        while True:
            start = context.find(quote, pos)
            if start < 0:
                break
            matches.append({"start": start, "end": start + len(quote)})
            pos = start + 1
        status = "located" if len(matches) == 1 else "ambiguous" if matches else "not_found"
        return {"status": status, "matches": matches,
                "context_sha256": text_sha256(context),
                "semantic_support": "not_evaluated"}

    def configuration(self) -> dict:
        return {"method": "contract-local BM25", "chunking": asdict(self.config),
                "chunk_tokenizer": CHUNK_TOKEN_RE.pattern,
                "token_unit": "regex words and punctuation; not model tokens",
                "bm25": {"k1": self.k1, "b": self.b},
                "category_version": self.category_version,
                "categories_sha256": text_sha256(json.dumps(list(self.categories.values()),
                                                            ensure_ascii=False, sort_keys=True)),
                "offset_unit": "Unicode code points, zero-based [start,end)"}
