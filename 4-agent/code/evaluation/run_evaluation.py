"""Reproducible local CUAD sampling, live Agent runs, and deterministic scoring."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.contract_review_agent import ContractReviewAgent
from agents.terminal_report import format_terminal_report
from main import build_agent


QUESTION_IDS = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q16", "Q34", "Q39"]
CATEGORIES = [(qid, category) for qid, category, _ in ContractReviewAgent.CATEGORIES if qid in QUESTION_IDS]
BOOLEAN = {"Insurance", "Audit Rights", "Termination For Convenience"}


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def normalize(value, category):
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(sorted(normalize(part, category) for part in value))
    value = unicodedata.normalize("NFKC", str(value)).strip()
    if category in {"Agreement Date", "Effective Date", "Expiration Date"}:
        value = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", value, flags=re.I)
        for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                pass
    value = value.casefold()
    if category in {"Renewal Term", "Notice Period To Terminate Renewal"}:
        match = re.fullmatch(r"(?:successive\s+)?(\d+)\s+(years?|months?|days?)", value)
        if match:
            unit = match[2].rstrip("s")
            number = int(match[1])
            if unit == "year":
                number, unit = number * 12, "month"
            return f"{number} {unit}"
    if category == "Governing Law":
        value = re.sub(r"\b(?:the|state of|commonwealth of)\b", " ", value)
    return " ".join(re.findall(r"\w+", value, re.UNICODE))


def token_f1(gold, prediction):
    gold_tokens, prediction_tokens = Counter(gold.split()), Counter(prediction.split())
    if not gold_tokens or not prediction_tokens:
        return float(gold_tokens == prediction_tokens)
    overlap = sum((gold_tokens & prediction_tokens).values())
    return 2 * overlap / (sum(gold_tokens.values()) + sum(prediction_tokens.values()))


def score_records(samples, reports):
    records = []
    for sample in samples:
        report = reports.get(sample["filename"])
        if report is None:
            continue
        checks = {item["category"]: item for item in report["checks"]}
        for qid, category in CATEGORIES:
            check = checks.get(category, {})
            truth = sample["truth"][category]
            gold = truth["answer"]
            prediction = check.get("category_answer")
            verified = (check.get("processing_status") == "COMPLETED"
                        and check.get("verification_status") == "PASSED")
            gold_valid = bool(gold.strip()) and not re.search(r"\[\s*\]", gold)
            if category in BOOLEAN:
                gold_valid = gold in {"Yes", "No"}
            gold_normalized = normalize(gold, category)
            for track in ("raw", "verified"):
                value = prediction if track == "raw" or verified else None
                normalized = normalize(value, category)
                answer_available = bool(normalized)
                if category in BOOLEAN:
                    answer_available = value in {"Yes", "No"}
                quote_tokens = set(normalize(" ".join(truth["quotes"]), category).split())
                predicted_quotes = " ".join(item["text"] for item in check.get("predicted_answers", []))
                prediction_tokens = set(normalize(predicted_quotes, category).split()) if value is not None else set()
                evidence_f1 = None
                if quote_tokens:
                    evidence_f1 = 2 * len(quote_tokens & prediction_tokens) / (len(quote_tokens) + len(prediction_tokens))
                records.append({
                    "filename": sample["filename"], "question_id": qid, "category": category, "track": track,
                    "gold": gold, "prediction": value, "gold_available": gold_valid,
                    "answer_available": answer_available,
                    "exact_match": int(gold_normalized == normalized) if gold_valid else None,
                    "answer_token_f1": token_f1(gold_normalized, normalized) if gold_valid else None,
                    "evidence_token_set_f1": evidence_f1,
                    "processing_status": check.get("processing_status"),
                    "verification_status": check.get("verification_status"),
                    "next_action": check.get("next_action"),
                    "report_missing_check": category not in checks,
                    "technical_failure": (not check or check.get("processing_status") == "ERROR"
                                          or "MODEL_ERROR" in check.get("diagnostic_codes", [])),
                    "failure_kind": (
                        "FREE_MODEL_QUOTA" if "free model quota" in check.get("extraction_reason", "").lower()
                        else "API_TIMEOUT" if "timed out" in check.get("extraction_reason", "").lower()
                        else "MODEL_ERROR" if "MODEL_ERROR" in check.get("diagnostic_codes", [])
                        else "PROCESSING_ERROR" if check.get("processing_status") == "ERROR"
                        else "MISSING_CHECK" if not check else None
                    ),
                })
    return records


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def aggregate(records):
    metrics = []
    for qid, category in CATEGORIES:
        for track in ("raw", "verified"):
            group = [r for r in records if r["category"] == category and r["track"] == track]
            valid = [r for r in group if r["gold_available"]]
            answered = [r for r in valid if r["answer_available"]]
            evidence = [r["evidence_token_set_f1"] for r in group if r["evidence_token_set_f1"] is not None]
            row = {
                "question_id": qid, "category": category, "track": track, "n": len(group),
                "gold_available": len(valid), "gold_missing": len(group) - len(valid),
                "answered": len(answered), "abstentions": len(valid) - len(answered),
                "answer_coverage": ratio(len(answered), len(valid)),
                "exact_match": ratio(sum(r["exact_match"] for r in valid), len(valid)),
                "answer_token_f1": ratio(sum(r["answer_token_f1"] for r in valid), len(valid)),
                "answered_exact_match": ratio(sum(r["exact_match"] for r in answered), len(answered)),
                "evidence_token_set_f1": ratio(sum(evidence), len(evidence)),
                "evidence_gold_count": len(evidence),
            }
            if category in BOOLEAN:
                tp = sum(r["gold"] == "Yes" and r["prediction"] == "Yes" for r in valid)
                tn = sum(r["gold"] == "No" and r["prediction"] == "No" for r in valid)
                fp = sum(r["gold"] == "No" and r["prediction"] == "Yes" for r in valid)
                fn = sum(r["gold"] == "Yes" and r["prediction"] == "No" for r in valid)
                positive = sum(r["gold"] == "Yes" for r in valid)
                negative = len(valid) - positive
                positive_f1 = ratio(2 * tp, tp + fp + positive)
                negative_f1 = ratio(2 * tn, tn + fn + negative)
                available_f1 = [v for v in (positive_f1, negative_f1) if v is not None]
                row.update(tp=tp, tn=tn, fp=fp, fn=fn, gold_yes=positive, gold_no=negative,
                           abstain_yes=sum(r["gold"] == "Yes" and not r["answer_available"] for r in valid),
                           abstain_no=sum(r["gold"] == "No" and not r["answer_available"] for r in valid),
                           yes_precision=ratio(tp, tp + fp), yes_recall=ratio(tp, positive),
                           yes_f1=positive_f1, no_precision=ratio(tn, tn + fn),
                           no_recall=ratio(tn, negative), no_f1=negative_f1,
                           macro_f1=ratio(sum(available_f1), len(available_f1)))
            metrics.append(row)
    return metrics


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
                             for key, value in row.items()})


def evaluate(folder, manifest):
    reports = {}
    for index, sample in enumerate(manifest["samples"], 1):
        path = folder / f"sample_{index:02d}.result.json"
        if path.exists():
            reports[sample["filename"]] = json.loads(path.read_text(encoding="utf-8"))
    records = score_records(manifest["samples"], reports)
    metrics = aggregate(records)
    save_json(folder / "metrics.json", {"completed_samples": len(reports), "metrics": metrics})
    write_csv(folder / "metrics.csv", metrics)
    write_csv(folder / "predictions.csv", records)
    write_csv(folder / "metrics_without_technical_failures.csv",
              aggregate([row for row in records if not row["technical_failure"]]))
    verified = [row for row in records if row["track"] == "verified"]
    scored = [row for row in verified if row["gold_available"]]
    save_json(folder / "summary.json", {
        "sample_count": len(reports), "task_count": len(verified),
        "scored_answers": len(scored), "excluded_missing_gold": len(verified) - len(scored),
        "verified_exact_match": ratio(sum(row["exact_match"] for row in scored), len(scored)),
        "verified_answer_coverage": ratio(sum(row["answer_available"] for row in scored), len(scored)),
        "technical_failures": dict(Counter(row["failure_kind"] for row in verified if row["technical_failure"])),
        "samples": [
            {"filename": filename, "tasks": len(report["checks"]),
             "manual_review": len(report.get("manual_review_items", [])),
             "technical_failures": sum(row["technical_failure"] for row in verified if row["filename"] == filename)}
            for filename, report in reports.items()
        ],
        "limitation": "Small random sample of matched local contracts. Primary scores include technical abstentions; diagnostic CSV excludes final technical failures. Inspect failure counts before interpreting model quality.",
    })
    return len(reports)


def prepare(args):
    with args.gold.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    columns = {re.sub(r"\s+", "", key): key for key in rows[0]}
    local = {}
    for path in sorted((ROOT / "data").rglob("*.txt")):
        local.setdefault(path.stem, []).append(path)
    eligible = [row for row in rows if len(local.get(Path(row["Filename"]).stem, [])) == 1]
    selected = random.Random(args.seed).sample(sorted(eligible, key=lambda r: r["Filename"]), args.samples)
    samples = []
    for row in selected:
        path = local[Path(row["Filename"]).stem][0]
        truth = {}
        for _, category in CATEGORIES:
            answer_key = columns[re.sub(r"\s+", "", category + "-Answer")]
            quotes = ast.literal_eval(row[category])
            if not isinstance(quotes, list) or not all(isinstance(q, str) for q in quotes):
                raise ValueError(f"Invalid gold evidence: {row['Filename']} / {category}")
            truth[category] = {"answer": row[answer_key].strip(), "quotes": quotes}
        samples.append({"filename": row["Filename"], "file_path": str(path.resolve()),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "truth": truth})
    return {
        "created_at": datetime.now(timezone.utc).isoformat(), "seed": args.seed,
        "sampling": "Uniform random sample without replacement from filename-matched local TXT contracts.",
        "eligible_rows": len(eligible), "gold_path": str(args.gold),
        "gold_sha256": hashlib.sha256(args.gold.read_bytes()).hexdigest(),
        "question_ids": QUESTION_IDS, "samples": samples,
        "scoring": {
            "raw": "Final extraction answer, including unverified candidates.",
            "verified": "Answer only when processing is COMPLETED and verification is PASSED. Rule-triggered manual review does not invalidate a verified fact.",
            "missing_gold": "Blank canonical answers and [] date placeholders excluded from answer scores, counted separately; never inferred to mean No.",
            "binary": "Yes and No both scored; unknown is abstention, not No. Accuracy and recall include abstentions. Undefined ratios are null.",
            "text": "Normalized exact match and token multiset F1 against canonical Answer columns, not LLM semantic grading.",
            "normalization": "Unicode NFKC, lowercase, punctuation removal, whitespace; full-date formatting; integer years to months and successive prefix removal for simple durations; State of/Commonwealth of prefixes for jurisdiction.",
            "evidence": "Token-set F1 of all predicted quote text against all gold quote text; only nonempty gold evidence. This is not the official CUAD benchmark metric.",
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20261120)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (manifest["seed"] != args.seed or len(manifest["samples"]) != args.samples
                or manifest["gold_sha256"] != hashlib.sha256(args.gold.read_bytes()).hexdigest()):
            raise ValueError("Existing manifest differs from requested sample or gold data.")
    else:
        manifest = prepare(args)
        save_json(manifest_path, manifest)
    if args.prepare_only:
        for sample in manifest["samples"]:
            print(sample["filename"], flush=True)
        return
    if args.score_only:
        print("SCORED", evaluate(args.output, manifest), flush=True)
        return
    from dotenv import load_dotenv
    import os
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / "agents" / ".env")
    # Use the same provider configuration as the interactive CLI.
    manifest["extraction_base_url"] = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    manifest["model"] = os.environ["LLM_MODEL"]
    manifest["policy_sha256"] = hashlib.sha256((ROOT / "tools/rules/risk_rules.yaml").read_bytes()).hexdigest()
    save_json(manifest_path, manifest)
    for index, sample in enumerate(manifest["samples"], 1):
        result_path = args.output / f"sample_{index:02d}.result.json"
        if result_path.exists():
            print("RESUME_SKIP", index, flush=True)
            continue
        path = Path(sample["file_path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != sample["sha256"]:
            raise ValueError("Sample file changed since manifest creation.")
        print("SAMPLE_START", index, sample["filename"], flush=True)
        messages = [{"role": "user", "content": f"审查 {sample['filename']}，任务编号 {QUESTION_IDS}"}]

        def progress(message):
            messages.append({"role": "assistant", "content": message})
            if message.startswith(("━━━━ [第", "✅ Q", "👤 Q", "❌ 无法开始")):
                print(message, flush=True)

        agent = build_agent(model=manifest["model"], output_dir=args.output, progress=progress)
        manifest["verification_model"] = agent.rag_tool.model_status()
        save_json(manifest_path, manifest)
        try:
            report = agent.run(path, question_ids=QUESTION_IDS)
        except Exception as exc:
            # Never drop a failed sample or silently replace it with an easier contract.
            report = {"document_id": f"sample_{index:02d}", "filename": sample["filename"],
                      "status": "FAILED", "checks": [], "manual_review_items": [],
                      "failure_type": type(exc).__name__}
        report_path = agent.save_report(report)
        messages.append({"role": "assistant", "content": format_terminal_report(report, report_path)})
        save_json(report_path.with_name(report_path.stem + ".conversation.json"),
                  {"document_id": report["document_id"], "messages": messages})
        save_json(result_path, report)
        evaluate(args.output, manifest)
        print("SAMPLE_DONE", index, report["status"], len(report["checks"]), flush=True)
    print("BATCH_DONE", evaluate(args.output, manifest), str(args.output.resolve()), flush=True)


if __name__ == "__main__":
    main()
