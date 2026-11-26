"""Extract local CUAD development samples; standard library only, no model calls.

TXT and gold files are immutable on rerun: existing different bytes cause an error.
Only pdf_ingest.py (a local, network-free text normalizer) is loaded from Agent.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
TITLES = {
    "CUAD-001": "SIBANNAC,INC_12_04_2017-EX-2.1-Strategic Alliance Agreement",
    "CUAD-004": "EUROPEANMICROHOLDINGSINC_03_06_1998-EX-10.6-DISTRIBUTOR AGREEMENT",
    "CUAD-008": "GluMobileInc_20070319_S-1A_EX-10.09_436630_EX-10.09_Content License Agreement2",
}
EXPECTED = {"CUAD-001": (8380, 11, 14), "CUAD-004": (56952, 21, 38),
            "CUAD-008": (11954, 9, 25)}
FOCUS = {
    "Termination For Convenience": ("termination_for_convenience_spans", (1, 4, 0)),
    "Change Of Control": ("change_of_control_spans", (0, 2, 0)),
    "Anti-Assignment": ("anti_assignment_spans", (1, 3, 0)),
    "Uncapped Liability": ("uncapped_liability_spans", (0, 1, 0)),
    "Cap On Liability": ("cap_on_liability_spans", (0, 3, 0)),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def save(path: Path, data: bytes, *, immutable: bool = False) -> None:
    if path.exists() and path.read_bytes() != data and immutable:
        raise ValueError(f"Existing file differs; preserved without overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def literal_assignment(path: Path, name: str):
    for node in ast.parse(path.read_bytes()).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"Missing literal assignment {name}: {path.name}")


def load_ingest(root: Path):
    path = root / "4-agent/code/tools/rag_tool/rag_core/pdf_ingest.py"
    spec = importlib.util.spec_from_file_location("member7_local_ingest", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # required by dataclasses; no package side effects
    spec.loader.exec_module(module)
    return module, path


def normalization_trace(raw: str, expected: str):
    """Track raw character provenance, then assert equality to ACTUAL normalizer.

    Each item is (normalized character, raw start, raw end). Many-to-one whitespace
    replacements retain the whole source interval. The synthetic final LF has a
    zero-width source at EOF. This is a coordinate aid, never a semantic score.
    """
    traced = [(c, i, i + 1) for i, c in enumerate(raw)]

    def sub(pattern, replacement):
        nonlocal traced
        text = "".join(item[0] for item in traced)
        output, cursor = [], 0
        for match in re.finditer(pattern, text):
            start, end = match.span()
            output.extend(traced[cursor:start])
            output.extend((c, traced[start][1], traced[end - 1][2]) for c in replacement)
            cursor = end
        output.extend(traced[cursor:])
        traced = output

    sub(r"\r\n|\r|\f", "\n")
    sub("\u00a0", " ")
    sub("[\u200b\ufeff\x00]", "")
    sub(r"[ \t\u00a0]+", " ")
    sub(r"[^\S\n]+(?=\n|$)", "")  # per-line rstrip
    sub(r"\n{3,}", "\n\n")
    start, end = 0, len(traced)
    while start < end and traced[start][0].isspace():
        start += 1
    while end > start and traced[end - 1][0].isspace():
        end -= 1
    traced = traced[start:end] + [("\n", len(raw), len(raw))]
    if "".join(x[0] for x in traced) != expected:
        raise ValueError("Normalization implementation changed; mapping rejected")

    runs = []
    for index, (char, start, end) in enumerate(traced):
        kind = ("insert" if start == end else
                "copy" if end == start + 1 and raw[start:end] == char else "replace")
        if kind == "copy" and runs and runs[-1]["kind"] == kind and runs[-1]["raw_end"] == start:
            runs[-1]["raw_end"] = end
            runs[-1]["normalized_end"] = index + 1
        else:
            runs.append({"kind": kind, "raw_start": start, "raw_end": end,
                         "normalized_start": index, "normalized_end": index + 1})
    return traced, runs


def project_gold(qas, traced, normalized):
    projections = []
    for qa in qas:
        for index, answer in enumerate(qa["answers"]):
            start, end = answer["answer_start"], answer["answer_start"] + len(answer["text"])
            hits = [i for i, (_, a, b) in enumerate(traced) if a < end and b > start]
            ns, ne = (hits[0], hits[-1] + 1) if hits else (None, None)
            shared = bool(hits and (traced[ns][1] < start or traced[ne - 1][2] > end))
            projections.append({"question_id": qa["id"], "category": qa["category"],
                                "answer_index": index, "raw_start": start, "raw_end": end,
                                "normalized_start": ns, "normalized_end": ne,
                                "normalized_text": normalized[ns:ne] if hits else None,
                                "boundary_shared_with_outside_span": shared})
    return projections


def prepare(root: Path, data_dir: Path, manifest: Path) -> dict:
    dest = root / "7-case-governance"
    result = dest / "results/data_preparation"
    with manifest.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    sources, indexes, file_info = {}, {}, {}
    for name in ("CUADv1.json", "train_separate_questions.json", "test.json"):
        path = data_dir / name
        content = path.read_bytes()
        dataset = json.loads(content)
        sources[name] = dataset["data"]
        titles = [x["title"] for x in dataset["data"]]
        if len(titles) != len(set(titles)):
            raise ValueError(f"Duplicate full contract title in {name}")
        indexes[name] = {x["title"]: (i, x) for i, x in enumerate(dataset["data"])}
        file_info[name] = {"path": str(path.resolve()), "bytes": len(content),
                           "sha256": sha(content), "version": dataset.get("version"),
                           "contract_count": len(titles)}
    all_titles, train_titles, test_titles = (set(indexes[n]) for n in sources)
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    check([len(x) for x in (all_titles, train_titles, test_titles)] == [510, 408, 102],
          "Dataset counts differ from expected 510/408/102")
    check(not train_titles & test_titles, "Train and test titles overlap")
    check(all_titles == train_titles | test_titles, "Splits do not partition CUADv1 titles")
    catalog_path = root / "4-agent/code/agents/clause_catalog.py"
    catalog = {c[1]: c[0] for c in literal_assignment(catalog_path, "CLAUSES")}
    check(len(catalog) == 41, "Agent catalog is not 41 unique categories")
    ingest, ingest_path = load_ingest(root)
    samples = []
    for sample_index, (sid, title) in enumerate(TITLES.items()):
        before_errors = len(errors)
        matches = [x for x in rows if x["sample_id"] == sid]
        if len(matches) != 1 or matches[0]["contract_title"] != title:
            raise ValueError(f"Manifest full-title mismatch / duplicate: {sid}")
        row = matches[0]
        entry_index, entry = indexes["CUADv1.json"][title]
        # Never concatenate contexts: offsets are paragraph-local in SQuAD.
        if len(entry["paragraphs"]) != 1:
            raise ValueError(f"Expected one full-document paragraph: {sid}")
        paragraph = entry["paragraphs"][0]
        raw = paragraph["context"]
        content, qas = raw.encode("utf-8"), []
        bad_spans, bad_flags = [], []
        for original in paragraph["qas"]:
            match = re.search(r'related to "([^"]+)"', original["question"])
            if not match:
                raise ValueError(f"Cannot identify question category: {original['id']}")
            category = match[1]
            qa = dict(original)  # all original QA/answer fields preserved
            qa.update(category=category, agent_question_id=catalog.get(category))
            check(qa["id"] == f"{title}__{category}", f"{sid}: question ID/category mismatch")
            if bool(qa["is_impossible"]) != (not qa["answers"]):
                bad_flags.append(qa["id"])
            for j, answer in enumerate(qa["answers"]):
                start, text = answer["answer_start"], answer["text"]
                valid = (isinstance(start, int) and start >= 0 and start + len(text) <= len(raw)
                         and raw[start:start + len(text)] == text)
                if not valid:
                    bad_spans.append({"question_id": qa["id"], "answer_index": j,
                                      "answer_start": start})
            qas.append(qa)
        counts = {q["category"]: len(q["answers"]) for q in qas}
        actual = (len(raw), sum(bool(q["answers"]) for q in qas),
                  sum(len(q["answers"]) for q in qas))
        comparisons = []

        def compare(field, value, expected, source):
            matched = value == expected
            comparisons.append({"field": field, "actual": value, "expected": expected,
                                "reference": source, "matches": matched})
            check(matched, f"{sid}: {field} differs from {source}; original data retained")

        for field, value, expected in zip(("context_chars", "answered_categories", "answer_spans"), actual, EXPECTED[sid]):
            compare(field, value, expected, "user_expected")
        for field, value in (("context_chars", len(raw)), ("context_sha256", sha(content))):
            compare(field, value, int(row[field]) if field == "context_chars" else row[field], "manifest")
        for category, (field, expected) in FOCUS.items():
            compare(field, counts.get(category, 0), expected[sample_index], "user_expected")
            compare(field, counts.get(category, 0), int(row[field]), "manifest")
        split = "train" if title in train_titles and title not in test_titles else "unexpected"
        compare("source_split", split, row["source_split"], "manifest")
        compare("source_split", split, "train", "user_expected")
        compare("planned_use", row["planned_use"], "development", "user_expected")
        compare("source_file", row["source_file"], "CUADv1.json", "manifest_vs_input")
        check(len(qas) == 41 and set(counts) == set(catalog), f"{sid}: category set/count differs")
        check(not bad_spans, f"{sid}: invalid original answer offsets")
        check(not bad_flags, f"{sid}: inconsistent is_impossible values")
        train_match = indexes["train_separate_questions.json"].get(title)
        train_paragraphs = train_match[1]["paragraphs"] if train_match else []
        train_context_same = len(train_paragraphs) == 1 and train_paragraphs[0]["context"] == raw
        check(train_context_same, f"{sid}: training context missing or different")

        txt_path = dest / "contracts" / f"{sid}.txt"
        gold_path = dest / "annotations" / f"{sid}_gold.json"
        gold = {"schema_version": 1, "sample_id": sid, "contract_title": title,
                "source_file": "CUADv1.json", "source_data_index": entry_index,
                "paragraph_index": 0, "source_split": split, "planned_use": row["planned_use"],
                "usage": "evaluation_only_do_not_pass_to_agent_or_rag",
                "coordinate_system": "CUAD_original_context_unicode_codepoints_zero_based_end_exclusive",
                "context_chars": len(raw), "context_sha256": sha(content), "qas": qas}
        save(txt_path, content, immutable=True)
        save(gold_path, json_bytes(gold), immutable=True)
        check(txt_path.read_bytes() == content, f"{sid}: written TXT differs from original UTF-8 bytes")
        normalized = ingest.ingest(txt_path).text  # no embeddings, client, or network
        traced, runs = normalization_trace(raw, normalized)
        projections = project_gold(qas, traced, normalized)
        mapping_path = result / f"{sid}_offset_mapping.json"
        mapping = {"schema_version": 1, "sample_id": sid, "raw_sha256": sha(content),
                   "normalized_sha256": sha(normalized.encode("utf-8")),
                   "normalizer_sha256": sha(ingest_path.read_bytes()),
                   "coordinate_unit": "unicode_codepoints_zero_based_end_exclusive",
                   "semantics": "copy: exact 1:1; replace: whole source interval; insert: no raw source; raw gaps: deleted",
                   "runs": runs, "gold_span_projections": projections}
        save(mapping_path, json_bytes(mapping))
        samples.append({"sample_id": sid, "contract_title": title,
                        "contract_type_hint": row["contract_type_hint"], "source_data_index": entry_index,
                        "source_split": split, "planned_use": row["planned_use"],
                        "selection_reason": row["selection_reason"],
                        "context_chars": actual[0], "context_bytes_utf8": len(content),
                        "context_sha256": sha(content), "category_count": len(qas),
                        "answered_categories": actual[1], "answer_spans": actual[2],
                        "category_span_counts": counts, "span_validation_passed": actual[2] - len(bad_spans),
                        "invalid_spans": bad_spans, "inconsistent_impossible_flags": bad_flags,
                        "training_context_identical": train_context_same,
                        "training_question_count": len(train_paragraphs[0]["qas"]) if train_paragraphs else None,
                        "comparisons": comparisons, "status": "PASS" if len(errors) == before_errors else "FAIL",
                        "normalization": {"raw_equals_normalized": raw == normalized,
                                          "normalized_chars": len(normalized),
                                          "normalized_sha256": mapping["normalized_sha256"],
                                          "raw_characters_removed_net": len(raw) - len(normalized) + 1,
                                          "mapping_runs": len(runs), "mapping_verified_against_agent_ingest": True,
                                          "gold_projection_count": len(projections)},
                        "files": {"contract": str(txt_path.relative_to(root)),
                                  "gold": str(gold_path.relative_to(root)),
                                  "offset_mapping": str(mapping_path.relative_to(root))}})

    return {"schema_version": 1, "prepared_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "status": "PASS" if not errors else "FAIL", "errors": errors,
            "scope": "local_data_preparation_only_no_model_calls_no_agent_review",
            "python_version": sys.version.split()[0], "python_executable": sys.executable,
            "sources": file_info, "manifest": {"path": str(manifest.resolve()), "sha256": sha(manifest.read_bytes())},
            "provenance": {"local_reference": "1-problem-data/problem_and_data.md section 3.1",
                           "description": "CUAD v1; Atticus Project; SEC EDGAR public contracts",
                           "upstream_commit_recorded_by_member1": "67faa0e6023b04fcaae6cc09497ab00e5d63a2a2",
                           "note": "Provenance transcribed from member1 local documentation; upstream not fetched or revalidated"},
            "split_validation": {"train_test_overlap": sorted(train_titles & test_titles),
                                 "union_matches_full_dataset": all_titles == train_titles | test_titles},
            "agent_sources": {"catalog": str(catalog_path.relative_to(root)),
                              "catalog_sha256": sha(catalog_path.read_bytes()),
                              "normalizer": str(ingest_path.relative_to(root)),
                              "normalizer_sha256": sha(ingest_path.read_bytes())}, "samples": samples}


def markdown_report(report):
    lines = ["# CUAD真实合同数据准备验证报告", "", f"生成时间：{report['prepared_at']}；总状态：**{report['status']}**。",
             "本报告仅记录本地数据提取与验证，未运行Agent审查或调用模型API。", "",
             "## 数据与选择依据", "",
             "来源为成员1提供的三个本地JSON；上游来源沿用 `1-problem-data/problem_and_data.md` 第3.1节记录，本轮未重新下载或联网核验。完整数据510份、训练408份、测试102份，实际值及文件SHA-256见同目录JSON报告。",
             "按完整标题精确匹配，不用模糊匹配；三份均为训练侧development样本，未提取成员6预留测试合同。", "",
             "| 样本 | 原文字符 | UTF-8字节 | 全部类别 | 有答案类别 | 标注片段 | 偏移验证 | 状态 |",
             "|---|---:|---:|---:|---:|---:|---:|---|"]
    for s in report["samples"]:
        lines.append(f"| {s['sample_id']} | {s['context_chars']} | {s['context_bytes_utf8']} | {s['category_count']} | {s['answered_categories']} | {s['answer_spans']} | {s['span_validation_passed']}/{s['answer_spans']} | {s['status']} |")
    lines += ["", "所有字符数按Python Unicode字符计数；SHA-256针对 `context.encode('utf-8')`，同时验证TXT文件字节完全一致。标注偏移从0开始，右端不含。", "",
              "## 样本明细", ""]
    for s in report["samples"]:
        n = s["normalization"]
        lines += [f"### {s['sample_id']}", "", f"完整标题：`{s['contract_title']}`。", "",
                  f"选择理由：{s['selection_reason']}。类型仅为标题提示，尚未进行法律审核。", "",
                  f"原文SHA-256：`{s['context_sha256']}`。", "",
                  f"划分：{s['source_split']} / {s['planned_use']}；训练文件正文与完整数据一致，训练问答条目数为{s['training_question_count']}，本次gold取完整数据的41项。", "",
                  f"Agent规范化后为{n['normalized_chars']}字符；规范化SHA-256：`{n['normalized_sha256']}`。空白压缩等处理净删除{n['raw_characters_removed_net']}个字符，另补1个末尾LF。", ""]
    lines += ["## 五类重点条款的标注片段数", "", "| 类别（本地Agent编号） | CUAD-001 | CUAD-004 | CUAD-008 |", "|---|---:|---:|---:|"]
    qids = ("Q16", "Q18", "Q19", "Q35", "Q36")
    for qid, category in zip(qids, FOCUS):
        values = " | ".join(str(s["category_span_counts"][category]) for s in report["samples"])
        lines.append(f"| {category}（{qid}） | {values} |")
    lines += ["", "## 对照与坐标约束", "",
              "逐项对照包括标题、来源文件、划分、开发用途、原文长度、原文哈希及五类条款计数；有答案类别数与全部片段数另与本轮给定预期比较。CSV未提供的统计不冒充CSV字段。逐项结果在 `validation_report.json` 的 `comparisons` 中。",
              "", "TXT直接写入UTF-8字节，不加BOM、不加标题、不更改换行、不补末尾换行。gold保留全部原始QA字段及answers字段，只增加category和本地Agent编号，不包含合同全文。",
              "", "Agent的 `pdf_ingest.py` 会统一换行、压缩空格、去除部分不可见字符和行尾空白、压缩多余空行、strip后补一个LF。本轮仅加载该纯文本模块，不构建Agent/索引、不加载模型。",
              "", "各 `*_offset_mapping.json` 保存原文与规范化文本的坐标区间及全部gold片段的规范化投影；映射重建结果已与实际 `ingest(TXT).text` 严格比较。copy区间可逐字符对应，replace为整体映射，insert无原文对应，原文区间间隙为删除部分；边界共享会显式标记，不能据此推断语义正确。未保留字符的点位没有唯一反向坐标。",
              "", "后续先核对审查报告 `context_sha256` 与本报告的规范化哈希一致，再在规范化坐标中比较投影标注与Agent证据；查看原始标注时使用原文坐标。JavaScript字符串索引是UTF-16，未来网页若处理非BMP字符需要转换。TXT的合成page=1不是原PDF页码。",
              "", "人工标注只用于运行后评价，不作为Agent输入或RAG资料。CUAD空答案不证明原文必然不存在条款，CUAD标注也不是项目风险等级标签。本轮不提供条款识别、风险判断或人工复核结论。", "",
              "## 差异", ""]
    lines += [f"- {e}" for e in report["errors"]] if report["errors"] else ["未发现与给定预期或样本清单不一致的项目；原文与Agent规范化文本存在预期的空白处理差异。"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "1-problem-data/data")
    parser.add_argument("--manifest", type=Path, default=ROOT / "1-problem-data/sample_manifest_draft.csv")
    args = parser.parse_args()
    report = prepare(ROOT, args.data_dir.resolve(), args.manifest.resolve())
    out = ROOT / "7-case-governance/results/data_preparation"
    save(out / "validation_report.json", json_bytes(report))
    save(out / "validation_report.md", markdown_report(report).encode("utf-8"))
    print(f"Data preparation: {report['status']}")
    for sample in report["samples"]:
        print(f"{sample['sample_id']}: chars={sample['context_chars']} categories={sample['category_count']} "
              f"answered={sample['answered_categories']} spans={sample['answer_spans']} status={sample['status']}")
    for error in report["errors"]:
        print(error, file=sys.stderr)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError) as exc:
        print(f"Preparation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
