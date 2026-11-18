"""四种模式的配置检查和纯条件比较。"""

import math
import re

from .validation import issue

MODES = ("INFORMATION_ONLY", "FLAG_IF_CONDITION", "REQUIRE_PRESENT", "CONTEXT_REVIEW")
RISK_MODES = ("FLAG_IF_CONDITION", "REQUIRE_PRESENT")


def _name(value):
    return " ".join(value.split()).casefold()


def law_name(value, aliases):
    """仅做明确名称映射；拒绝复合法律条件。"""
    normalized = _name(value)
    normalized = {_name(k): _name(v) for k, v in aliases.items()}.get(normalized, normalized)
    if (not re.fullmatch(r"[a-zÀ-ÿ][a-zÀ-ÿ .'-]*", normalized)
            or len(normalized.split()) > 6
            or re.search(r"\b(and|or|except|subject|unless|laws?|jurisdiction|court|provided)\b", normalized)):
        return None
    return normalized


def policy_issues(policy, definition, categories, sources):
    """某一类配置问题以POLICY_INCOMPLETE反馈，不中断其他类别。"""
    fields = []
    mode, condition, params = policy.get("mode"), policy.get("condition_type"), policy.get("parameters")
    if not isinstance(policy.get("rule_id"), str) or not policy["rule_id"].strip():
        fields.append("rule_id")
    if type(policy.get("enabled")) is not bool:
        fields.append("enabled")
    if not isinstance(mode, str) or mode not in MODES:
        fields.append("mode")
    if "applicable" not in policy or (policy["applicable"] is not None and type(policy["applicable"]) is not bool):
        fields.append("applicable")
    for key in ("manual_review_on_trigger", "manual_review_on_context"):
        if type(policy.get(key)) is not bool:
            fields.append(key)
    for key in ("review_note", "applicability_note", "rationale"):
        if not isinstance(policy.get(key), str) or not policy[key].strip():
            fields.append(key)
    refs = policy.get("source_ids")
    if not isinstance(refs, list) or not refs or any(not isinstance(x, str) or x not in sources for x in refs):
        fields.append("source_ids")

    if mode in RISK_MODES:
        if not isinstance(policy.get("risk_level"), str) or policy["risk_level"] not in ("LOW", "MEDIUM", "HIGH"):
            fields.append("risk_level")
    elif policy.get("risk_level") is not None:
        fields.append("risk_level")

    answer_type = definition["answer_type"]
    if mode in ("REQUIRE_PRESENT", "CONTEXT_REVIEW") and answer_type != "BOOLEAN":
        fields.append("mode")
    allowed = {"BOOLEAN": ("ANSWER_IS_YES",), "DURATION": ("DURATION_MONTHS_GT", "NOTICE_DAYS_GT"),
               "JURISDICTION": ("LAW_NOT_IN_ALLOWLIST",)}
    if mode == "FLAG_IF_CONDITION":
        if not isinstance(condition, str) or condition not in allowed[answer_type]:
            fields.append("condition_type")
    elif condition is not None:
        fields.append("condition_type")
    if not isinstance(params, dict):
        fields.append("parameters")
        params = {}

    if mode == "REQUIRE_PRESENT" and type(params.get("require_present")) is not bool:
        fields.append("parameters.require_present")
    if mode == "CONTEXT_REVIEW":
        related = params.get("related_categories")
        if (not isinstance(related, list)
                or any(not isinstance(c, str) or c not in categories or c == definition["category"] for c in related)):
            fields.append("parameters.related_categories")
    if condition == "ANSWER_IS_YES" and type(params.get("flag_if_present")) is not bool:
        fields.append("parameters.flag_if_present")
    if condition == "DURATION_MONTHS_GT":
        limit = params.get("maximum_renewal_months")
        if type(limit) is not int or limit < 0:
            fields.append("parameters.maximum_renewal_months")
    if condition == "NOTICE_DAYS_GT":
        limit = params.get("notice_period_threshold_days")
        if type(limit) not in (int, float) or limit < 0 or (type(limit) is float and not math.isfinite(limit)):
            fields.append("parameters.notice_period_threshold_days")
        if params.get("day_basis") not in ("AS_WRITTEN_DAYS", "CALENDAR"):
            fields.append("parameters.day_basis")
    if condition == "LAW_NOT_IN_ALLOWLIST":
        allowed_laws, aliases = params.get("allowed_governing_laws"), params.get("law_aliases")
        aliases_valid = (isinstance(aliases, dict)
                         and all(isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip() for k, v in aliases.items()))
        if not aliases_valid:
            fields.append("parameters.law_aliases")
        if (not isinstance(allowed_laws, list) or not allowed_laws
                or any(not isinstance(v, str) or not v.strip() for v in allowed_laws)):
            fields.append("parameters.allowed_governing_laws")
        elif aliases_valid and any(law_name(v, aliases) is None for v in allowed_laws):
            fields.append("parameters.allowed_governing_laws")
    return [issue("POLICY_INCOMPLETE", "本类政策配置缺失或无效。", *dict.fromkeys(fields))] if fields else []


def compare(value, policy):
    """返回(status, reason, issues)，仅在事实及配置有效时调用。"""
    params = policy["parameters"]
    if policy["mode"] == "REQUIRE_PRESENT":
        if not params["require_present"]:
            return "NOT_APPLICABLE", "当前政策明确不要求本条款存在。", []
        triggered = value == "No"
        reason = "未发现本次政策要求的条款。" if triggered else "存在相关条款，满足本项存在性要求。"
    elif policy["condition_type"] == "ANSWER_IS_YES":
        if not params["flag_if_present"]:
            return "NOT_APPLICABLE", "当前政策关闭发现时关注要求。", []
        triggered = value == "Yes"
        reason = "已发现相关条款，命中关注政策。" if triggered else "经充分检查，未发现相关条款，未命中关注政策。"
    elif policy["condition_type"] == "LAW_NOT_IN_ALLOWLIST":
        canonical = law_name(value, params["law_aliases"])
        if canonical is None:
            return _not_comparable("适用法律答案不能可靠归一化为单一地区。")
        triggered = canonical not in [law_name(x, params["law_aliases"]) for x in params["allowed_governing_laws"]]
        reason = f"适用法律答案 {value!r} {'不在' if triggered else '在'}配置的允许清单内。"
    elif policy["condition_type"] == "DURATION_MONTHS_GT":
        match = re.fullmatch(r"\s*(?:successive\s+)?([0-9]{1,9})\s+(months?|years?)\s*", value, re.I)
        if match is None:
            return _not_comparable("仅比较明确单次续约的整数月或整数年。")
        months = int(match[1]) * (12 if match[2].lower().startswith("year") else 1)
        limit = params["maximum_renewal_months"]
        triggered = months > limit
        reason = f"单次续约期限 {value} 按 {months} 个月比较，{'大于' if triggered else '不大于'}上限 {limit} 个月。"
    else:
        match = re.fullmatch(r"\s*([0-9]{1,9})\s+(?:(calendar|business|working)\s+)?days?\s*", value, re.I)
        if match is None:
            return _not_comparable("仅比较明确单一天数，不默认换算月、年或复杂通知窗口。")
        basis = params["day_basis"]
        if basis == "CALENDAR" and (match[2] or "").lower() != "calendar":
            return _not_comparable("政策要求日历日，答案未明确日历日。")
        days, limit = int(match[1]), params["notice_period_threshold_days"]
        triggered = days > limit
        reason = f"按 {basis} 口径，通知期限 {value} {'大于' if triggered else '不大于'}阈值 {limit} 天。"
    return "TRIGGERED" if triggered else "NOT_TRIGGERED", reason, []


def _not_comparable(reason):
    return "UNCERTAIN", reason, [issue("VALUE_NOT_COMPARABLE", reason, "category_answer")]
