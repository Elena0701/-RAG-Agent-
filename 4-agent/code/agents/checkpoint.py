"""Atomic per-clause checkpoints; never persist credentials in run metadata."""
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str).encode()).hexdigest()


def run_signature(agent, file_path, tasks):
    root = Path(__file__).resolve().parents[1]
    sources = {}
    for folder in (root / "agents", root / "tools"):
        for path in sorted(folder.rglob("*")):
            if (path.is_file() and path.suffix in {".py", ".yaml", ".json"}
                    and "__pycache__" not in path.parts
                    and not any(part.startswith(".") for part in path.relative_to(root).parts)):
                sources[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    sources["main.py"] = hashlib.sha256((root / "main.py").read_bytes()).hexdigest()
    verifier = getattr(agent.rag_tool, "model_call", None)
    verifier_config = getattr(verifier, "config", None)
    return digest({
        "schema": 1, "file": str(file_path),
        "content": hashlib.sha256(file_path.read_bytes()).hexdigest(),
        "tasks": [{k: v for k, v in task.items() if k != "document_id"} for task in tasks],
        "model": agent.model,
        "extraction_url": str(getattr(agent.llm_client, "base_url", "")),
        "verifier_config": {name: getattr(verifier_config, name, None)
                            for name in ("model", "base_url", "max_tokens", "timeout_seconds")},
        "top_k": agent.top_k, "max_retries": agent.max_retries,
        "rag_config": {k: v for k, v in getattr(agent.rag_tool, "config", {}).items()
                       if not callable(v)},
        "rules": getattr(agent.rule_tool, "config", None),
        "registry": getattr(agent.rule_tool, "registry", None),
        "sources": sources,
    })


def save_checkpoint(path, signature, document, results, logs):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({
        "schema_version": 1, "signature": signature, "document": document,
        "checks": results, "execution_logs": logs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_checkpoint(path, signature, tasks):
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or data.get("signature") != signature):
        raise ValueError("断点与当前合同、任务、模型或代码/政策配置不一致，请重新运行")
    document = data.get("document")
    if (not isinstance(document, dict)
            or any(not isinstance(document.get(key), str) or not document[key]
                   for key in ("document_id", "file_path", "filename"))
            or not isinstance(data.get("execution_logs"), list)):
        raise ValueError("断点合同信息或日志无效")
    results = data.get("checks")
    expected = [t["question_id"] for t in tasks]
    if not isinstance(results, list) or len(results) > len(expected):
        raise ValueError("断点结果无效")
    for index, result in enumerate(results):
        if (not isinstance(result, dict) or result.get("question_id") != expected[index]
                or result.get("category") != tasks[index]["category"]
                or result.get("document_id") != data["document"]["document_id"]
                or result.get("next_action") not in {"ACCEPT", "ESCALATE"}):
            raise ValueError("断点任务顺序或完成状态无效")
    return data
