"""RAGTool 的接口契约与行为测试（对应 4 号《工程架构与工具接口_修订版》）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.rag_tool import RAGTool  # noqa: E402
from rag_core.deepseek_client import DEFAULT_ENV_FILE  # noqa: E402

CONTRACT = (
    "SOFTWARE SUBSCRIPTION AGREEMENT\n\n"
    "1. Parties. This Agreement is entered into between Acme Software Inc. and Beta Retail LLC.\n\n"
    "2. Term and Renewal. The initial term is twelve (12) months and shall automatically renew "
    "for successive one (1) year periods unless either party gives written notice of non-renewal "
    "at least ninety (90) days prior to the end of the then-current term.\n\n"
    "3. Termination for Convenience. Customer may terminate this Agreement for any reason upon "
    "thirty (30) days prior written notice.\n\n"
    "4. Governing Law. This Agreement is governed by the laws of the State of California.\n\n"
    "5. Fees. Customer shall pay the fees set out in Exhibit A within thirty (30) days of invoice.\n"
)


class ModelConfigurationTest(unittest.TestCase):
    def test_default_env_file_is_project_root(self):
        self.assertEqual(DEFAULT_ENV_FILE, ROOT / "deepseek.local.env")


def model_supported(messages):
    payload = json.loads(messages[-1]["content"])
    checks = [
        {"answer_index": i, "support_status": "SUPPORTED", "reason": "引用与答案一致。"}
        for i, _ in enumerate(payload["quotes"])
    ]
    return {"evidence_checks": checks,
            "overall_support": {"status": "SUPPORTED", "reason": "证据支持答案。",
                                "evidence_indices": list(range(len(checks)))}}


def model_error(messages):
    raise RuntimeError("simulated provider failure")


def write_contract(directory: Path, name: str = "contract.txt", text: str = CONTRACT) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def make_pdf(directory: Path, text: str = CONTRACT) -> Path:
    """Minimal single-page PDF with an uncompressed content stream."""
    lines = [line for line in text.splitlines() if line.strip()]
    body = ["BT", "/F1 10 Tf", "72 760 Td"]
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        body.append(f"({escaped}) Tj")
        body.append("0 -14 Td")
    body.append("ET")
    stream = "\n".join(body).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + payload + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n").encode()
    path = directory / "contract.pdf"
    path.write_bytes(bytes(out))
    return path


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_prepare_text_file(self):
        tool = RAGTool({"chunk_size": 400, "chunk_overlap": 60})
        result = tool.prepare("DOC-1", str(write_contract(self.dir)))
        self.assertEqual(result["status"], "SUCCESS")
        self.assertGreater(result["chunk_count"], 1)
        self.assertEqual(len(result["context_sha256"]), 64)
        self.assertEqual(tool.context("DOC-1"), CONTRACT.strip() + "\n")

    def test_prepare_json_with_context_field(self):
        path = self.dir / "c.json"
        path.write_text(json.dumps({"context": CONTRACT}), encoding="utf-8")
        result = RAGTool().prepare("DOC-J", str(path))
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["method"], "json")

    def test_missing_file_fails_softly(self):
        result = RAGTool().prepare("DOC-X", str(self.dir / "nope.txt"))
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["error_code"], "FILE_NOT_FOUND")

    def test_unsupported_extension(self):
        path = self.dir / "c.docx"
        path.write_bytes(b"PK")
        result = RAGTool().prepare("DOC-X", str(path))
        self.assertEqual(result["error_code"], "UNSUPPORTED_FILE_TYPE")

    def test_pdf_prepare(self):
        tool = RAGTool({"chunk_size": 400, "chunk_overlap": 60})
        result = tool.prepare("DOC-PDF", str(make_pdf(self.dir)))
        self.assertEqual(result["status"], "SUCCESS", msg=result.get("reason"))
        self.assertIn("Governing Law", tool.context("DOC-PDF"))

    def test_prepare_is_idempotent(self):
        tool = RAGTool()
        path = write_contract(self.dir)
        first = tool.prepare("DOC-1", str(path))
        second = tool.prepare("DOC-1", str(path))
        self.assertEqual(first["context_sha256"], second["context_sha256"])

    def test_stale_reference_after_reparse_is_rejected(self):
        tool = RAGTool()
        path = write_contract(self.dir)
        tool.prepare("DOC-1", str(path))
        old = tool.context("DOC-1")
        write_contract(self.dir, text=CONTRACT + "\n6. Amendment. All terms may change.\n")
        tool.prepare("DOC-1", str(path))
        self.assertNotEqual(old, tool.context("DOC-1"))


class RetrieveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tool = RAGTool({"chunk_size": 400, "chunk_overlap": 60})
        self.tool.prepare("DOC-1", str(write_contract(Path(self.tmp.name))))

    def test_shape_and_offsets(self):
        result = self.tool.retrieve("DOC-1", "notice period to prevent renewal", top_k=3)
        self.assertIn("document_id", result)
        self.assertIsInstance(result["text"], list)
        self.assertTrue(result["text"])
        context = self.tool.context("DOC-1")
        for chunk in result["text"]:
            self.assertEqual(context[chunk["start"]:chunk["end"]], chunk["text"])
            self.assertEqual(set(chunk) >= {"chunk_id", "text", "start", "end", "score"}, True)

    def test_top_k_respected(self):
        result = self.tool.retrieve("DOC-1", "agreement", top_k=2)
        self.assertLessEqual(len(result["text"]), 2)

    def test_unknown_document(self):
        result = self.tool.retrieve("NOPE", "agreement")
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["text"], [])

    def test_empty_query_rejected(self):
        result = self.tool.retrieve("DOC-1", "   ")
        self.assertEqual(result["status"], "FAILED")


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tool = RAGTool({"chunk_size": 400, "chunk_overlap": 60, "model_call": model_supported})
        self.tool.prepare("DOC-1", str(write_contract(Path(self.tmp.name))))
        self.context = self.tool.context("DOC-1")
        self.quote = "shall automatically renew for successive one (1) year periods"
        self.start = self.context.index(self.quote)

    def test_valid_quotes_pass(self):
        result = self.tool.verify("DOC-1", "Renewal Term", "successive 1 year",
                                  [{"text": self.quote, "answer_start": self.start}])
        self.assertEqual(result["verification_status"], "PASSED")
        self.assertTrue(result["evidence_checks"][0]["position_valid"])
        self.assertEqual(result["evidence_checks"][0]["support_status"], "SUPPORTED")
        self.assertIn("page", result["evidence_checks"][0])

    def test_offset_mismatch_fails_before_model(self):
        called = {"n": 0}

        def counting(messages):
            called["n"] += 1
            return model_supported(messages)

        tool = RAGTool({"chunk_size": 400, "chunk_overlap": 60, "model_call": counting})
        tool.prepare("DOC-1", str(write_contract(Path(self.tmp.name))))
        result = tool.verify("DOC-1", "Renewal Term", "successive 1 year",
                             [{"text": self.quote, "answer_start": self.start + 5}])
        self.assertEqual(result["verification_status"], "FAILED")
        self.assertEqual(called["n"], 0)
        self.assertFalse(result["evidence_checks"][0]["position_valid"])

    def test_empty_evidence_is_not_passed(self):
        result = self.tool.verify("DOC-1", "Renewal Term", "successive 1 year", [])
        self.assertEqual(result["verification_status"], "UNCERTAIN")

    def test_yes_answer_without_evidence_is_uncertain(self):
        result = self.tool.verify("DOC-1", "Insurance", "Yes", [])
        self.assertEqual(result["verification_status"], "UNCERTAIN")
        self.assertEqual(result["coverage_status"], "NOT_APPLICABLE")  # 只有 No 才谈覆盖

    def test_no_with_zero_topic_mentions_passes(self):
        """全文没有审计锚定词：缺席判断有全局依据，可以 PASSED。"""
        result = self.tool.verify("DOC-1", "Audit Rights", "No", [])
        self.assertEqual(result["coverage_status"], "SUFFICIENT")
        self.assertEqual(result["verification_status"], "PASSED")

    def test_no_with_unretrieved_mentions_is_insufficient(self):
        """全文提到过保险，但这轮没检索到 → 不能判 No。"""
        text = CONTRACT + "\n6. Insurance. Supplier shall maintain commercial general liability insurance.\n"
        tool = RAGTool({"chunk_size": 300, "chunk_overlap": 40, "model_call": model_supported})
        tool.prepare("DOC-INS", str(write_contract(Path(self.tmp.name), "ins.txt", text)))
        retrieval = tool.retrieve("DOC-INS", "Acme Software Beta Retail parties", top_k=1)  # 故意不查保险
        history = [{"query": "parties", "top_k": 1,
                    "retrieved_chunk_ids": [c["chunk_id"] for c in retrieval["text"]]}]
        result = tool.verify("DOC-INS", "Insurance", "No", [], retrieval_history=history)
        self.assertEqual(result["coverage_status"], "INSUFFICIENT")
        self.assertEqual(result["verification_status"], "UNCERTAIN")
        self.assertIn("insurance", " ".join(item["term"] for item in result["coverage_detail"]["uncovered"]).lower())

    def test_no_with_full_coverage_passes(self):
        tool = RAGTool({"chunk_size": 4000, "chunk_overlap": 0, "model_call": model_supported})
        tool.prepare("DOC-1", str(write_contract(Path(self.tmp.name))))
        retrieval = tool.retrieve("DOC-1", "audit rights inspection of books and records", top_k=5)
        history = [{"query": "audit rights", "top_k": 5,
                    "retrieved_chunk_ids": [c["chunk_id"] for c in retrieval["text"]]}]
        result = tool.verify("DOC-1", "Audit Rights", "No", [], retrieval_history=history)
        # 全文只有一块且已被检索覆盖；锚定词都在块内 → 覆盖充分
        self.assertEqual(result["coverage_status"], "SUFFICIENT")
        self.assertEqual(result["verification_status"], "PASSED")

    def test_model_failure_is_uncertain(self):
        tool = RAGTool({"chunk_size": 400, "chunk_overlap": 60, "model_call": model_error})
        tool.prepare("DOC-1", str(write_contract(Path(self.tmp.name))))
        result = tool.verify("DOC-1", "Renewal Term", "successive 1 year",
                             [{"text": self.quote, "answer_start": self.start}])
        self.assertEqual(result["verification_status"], "UNCERTAIN")
        self.assertIn("语义核验失败", result["reason"])

    def test_missing_model_is_uncertain(self):
        tool = RAGTool({"semantic": False})
        tool.prepare("DOC-1", str(write_contract(Path(self.tmp.name))))
        result = tool.verify("DOC-1", "Renewal Term", "successive 1 year",
                             [{"text": self.quote, "answer_start": self.start}])
        self.assertEqual(result["verification_status"], "UNCERTAIN")

    def test_lowercase_yes_is_normalised(self):
        result = self.tool.verify("DOC-1", "Termination For Convenience", "no", [])
        self.assertEqual(result["category_answer"], "No")

    def test_unknown_category_fails(self):
        result = self.tool.verify("DOC-1", "Cap On Liability", "Yes", [])
        self.assertEqual(result["verification_status"], "FAILED")
        self.assertEqual(result["diagnostic_codes"], ["UNSUPPORTED_CATEGORY"])

    def test_malformed_quote_dict_fails(self):
        result = self.tool.verify("DOC-1", "Renewal Term", "x",
                                  [{"text": self.quote, "answer_start": self.start, "extra": 1}])
        self.assertEqual(result["verification_status"], "FAILED")


class StorageLayoutTest(unittest.TestCase):
    """与 4 号约定一致：_indexes 存分块/检索结构，_contexts 存全文，检索只认 document_id。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tool = RAGTool({"chunk_size": 400, "chunk_overlap": 60, "semantic": False,
                             "max_documents": 2})
        self.tool.prepare("DOC-1", str(write_contract(Path(self.tmp.name))))

    def test_index_cache_holds_chunks(self):
        entry = self.tool._indexes["DOC-1"]
        self.assertTrue(entry["chunks"])
        self.assertTrue(all({"start", "end", "text"} <= set(chunk) for chunk in entry["chunks"]))

    def test_context_cache_holds_full_text(self):
        entry = self.tool._contexts["DOC-1"]
        self.assertEqual(entry["text"], self.tool.context("DOC-1"))
        self.assertEqual(len(entry["sha256"]), 64)

    def test_retrieval_needs_only_document_id(self):
        result = self.tool.retrieve("DOC-1", "notice of non-renewal", top_k=2)
        self.assertEqual(result["status"], "OK")
        context = self.tool._contexts["DOC-1"]["text"]
        for chunk in result["text"]:
            self.assertEqual(context[chunk["start"]:chunk["end"]], chunk["text"])

    def test_eviction_clears_both_caches(self):
        for index in range(3):
            self.tool.prepare_text(f"DOC-{index}", CONTRACT, source="unit-test")
        self.assertEqual(len(self.tool._indexes), 2)
        self.assertEqual(len(self.tool._contexts), 2)
        self.assertEqual(set(self.tool._indexes), set(self.tool._contexts))


class ExpansionAndTextEntryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tool = RAGTool({"chunk_size": 400, "chunk_overlap": 60, "semantic": False})
        self.tool.prepare("DOC-1", str(write_contract(Path(self.tmp.name))))

    def test_category_expansion_is_opt_in(self):
        plain = self.tool.retrieve("DOC-1", "How long does it renew?", top_k=3)
        self.assertFalse(plain["expanded"])
        expanded = self.tool.retrieve("DOC-1", "How long does it renew?", top_k=3,
                                      category="Renewal Term")
        self.assertTrue(expanded["expanded"])
        self.assertIn("renewal", expanded["effective_query"].lower())

    def test_template_question_expands_without_category(self):
        result = self.tool.retrieve("DOC-1", "What is the renewal term?", top_k=3)
        self.assertTrue(result["expanded"])
        self.assertEqual(result["query_source"], "template")
        self.assertEqual(result["resolved_category"], "Renewal Term")

    def test_reworded_question_does_not_guess(self):
        result = self.tool.retrieve("DOC-1", "How long is the renewal period?", top_k=3)
        self.assertFalse(result["expanded"])
        self.assertEqual(result["query_source"], "none")

    def test_explicit_category_wins(self):
        result = self.tool.retrieve("DOC-1", "notice", top_k=3, category="Renewal Term")
        self.assertEqual(result["query_source"], "explicit")
        self.assertEqual(result["resolved_category"], "Renewal Term")

    def test_prepare_text_accepts_inline_contract(self):
        result = self.tool.prepare_text("DOC-TXT", CONTRACT, source="unit-test")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["method"], "inline")
        self.assertEqual(self.tool.context("DOC-TXT"), CONTRACT)

    def test_prepare_text_rejects_empty(self):
        result = self.tool.prepare_text("DOC-EMPTY", "   ")
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["error_code"], "EMPTY_DOCUMENT")


class DiagnosticCodeTest(unittest.TestCase):
    """4 号的重试分支按 code 走，不解析中文 reason。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tool = RAGTool({"chunk_size": 400, "chunk_overlap": 60, "model_call": model_supported})
        self.tool.prepare("DOC-1", str(write_contract(Path(self.tmp.name))))
        self.context = self.tool.context("DOC-1")
        self.quote = "shall automatically renew for successive one (1) year periods"
        self.start = self.context.index(self.quote)

    def test_position_mismatch_code(self):
        result = self.tool.verify("DOC-1", "Renewal Term", "1 year",
                                  [{"text": self.quote, "answer_start": self.start + 3}])
        self.assertEqual(result["diagnostic_codes"], ["POSITION_MISMATCH"])

    def test_no_evidence_code(self):
        result = self.tool.verify("DOC-1", "Renewal Term", "1 year", [])
        self.assertEqual(result["diagnostic_codes"], ["NO_EVIDENCE"])

    def test_coverage_insufficient_code(self):
        text = CONTRACT + "\n6. Insurance. Supplier shall keep liability insurance.\n"
        tool = RAGTool({"chunk_size": 300, "chunk_overlap": 40, "model_call": model_supported})
        tool.prepare("DOC-INS", str(write_contract(Path(self.tmp.name), "ins2.txt", text)))
        result = tool.verify("DOC-INS", "Insurance", "No", [])
        self.assertEqual(result["coverage_status"], "INSUFFICIENT")
        self.assertIn("COVERAGE_INSUFFICIENT", result["diagnostic_codes"])

    def test_success_has_no_codes(self):
        result = self.tool.verify("DOC-1", "Renewal Term", "successive 1 year",
                                  [{"text": self.quote, "answer_start": self.start}])
        self.assertEqual(result["diagnostic_codes"], [])

    def test_question_is_passed_to_model(self):
        seen = {}

        def capture(messages):
            import json as _json
            seen.update(_json.loads(messages[-1]["content"]))
            return model_supported(messages)

        tool = RAGTool({"chunk_size": 400, "chunk_overlap": 60, "model_call": capture})
        tool.prepare("DOC-Q", str(write_contract(Path(self.tmp.name), "q.txt")))
        ctx = tool.context("DOC-Q")
        quote = "shall automatically renew for successive one (1) year periods"
        tool.verify("DOC-Q", "Renewal Term", "1 year",
                    [{"text": quote, "answer_start": ctx.index(quote)}],
                    question="Is renewal automatic?")
        self.assertEqual(seen.get("question"), "Is renewal automatic?")


class ConfigurationTest(unittest.TestCase):
    def test_configuration_reports_units(self):
        config = RAGTool({"semantic": False}).configuration()
        self.assertEqual(config["offset_unit"], "Unicode code points, zero-based [start,end)")
        self.assertEqual(len(config["categories"]), 11)
        self.assertEqual(config["chunking"]["chunk_size"], 800)


if __name__ == "__main__":
    unittest.main(verbosity=2)
