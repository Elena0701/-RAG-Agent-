"""将已保存的审查事实格式化为终端和聊天框共用的中文报告。"""

import re
import textwrap
from datetime import datetime
from pathlib import Path

from agents.contract_review_agent import ContractReviewAgent


ICONS = {
    "Document Name": "📄", "Parties": "👥", "Agreement Date": "🗓️",
    "Effective Date": "🚀", "Expiration Date": "⌛", "Governing Law": "⚖️",
    "Renewal Term": "🔄", "Notice Period To Terminate Renewal": "📨",
    "Insurance": "🛡️", "Audit Rights": "🔍", "Termination For Convenience": "👤",
    "Most Favored Nation": "🤝",
    "Competitive Restriction Exception": "🔓",
    "Non-Compete": "🚧",
    "Exclusivity": "🔒",
    "No-Solicit Of Customers": "👥",
    "No-Solicit Of Employees": "🧑‍💼",
    "Non-Disparagement": "💬",
    "Rofr/Rofo/Rofn": "🥇",
    "Change Of Control": "🏢",
    "Anti-Assignment": "🔗",
    "Revenue/Profit Sharing": "💰",
    "Price Restrictions": "🏷️",
    "Minimum Commitment": "📦",
    "Volume Restriction": "📊",
    "Ip Ownership Assignment": "📝",
    "Joint Ip Ownership": "🧩",
    "License Grant": "🔑",
    "Non-Transferable License": "⛔",
    "Affiliate License-Licensor": "🏭",
    "Affiliate License-Licensee": "🏬",
    "Unlimited/All-You-Can-Eat-License": "♾️",
    "Irrevocable Or Perpetual License": "🔐",
    "Source Code Escrow": "💻",
    "Post-Termination Services": "🛠️",
    "Uncapped Liability": "🚨",
    "Cap On Liability": "🧱",
    "Liquidated Damages": "💸",
    "Warranty Duration": "🧰",
    "Covenant Not To Sue": "🕊️",
    "Third Party Beneficiary": "🎁",
}
MODE_LABELS = {
    "INFORMATION_ONLY": "事实展示",
    "REQUIRE_PRESENT": "必要条款检查",
    "FLAG_IF_CONDITION": "条件触发检查",
    "CONTEXT_REVIEW": "上下文复核",
}
RISK_LABELS = {"LOW": "低", "MEDIUM": "中", "HIGH": "高"}
VERIFICATION_LABELS = {"PASSED": "通过", "FAILED": "未通过", "UNCERTAIN": "无法确认"}
REPORT_LABELS = {"COMPLETED": "审查完成", "NEEDS_MANUAL_REVIEW": "待人工复核", "FAILED": "审查失败"}
TITLE_TYPES = {
    "services agreement": "服务协议",
    "service agreement": "服务协议",
    "non-disclosure agreement": "保密协议",
    "nondisclosure agreement": "保密协议",
    "confidentiality agreement": "保密协议",
    "employment agreement": "雇佣协议",
    "lease agreement": "租赁协议",
    "license agreement": "许可协议",
    "licensing agreement": "许可协议",
    "loan agreement": "借款协议",
    "credit agreement": "信贷协议",
    "supply agreement": "供应协议",
    "distribution agreement": "分销协议",
    "stock purchase agreement": "股份购买协议",
    "asset purchase agreement": "资产购买协议",
    "merger agreement": "合并协议",
}
PARTY_ROLES = {
    "Provider": "服务提供方",
    "Recipient": "服务接收方",
    "Disclosing Party": "披露方",
    "Receiving Party": "接收方",
    "Landlord": "出租方",
    "Tenant": "承租方",
    "Lessor": "出租方",
    "Lessee": "承租方",
    "Licensor": "许可方",
    "Licensee": "被许可方",
    "Employer": "雇主",
    "Employee": "雇员",
    "Seller": "卖方",
    "Buyer": "买方",
    "Purchaser": "买方",
    "Lender": "贷款方",
    "Borrower": "借款方",
    "Supplier": "供应方",
    "Distributor": "分销方",
}


def _text(value) -> str:
    if isinstance(value, list):
        return "、".join(_text(item) for item in value)
    return " ".join(str(value).split())


def _accepted(check: dict) -> bool:
    return check.get("next_action") == "ACCEPT"


def _manual_reason(check: dict) -> str:
    rules = [rule for rule in check.get("review_results", [])
             if rule.get("requires_manual_review")]
    triggered = [rule for rule in rules if rule.get("status") == "TRIGGERED"]
    if triggered:
        reasons = "；".join(f"{rule['rule_id']}：{_text(rule.get('reason', '规则要求人工复核'))}"
                           for rule in triggered)
        return f"转人工原因：命中业务规则，{reasons}"
    notes = [note["note"] for note in check.get("rule_review", {}).get("context_review_notes", [])
             if note.get("requires_manual_review") and note.get("note")]
    if notes:
        return f"转人工原因：需要结合相关条款复核。{_text(notes)}"
    issues = check.get("rule_review", {}).get("issues", [])
    policy_issues = [issue["message"] for issue in issues
                     if issue.get("code") == "POLICY_INCOMPLETE" and issue.get("message")]
    if policy_issues:
        return f"转人工原因：业务政策待确认。{_text(policy_issues)}"
    retries = check.get("retry_count", 0)
    prefix = f"已补查 {retries} 次，仍无法自动确认" if retries else "无法自动确认"
    reason = ContractReviewAgent.rule_manual_reason(check)
    reason = reason or check.get("extraction_reason") or check.get("reason") or "自动审查未完成"
    return f"转人工原因：{prefix}。{_text(reason)}"


def _answer(check: dict) -> str:
    answer = check.get("category_answer")
    if answer is None:
        return "抽取出错" if check.get("processing_status") == "ERROR" else "未能抽取到可确认的答案"
    value = _text(answer)
    if check.get("category") == "Governing Law" and isinstance(answer, str):
        if answer.strip().casefold() in {"israel", "state of israel", "the state of israel"}:
            value = "以色列"
    if check.get("category") in {"Agreement Date", "Effective Date", "Expiration Date"} and isinstance(answer, str):
        try:
            value = datetime.strptime(answer.strip(), "%B %d, %Y").date().isoformat()
        except ValueError:
            pass
    if check.get("verification_status") != "PASSED":
        return f"候选 {value}（未通过核验）"
    return value


def _parties(check: dict) -> list[str]:
    """仅按抽取答案中明确标注的角色分组，其他主体保留为未标注角色。"""
    answer = check.get("category_answer")
    if answer is None:
        return [f"   {_answer(check)}   ⚠️待人工复核"]
    values = answer if isinstance(answer, list) else [answer]
    groups: dict[str, list[str]] = {}
    for value in values:
        text = _text(value)
        role = "当事方（角色未标注）"
        # 只识别明确的括号角色标注，避免将公司名称里的角色词当成身份。
        annotation = re.search(r"\(([^)]*)\)", text)
        role_name = None
        if annotation:
            role_name = next((name for name in PARTY_ROLES
                              if re.search(r"\b" + re.escape(name) + r"\b", annotation[1], re.I)), None)
        if role_name:
            role = f"{PARTY_ROLES[role_name]}（{role_name}）"
        # 角色留在分组标题，国家和注册信息保留在 JSON 中。
        name = text[:annotation.start()].strip() if role_name else text
        name = re.split(r",\s*a company\b", name, maxsplit=1, flags=re.I)[0].strip()
        if re.fullmatch(r"\[\s*(?:\*\s*)+\]", name):
            name += "（原文已遮盖名称）"
        groups.setdefault(role, []).append(name)
    marker = "✅" if _accepted(check) else "⚠️待人工复核"
    return [f"   {role}：{'、'.join(names)} {marker}" for role, names in groups.items()]


def format_terminal_report(report: dict, report_path: str | Path) -> str:
    checks = report.get("checks", [])
    by_category = {check["category"]: check for check in checks}
    title_check = by_category.get("Document Name")
    title = _answer(title_check) if title_check else "本次未审查"
    contract_type = "未判定"
    if title_check and title_check.get("verification_status") == "PASSED":
        normalized_title = _text(title_check["category_answer"]).casefold()
        for suffix, label in TITLE_TYPES.items():
            if re.search(r"\b" + re.escape(suffix) + r"$", normalized_title):
                contract_type = f"{label}（根据合同标题归类）"
                break
    title_marker = ""
    if title_check:
        title_marker = " ✅" if _accepted(title_check) else "   ⚠️待人工复核"
    lines = [
        "━━━━━━━━ 合同审查报告 ━━━━━━━━", "",
        f"📄 合同名称：{title}{title_marker}",
    ]
    if title_check and not _accepted(title_check):
        lines.append(_manual_reason(title_check))
    lines.extend([f"📁 合同类型：{contract_type}", "", "👥 当事方构成"])
    party_check = by_category.get("Parties")
    lines.extend(_parties(party_check) if party_check else ["   本次未审查"])
    if party_check and not _accepted(party_check):
        lines.append(_manual_reason(party_check))
    lines.append("")
    for check in checks:
        qid = check["question_id"]
        if check["category"] in {"Document Name", "Parties"}:
            continue
        label = ContractReviewAgent.CATEGORY_LABELS.get(check["category"], check["category"])
        marker = "✅" if _accepted(check) else "⚠️待人工复核"
        spacing = " " if _accepted(check) else "   "
        line = f"{ICONS.get(check['category'], '📌')} {label}：{_answer(check)}{spacing}{marker}"
        levels = [rule.get("risk_level") for rule in check.get("review_results", [])
                  if rule.get("status") == "TRIGGERED"]
        risk = next((level for level in ("HIGH", "MEDIUM", "LOW") if level in levels), None)
        if risk:
            line += f"   风险：{RISK_LABELS[risk]}"
        lines.append(line)
        if not _accepted(check):
            lines.append(_manual_reason(check))
    lines.extend(["", f"📋 总体状态：{REPORT_LABELS.get(report['status'], report['status'])}"])
    if report["status"] == "FAILED":
        lines.append(f"❌ 失败原因：{_text(report.get('prepare_result', {}).get('reason', '预处理失败'))}")
    lines.extend(["", "━━━━ 证据溯源及审核意见 ━━━━", ""])
    answered = [check for check in checks if check.get("category_answer") is not None]
    if not answered:
        lines.append("本次没有可展示的答案或候选答案。")
    for check in answered:
        qid = check["question_id"]
        label = ContractReviewAgent.CATEGORY_LABELS.get(check["category"], check["category"])
        status = check.get("verification_status", "UNCERTAIN")
        action = check.get("next_action", "ESCALATE")
        lines.extend([
            f"{ICONS.get(check['category'], '📌')} {label}",
            f"   核验状态：{VERIFICATION_LABELS.get(status, status)}（{status}）",
            f"   处理结果：{'自动接收' if _accepted(check) else '待人工复核'}（{action}）",
        ])
        review = check.get("rule_review", {})
        if review.get("clause_description"):
            lines.append(f"事实描述：{_text(review['clause_description'])}")
        if review.get("mode") in MODE_LABELS:
            lines.append(f"审查模式：{MODE_LABELS[review['mode']]}")
        quotes = check.get("predicted_answers", [])
        if quotes:
            lines.append("   原文证据：")
            for index, quote in enumerate(quotes):
                lines.append(f"     [{index}] 字符起始偏移：{quote['answer_start']}")
                lines.extend(textwrap.wrap(quote["text"], width=88,
                                          initial_indent="         ", subsequent_indent="         "))
        else:
            basis = check.get("verification_basis")
            explanation = "已通过全文缺失核验" if basis == "FULL_CONTEXT_ABSENCE" else "候选 No 需经全文核验"
            if check.get("category_answer") != "No":
                explanation = "未提供原文证据"
            lines.append(f"   原文证据：无引文，{explanation}。")
        overall = check.get("overall_support") or {}
        reason = overall.get("reason")
        if not reason:
            diagnostic = check.get("reason") or check.get("extraction_reason") or "未执行整体语义核验"
            reason = f"未生成整体语义核验结论。{diagnostic}"
            if check.get("model_error"):
                reason += f"（{check['model_error']}）"
        lines.append(f"   核验结论：{_text(reason)}")
        rules = check.get("review_results", [])
        if rules:
            for rule in rules:
                state = {"TRIGGERED": "已触发", "NOT_TRIGGERED": "未触发",
                         "NOT_APPLICABLE": "未触发（不适用）",
                         "UNCERTAIN": "未触发（规则无法判断）"}.get(rule["status"], rule["status"])
                lines.extend([f"规则审核结论：{state} {rule['rule_id']}。",
                              _text(rule["reason"])])
        elif check["category"] not in ContractReviewAgent.RULE_CATEGORIES:
            lines.append("规则审核结论：未触发（本类别不执行规则）。")
        elif check.get("processing_status") != "COMPLETED" or status != "PASSED":
            lines.append("规则审核结论：未触发（抽取或证据核验未通过，规则未执行）。")
        else:
            execution = check.get("rule_review", {}).get("rule_execution_status")
            label = {"INFORMATION_ONLY": "仅作事实描述", "CONTEXT_REVIEW": "上下文复核",
                     "DISABLED": "规则未启用", "NOT_CONFIGURED": "规则未配置",
                     "ERROR": "规则处理异常"}.get(execution, "规则未配置或未启用")
            lines.append(f"规则审核结论：未触发（{label}）。")
        for note in check.get("rule_review", {}).get("context_review_notes", []):
            lines.append(f"上下文复核意见：{_text(note['note'])}")
        for issue in check.get("rule_review", {}).get("issues", []):
            lines.append(f"规则处理说明：{_text(issue['message'])}")
        lines.append("")
    manual = report.get("manual_review_items", [])
    accepted = sum(_accepted(check) for check in checks)
    lines.extend([
        "━━━━ 审查结束 ━━━━",
        f"📊 共审查 {len(checks)} 项，自动接收 {accepted} 项，待人工复核 {len(manual)} 项。",
    ])
    if manual:
        labels = "、".join(f"{item['question_id']} {ContractReviewAgent.CATEGORY_LABELS.get(item['category'], item['category'])}"
                          for item in manual)
        lines.append(textwrap.fill(f"👤 待人工复核：{labels}。", width=88, subsequent_indent="   "))
    lines.append(f"💾 报告已保存：{report_path}")
    return "\n".join(line.lstrip() for line in lines)
