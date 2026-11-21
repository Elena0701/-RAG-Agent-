"""Character-based chunking and in-contract BM25 for RAGTool.

The agent-facing config uses characters (``chunk_size=800``, ``chunk_overlap=120``)
because the frozen text is a character string and every offset must refer to it.
Chunks are packed at paragraph/sentence boundaries when possible, otherwise at a
word boundary, and always keep absolute offsets into the frozen context.
"""
from __future__ import annotations

import bisect
import math
import re
from collections import Counter

from .retrieval import terms

__all__ = ["ChunkConfig", "split_context", "split_by_clause", "split_units", "BM25Index", "covered_chars"]

# 条款标题的常见写法：法律文本自带结构，按标题切比按字符切更贴合语义。
_CLAUSE_HEADING = re.compile(
    r"^[ \t]*(?:"
    r"(?:ARTICLE|Article|SECTION|Section)\s+[0-9IVXLC]+(?:\.[0-9]+)*"
    r"|\d+(?:\.\d+)*\.?\s+[A-Z(]"
    r"|第[一二三四五六七八九十百]+条"
    r")",
    re.MULTILINE,
)

_PARAGRAPH_RE = re.compile(r"\n[ \t\r]*\n")
_SENTENCE_RE = re.compile(r"(?<=[.;!?])\s+|(?<=[。；！？])")


class ChunkConfig:
    """Chunk sizing in characters, validated once."""

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 120, min_paragraph_fraction: float = 0.6):
        if type(chunk_size) is not int or chunk_size < 100:
            raise ValueError("chunk_size must be an integer >= 100 characters")
        if type(chunk_overlap) is not int or not 0 <= chunk_overlap < chunk_size:
            raise ValueError("chunk_overlap must be an integer in [0, chunk_size)")
        if not 0 < min_paragraph_fraction <= 1:
            raise ValueError("min_paragraph_fraction must be in (0, 1]")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_paragraph_fraction = min_paragraph_fraction

    def as_dict(self) -> dict:
        return {"chunk_size": self.chunk_size, "chunk_overlap": self.chunk_overlap,
                "min_paragraph_fraction": self.min_paragraph_fraction,
                "unit": "characters (Unicode code points)"}


def _split_points(text: str) -> list[tuple[int, int]]:
    """Return break positions with a priority: paragraph (0) > sentence (1) > space (2)."""
    points = []
    for match in _PARAGRAPH_RE.finditer(text):
        points.append((match.end(), 0))
    for match in _SENTENCE_RE.finditer(text):
        points.append((match.end(), 1))
    for match in re.finditer(r"\s", text):
        points.append((match.end(), 2))
    points.sort()
    return points


def split_context(text: str, config: ChunkConfig) -> list[dict]:
    """Split ``text`` into overlapping chunks that keep absolute offsets."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("context must be nonempty text")
    points = _split_points(text)
    positions = [p for p, _ in points]
    priority = {p: pr for p, pr in reversed(points)} if points else {}

    chunks = []
    start = 0
    length = len(text)
    while start < length:
        target = min(start + config.chunk_size, length)
        end = target
        if target < length:
            lower = start + int(config.chunk_size * config.min_paragraph_fraction)
            cut = None
            # prefer a paragraph or sentence break inside [lower, target]
            index = bisect.bisect_left(positions, lower)
            while index < len(positions) and positions[index] <= target:
                candidate = positions[index]
                if priority.get(candidate, 2) <= 1 and candidate > start + config.chunk_overlap:
                    cut = candidate
                    break
                index += 1
            if cut is None:
                index = bisect.bisect_left(positions, target)
                while index > 0 and positions[index - 1] > start + config.chunk_overlap:
                    index -= 1
                    if priority.get(positions[index], 2) == 2:
                        cut = positions[index]
                        break
            if cut is not None:
                end = cut
        chunk_text = text[start:end]
        chunks.append({"start": start, "end": end, "text": chunk_text})
        if end >= length:
            break
        next_start = end - config.chunk_overlap
        # never move backwards into a previous chunk's territory
        start = max(next_start, start + 1)
    return chunks


def split_by_clause(text: str, config: ChunkConfig, min_segment: int = 180) -> list[dict]:
    """按条款标题切块；标题太少时退回字符切块。

    每块 = 一条（或合并后的若干条）完整条款，偏移仍是全文绝对位置。
    过长的条款再用 :func:`split_context` 在内部切分，避免单块过大稀释 BM25。
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("context must be nonempty text")
    headings = [match.start() for match in _CLAUSE_HEADING.finditer(text)]
    if len(headings) < 3:
        return split_context(text, config)

    starts = [0] + headings
    starts = sorted(set(starts))
    boundaries = [(start, starts[i + 1] if i + 1 < len(starts) else len(text))
                  for i, start in enumerate(starts)]

    # 把过短的段（标题下的半句话）并入前一段，避免产生噪声块
    merged: list[list[int]] = []
    for start, end in boundaries:
        if merged and (end - start) < min_segment:
            merged[-1][1] = end
        else:
            merged.append([start, end])

    chunks: list[dict] = []
    for start, end in merged:
        if end - start <= config.chunk_size:
            chunks.append({"start": start, "end": end, "text": text[start:end]})
            continue
        for piece in split_context(text[start:end], config):
            chunks.append({
                "start": start + piece["start"],
                "end": start + piece["end"],
                "text": piece["text"],
            })
    return chunks


_UNIT_BREAK = re.compile(r"(?<=[.;!?])\s+|\n+")


def split_units(chunks: list[dict], max_unit: int = 320) -> list[dict]:
    """把每个条款块再切成检索用的"小单元"（句子级，<= max_unit 字符）。

    返回的单元带 ``parent`` 指向所属条款块，检索命中后回到父块返回，
    这样"搜得准"和"读得全"兼顾。
    """
    if type(max_unit) is not int or max_unit <= 0:
        raise ValueError("max_unit must be a positive integer")
    units: list[dict] = []

    def append_range(chunk: dict, parent: int, text: str, start: int, end: int) -> None:
        # Legal drafting sometimes contains a single sentence far above the
        # target size.  Hard-slice that exceptional range so max_unit remains
        # a real bound rather than a best-effort hint.
        cursor = start
        while cursor < end:
            piece_end = min(cursor + max_unit, end)
            units.append({"start": chunk["start"] + cursor,
                          "end": chunk["start"] + piece_end,
                          "text": text[cursor:piece_end], "parent": parent})
            cursor = piece_end

    for parent, chunk in enumerate(chunks):
        text = chunk["text"]
        cuts = [0] + [m.end() for m in _UNIT_BREAK.finditer(text)] + [len(text)]
        cuts = sorted(set(cuts))
        start = cuts[0]
        previous = cuts[0]
        for boundary in cuts[1:]:
            if boundary - start > max_unit and previous > start:
                append_range(chunk, parent, text, start, previous)
                start = previous
            previous = boundary
        if previous > start:
            append_range(chunk, parent, text, start, previous)
    return [unit for unit in units if unit["text"].strip()]


def covered_chars(start: int, end: int, intervals) -> int:
    """Union length of intersections (overlaps counted once)."""
    clipped = sorted((max(start, a), min(end, b)) for a, b in intervals if max(start, a) < min(end, b))
    total, right = 0, start
    for a, b in clipped:
        total += max(0, b - max(a, right))
        right = max(right, b)
    return total


class BM25Index:
    """BM25 over the chunks of one contract; IDF stays contract-local."""

    def __init__(self, chunks: list[dict], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self._counts = [Counter(terms(c["text"])) for c in chunks]
        self._lengths = [sum(count.values()) for count in self._counts]
        self._average = (sum(self._lengths) / len(self._lengths)) if self._lengths else 1.0
        self._df = Counter(term for count in self._counts for term in count)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        query_terms = set(terms(query))
        if not query_terms or not self.chunks:
            return []
        scored = []
        n = len(self.chunks)
        for chunk, count, length in zip(self.chunks, self._counts, self._lengths):
            score = 0.0
            for term in query_terms:
                frequency = count.get(term, 0)
                if not frequency:
                    continue
                idf = math.log(1 + (n - self._df[term] + 0.5) / (self._df[term] + 0.5))
                score += idf * frequency * (self.k1 + 1) / (
                    frequency + self.k1 * (1 - self.b + self.b * length / (self._average or 1)))
            if score > 0:
                scored.append({"score": round(score, 8), **chunk})
        scored.sort(key=lambda item: (-item["score"], item["start"]))
        return scored[:top_k]
