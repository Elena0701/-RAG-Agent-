from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from uuid import uuid4
from pathlib import Path
from typing import Callable

from agents.contract_review_agent import ContractReviewAgent
from agents.terminal_report import format_terminal_report
from tools.rag_tool import RAGTool
from tools.rules import RuleTool, load_config


def build_llm_client():
    """
    输入: 环境变量 OPENAI_API_KEY、可选 OPENAI_BASE_URL
    输出: OpenAI兼容Chat Completions客户端。
    兼容第三方服务时须确认API协议和模型名称。
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("请先安装依赖: pip install openai") from exc

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("缺少环境变量 OPENAI_API_KEY")

    kwargs = {"api_key": api_key, "timeout": 60.0, "max_retries": 1}
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def build_agent(
    *,
    model: str,
    top_k: int = 5,
    max_retries: int = 2,
    output_dir: str = "outputs",
    progress: Callable[[str], None] | None = None,
    policy_path: str | Path | None = None,
) -> ContractReviewAgent:
    """
    输入: 模型名、检索参数和重试配置
    输出: 仅注入RAGTool与RuleTool两个业务工具的Agent实例。

    注意: RAGTool与RuleTool的内部实现由5号/3号负责。
    未确认的风险规则触发条件不在main中擅自配置。
    """
    rag_tool = RAGTool(config={"chunk_size": 800, "chunk_overlap": 120}, progress=progress)
    rule_tool = RuleTool(config=load_config(policy_path) if policy_path else None)
    return ContractReviewAgent(
        rag_tool=rag_tool,
        rule_tool=rule_tool,
        llm_client=build_llm_client(),
        model=model,
        max_retries=max_retries,
        top_k=top_k,
        output_dir=output_dir,
        progress=progress,
    )


def main() -> None:
    """
    命令行示例:
        python main.py data/raw/example.pdf --model your-model-name

    输出:
        outputs/reports/<document_id>.json
        终端打印运行状态、检查数量及报告路径。
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
        load_dotenv(Path(__file__).resolve().parent / "agents" / ".env")
    except ImportError:
        pass  # 也可直接通过系统环境变量配置

    parser = argparse.ArgumentParser(description="CUAD合同审查Agent")
    parser.add_argument("file_path", nargs="?", type=Path, help="待审查的合同文件（PDF 或 TXT）")
    parser.add_argument("--list-clauses", action="store_true", help="列出可选条款编号")
    parser.add_argument("--clauses", nargs="+", type=str.upper,
                        choices=[qid for qid, _, _ in ContractReviewAgent.CATEGORIES],
                        help="指定Q1–Q41条款编号，例如 --clauses Q3 Q8 Q16，默认审查全部")
    parser.add_argument("--model", default=os.getenv("LLM_MODEL"),
                        help="OpenAI兼容模型名，亦可设置LLM_MODEL")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--resume", type=Path, help="从指定 checkpoint.json 恢复，须使用相同合同、条款和配置")
    parser.add_argument("--debug", action="store_true", help="同时显示技术日志")
    parser.add_argument("--policy", type=Path, help="业务政策配置文件，默认使用内置演示政策")
    args = parser.parse_args()

    if args.list_clauses:
        for qid, category, _ in ContractReviewAgent.CATEGORIES:
            print(f"{qid}  {ContractReviewAgent.CLAUSE_LABELS[qid]}（{category}）")
        return
    if args.file_path is None:
        parser.error("请提供合同文件路径，或使用 --list-clauses 查看条款清单")
    if not args.model:
        parser.error("请传入 --model 或设置 LLM_MODEL")

    logging.basicConfig(level=logging.INFO if args.debug else logging.CRITICAL,
                        format="%(levelname)s %(message)s")

    clauses = "、".join(args.clauses) if args.clauses else "全部条款（Q1–Q41）"
    messages = [{
        "role": "user",
        "content": (
            f"审查合同：{args.file_path}\n"
            f"审查条款：{clauses}\n"
            f"抽取模型：{args.model}\n"
            f"首轮候选数：{args.top_k}，最大补查次数：{args.max_retries}\n"
            f"输出目录：{args.output_dir}"
            f"\n业务政策：{args.policy or '内置演示政策'}"
        ),
    }]

    journal = Path(args.output_dir) / "conversations" / f"{uuid4().hex}.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps(messages[0], ensure_ascii=False) + "\n", encoding="utf-8")

    def progress(message: str) -> None:
        print(message, file=sys.stderr, flush=True)
        entry = {"role": "assistant", "content": message}
        messages.append(entry)
        with journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    agent = build_agent(
        model=args.model,
        top_k=args.top_k,
        max_retries=args.max_retries,
        output_dir=args.output_dir,
        progress=progress,
        policy_path=args.policy,
    )
    try:
        report = agent.run(args.file_path, question_ids=args.clauses, resume=args.resume)
    except (FileNotFoundError, ValueError) as exc:
        parser.exit(2, f"❌ 无法开始审查：{exc}\n")
    report_path = agent.save_report(report)

    progress(format_terminal_report(report, report_path))

    conversation_path = report_path.with_name(f"{report_path.stem}.conversation.json")
    summary = json.dumps({
        "document_id": report["document_id"],
        "status": report["status"],
        "check_count": len(report["checks"]),
        "manual_review_count": len(report["manual_review_items"]),
        "report_path": str(report_path),
        "conversation_path": str(conversation_path),
        "checkpoint_path": str(agent.checkpoint_path),
        "journal_path": str(journal),
    }, ensure_ascii=False, indent=2)
    messages.append({"role": "assistant", "content": summary})
    with journal.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(messages[-1], ensure_ascii=False) + "\n")
    conversation_path.write_text(json.dumps({
        "document_id": report["document_id"],
        "messages": messages,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
