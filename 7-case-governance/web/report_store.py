"""Read-only presentation adapter for existing reports. No Agent/client imports."""
from __future__ import annotations

import ast
from collections import Counter
from datetime import datetime, timezone, timedelta
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
MEMBER = ROOT / "7-case-governance"
CODE = ROOT / "4-agent/code"
MODE_NAMES = {"FLAG_IF_CONDITION": "条件触发检查", "REQUIRE_PRESENT": "必要条款检查",
              "CONTEXT_REVIEW": "上下文复核", "INFORMATION_ONLY": "仅记录事实"}
REASON_NAMES = {"unconfirmed": "事实或证据无法确认", "coverage": "检索覆盖不足", "policy": "业务规则命中",
                "context": "上下文需要综合判断", "incomplete_policy": "政策配置不完整", "technical": "模型API或程序异常"}
GROUPS = [("基础信息与期限", 1, 8), ("交易与竞争安排", 9, 23), ("知识产权与许可", 24, 32), ("履约与责任安排", 33, 41)]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_bytes())


def clean(value):
    if isinstance(value, str):
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[凭据已隐藏]", value)
        return re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~-]+", "Bearer [已隐藏]", value)
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if not re.search(r"api[_-]?key|authorization|password|secret", k, re.I)}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def catalog():
    path = CODE / "agents/clause_catalog.py"
    tree = ast.parse(path.read_bytes())
    values = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "CLAUSES" for t in n.targets))
    return [{"id": qid, "name": name, "label": label, "question": question, "answer_type": kind,
             "group": next(label for label, lo, hi in GROUPS if lo <= int(qid[1:]) <= hi)}
            for qid, name, label, question, kind in values]


@lru_cache(maxsize=1)
def ingestion_module():
    # Load only the stdlib ingestion module; never import RAG/Embedding/LLM clients.
    spec = importlib.util.spec_from_file_location("workbench_ingest", CODE / "tools/rag_tool/rag_core/pdf_ingest.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def reasons(check):
    result = []
    rule = check.get("rule_review") or {}
    attempts = check.get("attempt_history") or [check]
    if check.get("stage_error") or check.get("model_error") or any(
            "MODEL_ERROR" in (a.get("diagnostic_codes") or []) for a in attempts):
        result.append("technical")
    if any(x.get("code") == "POLICY_INCOMPLETE" for x in rule.get("issues", [])):
        result.append("incomplete_policy")
    if any(x.get("status") == "TRIGGERED" and x.get("requires_manual_review") for x in check.get("review_results", [])):
        result.append("policy")
    if any(x.get("requires_manual_review") for x in rule.get("context_review_notes", [])):
        result.append("context")
    if check.get("coverage_status") == "INSUFFICIENT":
        result.append("coverage")
    if check.get("verification_status") != "PASSED" or check.get("processing_status") != "COMPLETED":
        result.append("unconfirmed")
    return result or ["unconfirmed"]


class ReportStore:
    def __init__(self):
        self.clauses = catalog()
        self.by_name = {c["name"]: c for c in self.clauses}
        self.entries = {}
        self._cache = {}
        self.refresh()

    def refresh(self):
        paths = list((CODE / "outputs/reports").glob("*.json"))
        for folder in sorted((MEMBER / "results").glob("CUAD-*/reports")):
            paths.extend(folder.glob("*.json"))
        for folder in sorted((MEMBER / "results/web_runs").glob("*/reports")):
            paths.extend(folder.glob("*.json"))
        entries = {}
        for path in sorted(paths):
            if path.name.endswith(".conversation.json") or not path.resolve().is_relative_to(ROOT.resolve()):
                continue
            try:
                raw = read_json(path)
                if not isinstance(raw.get("checks"), list) or not isinstance(raw.get("document_id"), str):
                    continue
                key = digest(str(path.relative_to(ROOT)).encode())[:20]
                parent = path.parent.parent
                meta = read_json(parent / "run_metadata.json") if (parent / "run_metadata.json").is_file() else {}
                sample = meta.get("sample_id")
                is_web = meta.get("scope") == "real_web_agent_run"
                if not sample and not is_web:
                    match = re.match(r"(CUAD-\d{3})", raw["document_id"])
                    sample = match[1] if match else None
                label = {"CUAD-001": "战略联盟协议", "CUAD-004": "分销协议", "CUAD-008": "内容许可修订协议"}.get(sample)
                label = (meta.get("original_filename") or raw.get("filename", "上传合同")) if is_web else label or ("认证失败演示" if "b48b4904" in raw["document_id"] else "演示合同" if raw["filename"].startswith("demo") else "网站托管协议")
                at = meta.get("started_at") or next((x.get("timestamp") for x in raw.get("execution_logs", []) if x.get("timestamp")), None)
                try:
                    date = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M") if at else "未记录"
                except ValueError:
                    date = "未记录"
                entries[key] = {"id": key, "path": path, "run_dir": parent, "sample": sample,
                                "title": f"{sample} · {label}" if sample else label, "label": label,
                                "date": date, "started_at": at, "document_id": raw["document_id"],
                                "filename": raw.get("filename", "未记录"), "status": raw.get("status"),
                                "count": len(raw["checks"]), "manual_count": len(raw.get("manual_review_items", [])),
                                "model": meta.get("extraction_model"), "web_task_id": meta.get("web_task_id"),
                                "source": "网页真实审查" if is_web else "CUAD真实运行" if sample else "既有演示运行"}
            except (OSError, ValueError, KeyError, TypeError):
                continue
        self.entries = entries
        self._cache = {key: value for key, value in self._cache.items() if key in entries}
        return self.list()

    def list(self):
        return [self.public(e) for e in sorted(self.entries.values(), key=lambda e: (e["sample"] == "CUAD-004", e["started_at"] or ""), reverse=True)]

    def public(self, entry):
        return {k: v for k, v in entry.items() if k not in ("path", "run_dir")}

    def get(self, key):
        if key not in self.entries:
            raise KeyError("Report not found")
        entry = self.entries[key]
        dependencies = [entry["path"], entry["run_dir"] / "run_metadata.json",
                        entry["path"].with_name(entry["path"].stem + ".conversation.json"),
                        entry["run_dir"] / "analysis/supplemental_review_items.json"]
        stamp = tuple(p.stat().st_mtime_ns if p.is_file() else None for p in dependencies)
        if key in self._cache and self._cache[key][0] == stamp:
            return self._cache[key][1]
        raw = read_json(entry["path"])
        meta_path = entry["run_dir"] / "run_metadata.json"
        meta = read_json(meta_path) if meta_path.is_file() else {}
        checks = []
        # Category is authoritative for historical reports whose Q numbering differs.
        for original in raw["checks"]:
            info = self.by_name.get(original.get("category"))
            if not info:
                continue
            rule = original.get("rule_review") or {}
            manual = next((m for m in raw.get("manual_review_items", []) if m.get("category") == original.get("category")), {})
            item = clean(original)
            item.update(qid=info["id"], recorded_qid=original.get("question_id"), label=info["label"],
                        group=info["group"], rule_executed=int(info["id"][1:]) > 5 and bool(rule),
                        mode=rule.get("mode") if int(info["id"][1:]) > 5 else "NOT_EXECUTED",
                        mode_label=MODE_NAMES.get(rule.get("mode"), "未记录") if int(info["id"][1:]) > 5 else "未执行",
                        risk_levels=sorted({r["risk_level"] for r in original.get("review_results", []) if r.get("risk_level")}),
                        triggered_rules=[r for r in original.get("review_results", []) if r.get("status") == "TRIGGERED"],
                        manual_reason_text=clean(manual.get("reason", "")),
                        manual_reasons=reasons(original) if original.get("needs_manual_review") or original.get("next_action") == "ESCALATE" else [])
            checks.append(item)
        verification = Counter(c.get("verification_status", "NOT_RECORDED") for c in checks)
        stats = {"reviewed": len(checks), "accepted": sum(c.get("next_action") == "ACCEPT" for c in checks),
                 "manual": sum(c.get("next_action") == "ESCALATE" for c in checks),
                 "passed": verification["PASSED"], "failed": verification["FAILED"], "uncertain": verification["UNCERTAIN"],
                 "triggered": sum(len(c["triggered_rules"]) for c in checks),
                 "retries": sum(c.get("retry_count", 0) for c in checks),
                 "reason_counts": dict(Counter(reason for c in checks for reason in c["manual_reasons"]))}
        progress_path = entry["path"].with_name(entry["path"].stem + ".conversation.json")
        try:
            messages = read_json(progress_path).get("messages", []) if progress_path.is_file() else []
        except (OSError, ValueError):
            messages = []  # Native main may still be writing the conversation.
        if not messages:
            messages = [{"role": "assistant", "content": json.dumps(x, ensure_ascii=False), "timestamp": x.get("timestamp")}
                        for x in raw.get("execution_logs", [])]
        suggestions_path = entry["run_dir"] / "analysis/supplemental_review_items.json"
        suggestions = read_json(suggestions_path).get("items", []) if suggestions_path.is_file() else []
        value = {"identity": self.public(entry), "checks": checks, "stats": stats,
                 "logs": [{"role": m.get("role"), "content": clean(m.get("content", "")), "timestamp": m.get("timestamp")} for m in messages],
                 "execution_logs": clean(raw.get("execution_logs", [])), "supplemental": clean(suggestions),
                 "configuration": {"extraction_model": meta.get("extraction_model"),
                                   "verification_model": (meta.get("verification_config") or {}).get("model"),
                                   "top_k": meta.get("top_k"), "max_retries": meta.get("max_retries"),
                                   "elapsed_seconds": meta.get("elapsed_seconds"), "api_usage": meta.get("api_usage"),
                                   "policy_name": (meta.get("policy") or {}).get("policy_name")},
                 "report_sha256": digest(entry["path"].read_bytes()),
                 "source_file": entry["path"].relative_to(ROOT).as_posix(),
                 "playback_mode": "HISTORY", "has_complete_progress_log": progress_path.is_file()}
        self._cache[key] = (stamp, value)
        return value

    def text(self, key):
        entry = self.entries[key]
        report = self.get(key)
        expected = {c["context_sha256"] for c in report["checks"] if c.get("context_sha256")}
        if not expected:
            expected = {e["context_sha256"] for e in report["execution_logs"] if e.get("context_sha256")}
        source = None
        if entry.get("web_task_id"):
            task_path = entry["run_dir"] / "task.json"
            if task_path.is_file():
                task = read_json(task_path)
                candidate = entry["run_dir"] / "input" / task["filename"]
                if candidate.resolve().is_relative_to((entry["run_dir"] / "input").resolve()):
                    source = candidate
        elif entry["sample"]:
            source = MEMBER / "contracts" / (entry["sample"] + ".txt")
        else:
            filename = Path(entry["filename"]).name
            candidate = CODE / "contracts" / filename
            if candidate.resolve().is_relative_to((CODE / "contracts").resolve()):
                source = candidate
        missing = {"available": False, "normalized_text": None, "raw_text": None, "raw_mapping_available": False,
                   "message": "未找到与报告哈希一致的合同原文；仅展示引文及记录偏移，不进行定位。", "quotes": {}}
        if source is None or not source.is_file() or source.suffix.lower() not in (".txt", ".pdf"):
            return missing
        content = source.read_bytes()
        try:
            raw = content.decode("utf-8") if source.suffix.lower() == ".txt" else None
            snapshot_path = entry["run_dir"] / "text_snapshot.json"
            snapshot = read_json(snapshot_path) if entry.get("web_task_id") and snapshot_path.is_file() else None
            if snapshot:
                if snapshot["raw_sha256"] != digest(content) or snapshot["normalized_sha256"] != digest(snapshot["normalized_text"].encode("utf-8")):
                    return missing
                normalized = snapshot["normalized_text"]
            else:
                normalized = ingestion_module().ingest(source).text
        except (ValueError, UnicodeError, OSError, KeyError, ingestion_module().IngestError):
            return missing
        normalized_hash = digest(normalized.encode("utf-8"))
        if expected != {normalized_hash}:
            return missing
        mapping = None
        if entry["sample"]:
            mapping_path = MEMBER / "results/data_preparation" / (entry["sample"] + "_offset_mapping.json")
            if mapping_path.is_file():
                candidate = read_json(mapping_path)
                normalizer = CODE / "tools/rag_tool/rag_core/pdf_ingest.py"
                if (candidate.get("raw_sha256") == digest(content) and candidate.get("normalized_sha256") == normalized_hash
                        and candidate.get("normalizer_sha256") == digest(normalizer.read_bytes())):
                    mapping = candidate
        quotes = {}
        for check in report["checks"]:
            pieces = []
            for i, answer in enumerate(check.get("predicted_answers", [])):
                ns = answer.get("answer_start")
                quote = answer.get("text", "")
                valid = type(ns) is int and ns >= 0 and bool(quote) and normalized[ns:ns + len(quote)] == quote
                record = {"index": i, "text": quote, "normalized_start": ns, "normalized_end": ns + len(quote) if type(ns) is int else None,
                          "position_matches": valid, "raw_start": None, "raw_end": None}
                if valid and mapping:
                    intervals = []
                    ne = ns + len(quote)
                    for run in mapping["runs"]:
                        a, b = run["normalized_start"], run["normalized_end"]
                        if ns < b and ne > a and run["kind"] != "insert":
                            if run["kind"] == "copy":
                                intervals.append((run["raw_start"] + max(ns, a) - a, run["raw_start"] + min(ne, b) - a))
                            else:
                                intervals.append((run["raw_start"], run["raw_end"]))
                    if intervals:
                        rs, re_ = min(x[0] for x in intervals), max(x[1] for x in intervals)
                        if ingestion_module().normalize_text(raw[rs:re_]).strip() == quote.strip():
                            record.update(raw_start=rs, raw_end=re_)
                pieces.append(record)
            quotes[check["qid"]] = pieces
        is_pdf = source.suffix.lower() == ".pdf"
        return {"available": True, "raw_text": raw if mapping else None, "normalized_text": normalized,
                "raw_mapping_available": bool(mapping), "raw_sha256": digest(content), "normalized_sha256": normalized_hash,
                "source_format": "PDF" if is_pdf else "TXT",
                "pages": snapshot.get("pages", []) if snapshot and is_pdf and snapshot.get("parse_method")=="pypdf" else [],
                "page_note": ("PDF解析文本坐标；页码仅按现有pypdf页映射显示，不是原PDF图像。" if snapshot and snapshot.get("parse_method")=="pypdf"
                              else "PDF回退解析未记录可靠页映射，不显示合成页码。") if is_pdf else "TXT无原始PDF页码；报告page=1为合成映射。",
                "coordinate_unit": "Unicode字符，从0起，右端不含", "quotes": quotes,
                "message": "规范化文本已与原报告哈希核对" + ("，原文映射已核对" if mapping else "；原文坐标映射未记录，使用规范化坐标")}

    def system(self):
        policy = read_json(CODE / "tools/rules/risk_rules.yaml")
        return {"catalog": self.clauses, "policy_name": policy.get("policy_name"),
                "mode_counts": dict(Counter(p["mode"] for p in policy["policies"].values())),
                "mode_names": MODE_NAMES, "reason_names": REASON_NAMES,
                "realtime_enabled": True, "model_api_calls_enabled": True,
                "task_groups": [g[0] for g in GROUPS], "default_top_k": 5, "default_max_retries": 2}
