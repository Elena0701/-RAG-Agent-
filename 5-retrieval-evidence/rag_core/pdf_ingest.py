"""Contract ingestion: PDF (heuristic, stdlib) / TXT / CUAD JSON -> frozen text.

``RAGTool.prepare`` receives a file path.  Everything downstream (offsets, quotes,
page lookups) refers to the *frozen* text produced here, so this module is the
single place that touches raw files.

PDF handling is deliberately honest:

* if ``pypdf`` is installed it is used, page by page;
* otherwise a stdlib fallback scans content streams (FlateDecode + ``Tj``/``TJ``)
  which works for simple text PDFs and fails loudly on font-encoded PDFs;
* if text cannot be recovered, :class:`IngestError` is raised and ``prepare()``
  reports ``status: FAILED`` — the tool never silently indexes an empty document.
"""
from __future__ import annotations

import json
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["IngestError", "IngestResult", "ingest", "normalize_text"]


class IngestError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass
class IngestResult:
    text: str
    method: str
    pages: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"method": self.method, "chars": len(self.text),
                "pages": len(self.pages), "warnings": list(self.warnings)}


_SUPPORTED = {".pdf", ".txt", ".json", ".md"}
_WS = re.compile(r"[ \t\u00a0]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Conservative normalisation applied *before* offsets are frozen."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    text = text.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "").replace("\x00", "")
    text = _WS.sub(" ", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = _MANY_NEWLINES.sub("\n\n", text)
    return text.strip() + "\n"


def ingest(path: str | Path) -> IngestResult:
    path = Path(path)
    if not path.is_file():
        raise IngestError("FILE_NOT_FOUND", f"contract file not found: {path.name}")
    suffix = path.suffix.lower()
    if suffix not in _SUPPORTED:
        raise IngestError("UNSUPPORTED_FILE_TYPE", f"unsupported file type: {suffix or '(none)'}")
    if suffix == ".pdf":
        return _ingest_pdf(path)
    if suffix == ".json":
        return _ingest_json(path)
    return _ingest_text(path)


def _ingest_text(path: Path) -> IngestResult:
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="latin-1")
    text = normalize_text(raw)
    if not text.strip():
        raise IngestError("EMPTY_DOCUMENT", "text file contains no content")
    return IngestResult(text=text, method="text", pages=[{"page": 1, "start": 0, "end": len(text)}])


def _ingest_json(path: Path) -> IngestResult:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise IngestError("INVALID_JSON", "json file could not be parsed") from None
    text = None
    if isinstance(payload, str):
        text = payload
    elif isinstance(payload, dict):
        for key in ("context", "text", "contract_text", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                text = value
                break
        if text is None and isinstance(payload.get("data"), list):
            try:
                text = payload["data"][0]["paragraphs"][0]["context"]
            except (KeyError, IndexError, TypeError):
                text = None
    if not text:
        raise IngestError("INVALID_JSON", "json has no contract text field (context/text)")
    normalized = normalize_text(text)
    return IngestResult(text=normalized, method="json",
                        pages=[{"page": 1, "start": 0, "end": len(normalized)}])


def _ingest_pdf(path: Path) -> IngestResult:
    try:
        import pypdf  # type: ignore
    except ModuleNotFoundError:
        return _stdlib_pdf(path)
    try:
        reader = pypdf.PdfReader(str(path))
        pieces, pages, offset = [], [], 0
        for number, page in enumerate(reader.pages, start=1):
            content = page.extract_text() or ""
            if not content.strip():
                continue
            piece = content + "\n\n"
            pieces.append(piece)
            pages.append({"page": number, "start": offset, "end": offset + len(piece)})
            offset += len(piece)
    except Exception as exc:  # pypdf raises several unrelated types
        raise IngestError("PDF_PARSE_FAILED", f"pypdf could not parse the file ({type(exc).__name__})") from None
    text = normalize_text("".join(pieces))
    if not text.strip():
        raise IngestError("PDF_TEXT_EMPTY", "PDF contains no extractable text (scanned image?)")
    return IngestResult(text=text, method="pypdf", pages=pages)


_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_HEX_RE = re.compile(rb"<([0-9A-Fa-f\s]+)>")
_TEXT_TOKEN_RE = re.compile(
    rb"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>|\[|\]|/[^\s/\[\]()<>]+|-?\d+\.?\d*|[A-Za-z*'\"]+")
_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
            b"(": b"(", b")": b")", b"\\": b"\\"}


def _unescape_pdf_string(raw: bytes) -> bytes:
    out = bytearray()
    index = 0
    while index < len(raw):
        char = raw[index:index + 1]
        if char != b"\\":
            out.extend(char)
            index += 1
            continue
        nxt = raw[index + 1:index + 2]
        if nxt in _ESCAPES:
            out.extend(_ESCAPES[nxt])
            index += 2
        elif nxt.isdigit():
            digits = raw[index + 1:index + 4]
            number = b""
            for byte in digits:
                if not byte.isdigit() or len(number) == 3:
                    break
                number += byte
            out.append(int(number, 8) & 0xFF)
            index += 1 + len(number)
        elif nxt in (b"\n", b"\r"):
            index += 2
        else:
            out.extend(nxt)
            index += 2
    return bytes(out)


def _content_to_text(data: bytes) -> str:
    parts: list[str] = []
    array: list[bytes] | None = None
    for match in _TEXT_TOKEN_RE.finditer(data):
        token = match.group(0)
        if token == b"[":
            array = []
        elif token == b"]":
            array = None
        elif token.startswith(b"(") or token.startswith(b"<"):
            raw = token[1:-1]
            if token.startswith(b"<"):
                try:
                    value = bytes.fromhex(re.sub(rb"\s", b"", raw).decode("ascii"))
                except ValueError:
                    continue
            else:
                value = _unescape_pdf_string(raw)
            if array is not None:
                array.append(value)
            else:
                parts.append(value.decode("latin-1"))
        elif token in (b"TJ", b"Tj"):
            if token == b"TJ" and array is not None:
                parts.append(b"".join(array).decode("latin-1"))
                array = None
        elif token in (b"Td", b"TD", b"T*", b"ET", b"'", b'"'):
            parts.append("\n")
    return "".join(parts)


def _stdlib_pdf(path: Path) -> IngestResult:
    data = path.read_bytes()
    if not data.startswith(b"%PDF"):
        raise IngestError("PDF_PARSE_FAILED", "file does not start with %PDF")
    pieces, decoded_streams = [], 0
    for match in _STREAM_RE.finditer(data):
        block = match.group(1)
        try:
            block = zlib.decompress(block)
            decoded_streams += 1
        except zlib.error:
            pass
        if b"Tj" not in block and b"TJ" not in block:
            continue
        pieces.append(_content_to_text(block))
    text = normalize_text("\n".join(pieces))
    letters = sum(ch.isalpha() for ch in text)
    if len(text) < 80 or letters < len(text) * 0.3:
        raise IngestError(
            "PDF_TEXT_UNUSABLE",
            "stdlib PDF fallback recovered too little text (font-encoded PDF); install pypdf or provide .txt",
        )
    pages = [{"page": 1, "start": 0, "end": len(text)}]
    return IngestResult(
        text=text,
        method="stdlib_pdf",
        pages=pages,
        warnings=["page_mapping_unavailable_single_page",
                  "pdf_text_extraction_is_heuristic"],
    )
