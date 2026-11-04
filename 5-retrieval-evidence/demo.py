"""十一类任务的联调冒烟：RAGTool + 最小 Agent 循环 + MockRuleTool。

这不是 4 号的 Agent 实现，只是用与《工程架构与工具接口_修订版》一致的调用顺序
（prepare → retrieve → 抽取 → verify → 规则）跑一遍，证明工具接口可用、字段对得上。

抽取与语义核验都用**确定性桩**：
* 抽取：用检索到的块 + 正则抓答案与引文（标注 STUB）；
* 语义核验：判断引文是否包含答案关键词（标注 STUB，不代表真实模型效果）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.rag_tool import RAGTool  # noqa: E402

CONTRACT = """SERVICE AGREEMENT

1. Parties. This Service Agreement is entered into between Nova Systems Inc. and Orbit Retail LLC.

2. Term and Renewal. The initial term is twelve (12) months and shall automatically renew for
successive one (1) year periods unless either party gives written notice of non-renewal at least
ninety (90) days prior to the end of the then-current term.

3. Termination for Convenience. Customer may terminate this Agreement for any reason upon thirty
(30) days prior written notice.

4. Governing Law. This Agreement shall be governed by the laws of the State of Colorado.

5. Fees. Customer shall pay the fees in Exhibit A within thirty (30) days of invoice.

6. Limitation of Liability. Aggregate liability shall not exceed the fees paid in the prior
twelve (12) months.
"""

QUESTIONS = {
    "Document Name": "What is the name of this agreement?",
    "Parties": "Who are the contracting parties?",
    "Agreement Date": "What is the agreement date?",
    "Effective Date": "When does the agreement become effective?",
    "Expiration Date": "When does the agreement expire?",
    "Governing Law": "Which jurisdiction governs the agreement?",
    "Renewal Term": "What is the renewal term?",
    "Notice Period To Terminate Renewal": "What advance notice is required to prevent renewal?",
    "Insurance": "Does the agreement impose insurance obligations?",
    "Audit Rights": "Does a party have audit or inspection rights?",
    "Termination For Convenience": "May a party terminate without cause?",
}

PATTERNS = {
    # category: (正则, 固定答案或 None=用捕获组1, 是否 Yes/No 类)
    "Governing Law": (r"laws of the State of ([A-Z][a-z]+)", None, False),
    "Renewal Term": (r"successive\s+one\s*\(1\)\s*year", "successive 1 year", False),
    "Notice Period To Terminate Renewal": (r"at least\s+ninety\s*\(90\)\s*days", "90 days", False),
    "Termination For Convenience": (r"for any reason", "Yes", True),
    "Document Name": (r"SERVICE AGREEMENT", "SERVICE AGREEMENT", False),
    "Parties": (r"Nova Systems Inc\.\s+and\s+Orbit Retail LLC", "Nova Systems Inc.; Orbit Retail LLC", False),
}


def stub_extract(category: str, chunks: list[dict]) -> dict:
    """确定性抽取桩：在候选块里找模式，返回答案 + 原文引文。"""
    entry = PATTERNS.get(category)
    if entry is None:
        return {"category_answer": None, "predicted_answers": [], "processing_status": "INCOMPLETE"}
    pattern, fixed, yes_no = entry
    for chunk in chunks:
        match = re.search(pattern, chunk["text"])
        if match:
            answer = fixed if fixed is not None else match.group(1)
            return {
                "category_answer": answer,
                "predicted_answers": [{"text": match.group(0), "answer_start": chunk["start"] + match.start()}],
                "processing_status": "COMPLETED",
            }
    return {"category_answer": None, "predicted_answers": [], "processing_status": "INCOMPLETE"}


def stub_model(messages) -> dict:
    """语义核验桩：引文包含答案关键词即判 SUPPORTED（明确是桩）。"""
    import json
    payload = json.loads(messages[-1]["content"])
    checks = []
    for quote in payload["quotes"]:
        text = quote["text"].lower()
        answer = str(payload["proposed_answer"]).lower()
        if answer in ("yes", "no"):
            hit = True  # STUB：Yes/No 由抽取桩的匹配保证，此处不重复判断
        else:
            tokens = [t for t in re.split(r"[^a-z0-9]+", answer) if len(t) > 2]
            hit = any(token in text for token in tokens) if tokens else False
        checks.append({"answer_index": quote["answer_index"],
                       "support_status": "SUPPORTED" if hit else "INSUFFICIENT",
                       "reason": "STUB：引文包含答案关键词。" if hit else "STUB：引文未包含答案关键词。"})
    overall = "SUPPORTED" if checks and all(c["support_status"] == "SUPPORTED" for c in checks) else "INSUFFICIENT"
    return {"evidence_checks": checks,
            "overall_support": {"status": overall, "reason": "STUB 判定，不代表真实模型或人工结论。",
                                "evidence_indices": [c["answer_index"] for c in checks]}}


class MockRuleTool:
    """仅演示调用顺序；真实规则在 3 号模块。"""

    THRESHOLD_DAYS = 60

    def evaluate(self, *, document_id, question_id, category, category_answer, predicted_answers,
                 evidence_checks, processing_status, verification_status, coverage_status):
        if category not in {"Governing Law", "Notice Period To Terminate Renewal"}:
            return []
        if processing_status != "COMPLETED" or verification_status != "PASSED":
            return [{"status": "NEEDS_REVIEW", "level": None, "reason": "上游未通过核验。",
                     "evidence_indices": [], "missing_items": ["verified_extraction"],
                     "recommendation": "补查或转人工。"}]
        if category == "Notice Period To Terminate Renewal":
            match = re.search(r"(\d+)\s*days", str(category_answer))
            if match and int(match.group(1)) > self.THRESHOLD_DAYS:
                return [{"status": "REVIEWED", "level": "MEDIUM",
                         "reason": f"{match.group(1)} 天超过示例阈值 {self.THRESHOLD_DAYS} 天。",
                         "evidence_indices": [0], "missing_items": [], "recommendation": "复核通知期。"}]
        return [{"status": "REVIEWED", "level": "LOW", "reason": "示例规则：清单内或未触发。",
                 "evidence_indices": [0], "missing_items": [], "recommendation": "无需动作。"}]


def main() -> int:
    tool = RAGTool({"chunk_size": 600, "chunk_overlap": 100, "model_call": stub_model})
    prepared = tool.prepare("DEMO-001", str(Path(__file__).with_name("demo_contract.txt")))
    if prepared["status"] != "SUCCESS":
        print("prepare failed:", prepared)
        return 1
    rules = MockRuleTool()
    print(f"{'category':36s} {'chunks':>6s} {'answer':22s} {'verify':9s} {'coverage':13s} rules")
    print("-" * 110)
    for index, (category, question) in enumerate(QUESTIONS.items(), start=1):
        retrieval = tool.retrieve("DEMO-001", question, top_k=5)
        chunks = retrieval["text"]
        extraction = stub_extract(category, chunks)
        history = [{"query": question, "top_k": 5,
                    "retrieved_chunk_ids": [c["chunk_id"] for c in chunks]}]
        verification = tool.verify("DEMO-001", category, extraction["category_answer"],
                                   extraction["predicted_answers"], retrieval_history=history)
        reviews = rules.evaluate(document_id="DEMO-001", question_id=f"Q{index}", category=category,
                                 category_answer=extraction["category_answer"],
                                 predicted_answers=extraction["predicted_answers"],
                                 evidence_checks=verification["evidence_checks"],
                                 processing_status=extraction["processing_status"],
                                 verification_status=verification["verification_status"],
                                 coverage_status=verification["coverage_status"])
        rules_text = "; ".join(f"{r['status']}/{r['level']}" for r in reviews) or "[]"
        print(f"{category:36s} {len(chunks):6d} {str(extraction['category_answer'])[:20]:22s} "
              f"{verification['verification_status']:9s} {verification['coverage_status']:13s} {rules_text}")
    print("\n注：抽取与语义核验均为 STUB，仅验证接口与状态流转；规则为演示阈值。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
