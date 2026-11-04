"""确定性规则判断；消费上游核验结果，不读取合同或调用模型。"""

import json
from copy import deepcopy
import math
import re
from pathlib import Path
from typing import Any


def load_config(path: str | Path) -> dict:
    """读取 JSON 语法的 YAML 配置，无第三方依赖。"""
    with Path(path).open(encoding="utf-8-sig") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError("规则配置必须是对象")
    return config


class RuleTool:
    """与共识文件同名的入口；每次处理一个合同类别。"""

    RULES = {
        "Governing Law": "LAW-001",
        "Renewal Term": "RENEWAL-001",
        "Notice Period To Terminate Renewal": "NOTICE-001",
        "Insurance": "INS-001",
        "Audit Rights": "AUDIT-001",
        "Termination For Convenience": "TERM-001",
    }

    BOOLEAN_CATEGORIES = {"Insurance", "Audit Rights", "Termination For Convenience"}

    def __init__(self, config: dict | None = None):
        self.config = load_config(Path(__file__).with_name("risk_rules.yaml")) if config is None else config

    def review(
        self,
        document_id: str,
        question_id: str,
        category: str,
        category_answer: Any,
        predicted_answers: list[dict],
        evidence_checks: list[dict],
        processing_status: str,
        verification_status: str,
        coverage_status: str,
    ) -> dict:
        """推荐给 Agent 的统一入口：九个输入原样保留，追加事实描述及规则结果。"""
        if category not in self.RULES:
            raise ValueError(f"review() 仅处理约定的六个 CUAD 类别：{category}")
        item = {
            "document_id": document_id, "question_id": question_id,
            "category": category, "category_answer": category_answer,
            "predicted_answers": predicted_answers, "evidence_checks": evidence_checks,
            "processing_status": processing_status, "verification_status": verification_status,
            "coverage_status": coverage_status,
        }
        problem = self._fact_problem(**item)
        labels = {
            "Governing Law": "适用法律答案", "Renewal Term": "续约期限答案",
            "Notice Period To Terminate Renewal": "退出续约通知期限答案",
            "Insurance": "保险义务条款", "Audit Rights": "审计权条款",
            "Termination For Convenience": "无因终止条款",
        }
        label = labels[category]
        if problem:
            target = f"是否存在{label}" if category in self.BOOLEAN_CATEGORIES else label
            description = f"暂无法确认{target}：{problem[0]}"
        elif category in self.BOOLEAN_CATEGORIES:
            description = f"存在{label}。" if category_answer == "Yes" else f"经本次充分检查，未发现{label}。"
        else:
            # 只复述已核验的答案，复杂答案不在此处强制规范化或增加推断。
            description = f"识别到{label}为：{category_answer}。"

        results = self.evaluate(**item)
        rules = self.config.get("rules", {})
        policy = rules.get(self.RULES[category], {}) if isinstance(rules, dict) else {}
        execution = "EXECUTED" if results else (
            "DISABLED" if isinstance(policy, dict) and policy.get("enabled") is False else "NOT_CONFIGURED"
        )
        return {
            **deepcopy(item),
            "fact_status": "UNCERTAIN" if problem else "CONFIRMED",
            "clause_description": description,
            "rule_execution_status": execution,
            "review_results": results,
            "requires_manual_review": bool(problem) or any(r["requires_manual_review"] for r in results),
        }

    @staticmethod
    def _result(rule_id, status, reason, *, level=None, indices=None, missing=None, manual=False):
        return {
            "rule_id": rule_id,
            "status": status,
            "risk_level": level,
            "reason": reason,
            "evidence_indices": indices or [],
            "missing_fields": missing or [],
            "requires_manual_review": manual,
            "recommendation": (
                "补齐所列信息或检查原文；由 Agent 决定补查或转人工。" if status == "UNCERTAIN"
                else "请人工确认该安排是否符合本次业务政策。" if status == "TRIGGERED" and manual
                else "记录本次政策提示。" if status == "TRIGGERED"
                else "本项政策要求不适用；仍保留条款识别与核验结果。" if status == "NOT_APPLICABLE"
                else "本项政策未触发；不代表合同整体无风险。"
            ),
        }

    def evaluate(
        self,
        document_id: str,
        question_id: str,
        category: str,
        category_answer: Any,
        predicted_answers: list[dict],
        evidence_checks: list[dict],
        processing_status: str,
        verification_status: str,
        coverage_status: str,
    ) -> list[dict]:
        """返回规则列表；未配置/未启用的类别返回 []，不能解释为无风险。

        输出沿用触发状态、risk_level、missing_fields；Agent 汇总时保留九项输入。
        """
        rule_id = self.RULES.get(category)
        rules = self.config.get("rules", {})
        policy = rules.get(rule_id, {}) if isinstance(rules, dict) else {}
        if not rule_id or policy == {}:
            return []

        def uncertain(reason, missing, indices=None):
            return [self._result(rule_id, "UNCERTAIN", reason, missing=missing, indices=indices, manual=True)]

        if not isinstance(policy, dict) or type(policy.get("enabled")) is not bool:
            return uncertain("规则开关配置无效。", [f"rules.{rule_id}.enabled"])
        if policy["enabled"] is False:
            return []
        if policy.get("category") != category:
            return uncertain("政策类别与规则路由不一致。", [f"rules.{rule_id}.category"])

        problem = self._fact_problem(
            document_id, question_id, category, category_answer,
            predicted_answers, evidence_checks, processing_status,
            verification_status, coverage_status,
        )
        if problem:
            return uncertain(*problem)
        indices = list(range(len(predicted_answers)))

        level = policy.get("risk_level")
        manual = policy.get("manual_review_on_trigger")
        if not isinstance(level, str) or level not in {"LOW", "MEDIUM", "HIGH"} or type(manual) is not bool:
            return uncertain("规则等级或人工复核策略配置缺失/无效。", [f"rules.{rule_id}"], indices)

        if rule_id == "LAW-001":
            allowed = self.config.get("allowed_governing_laws")
            if not isinstance(allowed, list) or not allowed or any(not isinstance(v, str) or not v.strip() for v in allowed):
                return uncertain("需要非空的适用法律允许清单。", ["allowed_governing_laws"], indices)
            aliases = self.config.get("law_aliases", {})
            if not isinstance(aliases, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in aliases.items()):
                return uncertain("名称别名配置无效。", ["law_aliases"], indices)
            value = self._law_name(category_answer, aliases)
            allowed_names = [self._law_name(v, aliases) for v in allowed]
            if any(v is None for v in allowed_names):
                return uncertain("允许清单需要明确的单一地区名称。", ["allowed_governing_laws"], indices)
            if value is None:
                return uncertain("答案不是可直接匹配的单一地区；不解析多法律或条件表达。", ["category_answer"], indices)
            triggered = value not in allowed_names
            reason = f"适用法律答案 {category_answer!r} {'不在' if triggered else '在'}配置的允许清单内。"
        elif rule_id == "RENEWAL-001":
            threshold = self.config.get("maximum_renewal_months")
            if type(threshold) is not int or threshold < 0:
                return uncertain("续约月数上限缺失或无效。", ["maximum_renewal_months"], indices)
            parsed = re.fullmatch(r"\s*(?:successive\s+)?(\d+)\s+(months?|years?)\s*", category_answer, re.I)
            if parsed is None:
                return uncertain("仅比较明确单次续约的整数月或整数年；不简化复杂期限。", ["category_answer"], indices)
            months = int(parsed.group(1)) * (12 if parsed.group(2).lower().startswith("year") else 1)
            triggered = months > threshold
            reason = f"单次续约期限 {category_answer} 按 {months} 个月比较，{'大于' if triggered else '不大于'}上限 {threshold} 个月。"
        elif rule_id == "NOTICE-001":
            threshold = self.config.get("notice_period_threshold_days")
            if type(threshold) not in {int, float} or not math.isfinite(threshold) or threshold < 0:
                return uncertain("通知天数阈值缺失或无效。", ["notice_period_threshold_days"], indices)
            basis = self.config.get("day_basis")
            if basis not in {"AS_WRITTEN_DAYS", "CALENDAR"}:
                return uncertain("缺少明确的天数比较口径。", ["day_basis"], indices)
            parsed = re.fullmatch(r"\s*(\d+)\s+(?:(calendar|business|working)\s+)?days?\s*", category_answer, re.I)
            if parsed is None:
                return uncertain("仅比较单一明确天数；月、年、区间及复杂条件不默认换算。", ["category_answer"], indices)
            if basis == "CALENDAR" and (parsed.group(2) or "").lower() != "calendar":
                return uncertain("政策要求日历日，但识别答案未明确为日历日。", ["category_answer"], indices)
            days = int(parsed.group(1))
            triggered = days > threshold
            reason = f"按 {basis} 口径，通知期限 {category_answer} {'大于' if triggered else '不大于'}阈值 {threshold} 天。"
        else:
            parameter, label = {
                "INS-001": ("require_insurance_clause", "保险义务"),
                "AUDIT-001": ("require_audit_clause", "审计权"),
                "TERM-001": ("flag_if_present", "无因终止"),
            }[rule_id]
            requirement = self.config.get(parameter)
            if type(requirement) is not bool:
                return uncertain("政策要求缺失或不是布尔值。", [parameter], indices)
            if requirement is False:
                return [self._result(rule_id, "NOT_APPLICABLE", f"当前政策未要求对{label}执行本项检查。", indices=indices)]
            if rule_id == "TERM-001":
                triggered = category_answer == "Yes"
                reason = ("已发现无因终止条款，命中关注政策；不据此判断其必然不利于本方。" if triggered
                          else "经充分检查，未发现无因终止条款，未命中存在性关注政策。")
            else:
                triggered = category_answer == "No"
                reason = (f"经充分检查，未发现本次政策要求的{label}条款。" if triggered
                          else f"存在{label}条款，满足本项存在性要求；不判断具体内容是否充分。")

        return [self._result(rule_id, "TRIGGERED" if triggered else "NOT_TRIGGERED", reason,
                             level=level if triggered else None, indices=indices, manual=manual if triggered else False)]

    def _fact_problem(
        self, document_id, question_id, category, category_answer,
        predicted_answers, evidence_checks, processing_status,
        verification_status, coverage_status,
    ):
        """仅检查输入完整性与上游结论，不读取原文或重新核验证据。"""
        missing = []
        if not document_id:
            missing.append("document_id")
        if not question_id:
            missing.append("question_id")
        if processing_status != "COMPLETED":
            missing.append("processing_status")
        if verification_status != "PASSED":
            missing.append("verification_status")
        if coverage_status not in {"SUFFICIENT", "INSUFFICIENT", "NOT_APPLICABLE"}:
            missing.append("coverage_status")
        if (not isinstance(category_answer, str) or not category_answer.strip()
                or (category in self.BOOLEAN_CATEGORIES and category_answer not in {"Yes", "No"})
                or (category not in self.BOOLEAN_CATEGORIES
                    and category_answer.strip().casefold() in {"yes", "no", "unknown", "n/a"})):
            missing.append("category_answer")
        if category_answer == "No" and coverage_status != "SUFFICIENT":
            missing.append("coverage_status")
        if missing:
            return ("识别、核验或覆盖状态不足，不能执行确定性判断。", list(dict.fromkeys(missing)))

        # 仅校验接口与核验结论的一致性，不重新校验原文位置或语义。
        negative = category in self.BOOLEAN_CATEGORIES and category_answer == "No"
        if not isinstance(predicted_answers, list) or (not predicted_answers and not negative):
            return ("本项规则需要已核验的正向原文证据。", ["predicted_answers"])
        if not isinstance(evidence_checks, list):
            return ("缺少逐条证据核验结果。", ["evidence_checks"])
        for index, answer in enumerate(predicted_answers):
            if (not isinstance(answer, dict) or not isinstance(answer.get("text"), str)
                    or not answer["text"].strip() or type(answer.get("answer_start")) is not int
                    or answer["answer_start"] < 0):
                return ("引用字段不完整或位置格式无效。", [f"predicted_answers[{index}]"])
            checks = [c for c in evidence_checks if isinstance(c, dict)
                      and type(c.get("answer_index")) is int and c["answer_index"] == index]
            if (len(checks) != 1 or checks[0].get("position_valid") is not True
                    or checks[0].get("support_status") != "SUPPORTED"):
                return ("引用缺少唯一且通过的核验结果。", [f"evidence_checks[{index}]"])
        if len(evidence_checks) != len(predicted_answers):
            return ("核验结果与引用列表不一一对应。", ["evidence_checks"])
        return None

    @staticmethod
    def _law_name(value, aliases):
        value = " ".join(value.strip().split()).casefold()
        alias_map = {" ".join(k.strip().split()).casefold(): " ".join(v.strip().split()).casefold()
                     for k, v in aliases.items()}
        value = alias_map.get(value, value)
        # 保守接受地区实体；复合答案交人工，不从整句话猜测地区。
        if (not re.fullmatch(r"[a-zÀ-ÿ][a-zÀ-ÿ .'-]*", value)
                or len(value.split()) > 6
                or re.search(r"\b(and|or|except|subject|unless|laws?|jurisdiction|court|provided)\b", value)):
            return None
        return value
