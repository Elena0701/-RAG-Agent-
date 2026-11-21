"""36类事实描述、政策判断及批量结果封装。"""

from copy import deepcopy
import json
from pathlib import Path
from string import Formatter

from .policy_checks import MODES, RISK_MODES, compare, policy_issues
from .validation import ITEM_FIELDS, fact_issues, issue


def load_config(path):
    """读取JSON或使用JSON语法的YAML配置。"""
    with Path(path).open(encoding="utf-8-sig") as stream:
        data = json.load(stream, parse_constant=_invalid_constant)
    if not isinstance(data, dict):
        raise ValueError("配置顶层须为对象。")
    return data


def _invalid_constant(value):
    raise ValueError(f"JSON中不支持{value}数值。")


class RuleTool:
    def __init__(self, config=None, registry=None):
        base = Path(__file__).parent
        self.config = deepcopy(load_config(base / "risk_rules.yaml") if config is None else config)
        registered = deepcopy(load_config(base / "category_registry.json") if registry is None else registry)
        self.registry = self._load_registry(registered)
        if not isinstance(self.config, dict) or not isinstance(self.config.get("policies"), dict):
            raise ValueError("配置须包含policies对象。")
        if not isinstance(self.config.get("sources"), dict):
            raise ValueError("配置须包含sources对象。")
        if set(self.config["policies"]) - set(self.registry):
            raise ValueError("政策包含未注册的类别。")
        requirements = self.config.get("processing")
        fixed = ("manual_review_on_uncertain", "negative_requires_sufficient_coverage",
                 "preserve_fact_when_disabled", "preserve_item_order")
        if not isinstance(requirements, dict) or any(requirements.get(key) is not True for key in fixed):
            raise ValueError("processing中的四项固定处理要求须均为true。")

    @staticmethod
    def _load_registry(data):
        entries = data.get("categories") if isinstance(data, dict) else None
        if not isinstance(entries, list) or len(entries) != 36:
            raise ValueError("类别注册表须包含36类。")
        registry, indices = {}, set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("类别定义须为对象。")
            name, index, kind = entry.get("category"), entry.get("cuad_index"), entry.get("answer_type")
            if (not isinstance(name, str) or not name.strip() or name in registry
                    or type(index) is not int or index not in range(6, 42) or index in indices
                    or kind not in ("BOOLEAN", "DURATION", "JURISDICTION")
                    or not isinstance(entry.get("label"), str) or not entry["label"].strip()):
                raise ValueError("类别名称、序号、类型或中文名称无效。")
            templates = entry.get("fact_templates")
            keys = ("present", "absent", "unknown") if kind == "BOOLEAN" else ("value", "unknown")
            if not isinstance(templates, dict) or any(not isinstance(templates.get(k), str) or not templates[k].strip() for k in keys):
                raise ValueError("类别描述模板缺失。")
            for key in keys:
                try:
                    fields = list(Formatter().parse(templates[key]))
                    if any(field is not None and (key != "value" or field != "value" or spec or conversion)
                           for _, field, spec, conversion in fields):
                        raise ValueError("描述模板只支持{value}占位符。")
                    templates[key].format(value="example")
                except (ValueError, KeyError, IndexError) as error:
                    raise ValueError("类别描述模板无效。") from error
            indices.add(index)
            registry[name] = entry
        return registry

    @property
    def supported_categories(self):
        return tuple(self.registry)

    def review_batch(self, document_id, items):
        """外层无效抛出ValueError；单项异常返回原顺序的异常结果。"""
        self._validate_document_id(document_id)
        if not isinstance(items, list) or not items:
            raise ValueError("items须为非空列表。")
        seen, results = set(), []
        for index, raw in enumerate(items):
            early = []
            if not isinstance(raw, dict):
                early.append(issue("INPUT_INVALID", "类别项须为对象。", "item"))
            else:
                category = raw.get("category")
                if isinstance(category, str) and category in self.registry:
                    if category in seen:
                        early.append(issue("DUPLICATE_CATEGORY", "本批次已包含该类别，保留首项。", "category"))
                    seen.add(category)
                if "document_id" in raw and raw["document_id"] != document_id:
                    early.append(issue("INPUT_INVALID", "类别项合同标识与批量合同不一致。", "document_id"))
            try:
                result = self._review_item(document_id, raw, early)
            except Exception as error:
                # 单项处理异常不覆盖其他类别；记录类型，避免把失败当作正常否定。
                result = self._error_result(raw, issue("PROCESSING_ERROR", f"本项处理失败：{type(error).__name__}。", "item"))
                result["document_id"] = document_id
            result.pop("document_id", None)
            result["item_index"] = index
            results.append(result)
        return {"document_id": document_id, "results": results}

    def review(self, document_id, question_id, category, category_answer, predicted_answers,
               evidence_checks, processing_status, verification_status, coverage_status):
        """单类别入口，返回包含document_id的完整结果。"""
        self._validate_document_id(document_id)
        item = dict(zip(ITEM_FIELDS, (question_id, category, category_answer, predicted_answers,
                                    evidence_checks, processing_status, verification_status, coverage_status)))
        return self._review_item(document_id, item)

    def evaluate(self, *args, **kwargs):
        """仅需要分级规则列表时使用；完整反馈应使用review或review_batch。"""
        return self.review(*args, **kwargs)["review_results"]

    @staticmethod
    def _validate_document_id(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("document_id须为非空字符串。")

    @staticmethod
    def _base_result(raw):
        raw = raw if isinstance(raw, dict) else {}
        return {**{key: deepcopy(raw.get(key)) for key in ITEM_FIELDS},
                "fact_status": "UNCERTAIN", "clause_description": "暂无法确认本类别事实。",
                "mode": None, "rule_execution_status": "ERROR", "review_results": [],
                "context_review_notes": [], "requires_manual_review": True, "issues": []}

    @classmethod
    def _error_result(cls, raw, problem):
        result = cls._base_result(raw)
        result["issues"] = [problem]
        return result

    def _review_item(self, document_id, raw, early=None):
        result = self._base_result(raw)
        result["document_id"] = document_id
        if early:
            result["issues"] = early
            return result
        if not isinstance(raw, dict):
            result["issues"] = [issue("INPUT_INVALID", "类别项须为对象。", "item")]
            return result
        missing = [key for key in ITEM_FIELDS if key not in raw]
        category = raw.get("category")
        if not isinstance(category, str) or category not in self.registry:
            result["issues"] = [issue("UNSUPPORTED_CATEGORY", "类别须使用注册表中的官方名称。", "category")]
            return result
        definition = self.registry[category]
        problems = fact_issues(result, definition)
        if missing:
            problems.insert(0, issue("INPUT_INVALID", "类别项缺少约定字段。", *missing))
        result["issues"] = problems
        templates = definition["fact_templates"]
        result["clause_description"] = templates["unknown"]
        if not problems:
            value = raw["category_answer"]
            key = ("present" if value == "Yes" else "absent") if definition["answer_type"] == "BOOLEAN" else "value"
            result["fact_status"] = "CONFIRMED"
            result["clause_description"] = templates[key].format(value=value)
            result["requires_manual_review"] = False
        # 格式错误为本项错误；正常的未知／上游失败仍保留所选模式及其处理状态。
        if any(p["code"] == "INPUT_INVALID" for p in problems):
            return result
        policies = self.config["policies"]
        if category not in policies:
            result.update(mode="INFORMATION_ONLY", rule_execution_status="NOT_CONFIGURED")
            return result
        policy = policies[category]
        if not isinstance(policy, dict):
            return self._policy_uncertain(result, {}, [issue("POLICY_INCOMPLETE", "本类政策须为对象。", "policies")])
        mode = policy.get("mode")
        result["mode"] = mode if isinstance(mode, str) and mode in MODES else None
        if policy.get("enabled") is False:
            result["rule_execution_status"] = "DISABLED"
            return result
        errors = policy_issues(policy, definition, self.registry, self.config["sources"])
        if errors:
            return self._policy_uncertain(result, policy, errors)
        if mode == "INFORMATION_ONLY":
            result["rule_execution_status"] = "INFORMATION_ONLY"
            return result
        result["rule_execution_status"] = "CONTEXT_REVIEW" if mode == "CONTEXT_REVIEW" else "EXECUTED"
        if problems:
            if mode in RISK_MODES:
                result["review_results"] = [self._risk_result(policy, "UNCERTAIN", "事实或上游核验尚无法确认。", result)]
            return result
        params = policy["parameters"]
        requirement_off = (mode == "REQUIRE_PRESENT" and params["require_present"] is False) or (
            mode == "FLAG_IF_CONDITION" and policy["condition_type"] == "ANSWER_IS_YES" and params["flag_if_present"] is False)
        if requirement_off:
            result["review_results"] = [self._risk_result(policy, "NOT_APPLICABLE", "当前政策明确关闭本项要求。", result)]
            return result
        if policy["applicable"] is None:
            return self._policy_uncertain(result, policy, [issue("POLICY_INCOMPLETE", "请明确本合同的政策适用性。", "applicable")])
        if policy["applicable"] is False:
            if mode in RISK_MODES:
                result["review_results"] = [self._risk_result(policy, "NOT_APPLICABLE", "本项政策明确不适用于本合同。", result)]
            return result
        if mode == "CONTEXT_REVIEW":
            if raw["category_answer"] == "Yes":
                manual = policy["manual_review_on_context"]
                result["context_review_notes"] = [{"rule_id": policy["rule_id"],
                    "related_categories": deepcopy(policy["parameters"]["related_categories"]),
                    "note": policy["review_note"], "evidence_indices": self._indices(result),
                    "requires_manual_review": manual}]
                result["requires_manual_review"] = manual
            return result
        status, reason, errors = compare(raw["category_answer"], policy)
        result["issues"].extend(errors)
        result["review_results"] = [self._risk_result(policy, status, reason, result)]
        result["requires_manual_review"] = result["review_results"][0]["requires_manual_review"]
        return result

    def _policy_uncertain(self, result, policy, problems):
        result["issues"].extend(problems)
        result["requires_manual_review"] = True
        if result["mode"] in RISK_MODES:
            result["rule_execution_status"] = "EXECUTED"
            result["review_results"] = [self._risk_result(policy, "UNCERTAIN", problems[0]["message"], result)]
        else:
            result["rule_execution_status"] = "CONTEXT_REVIEW" if result["mode"] == "CONTEXT_REVIEW" else "ERROR"
        return result

    @staticmethod
    def _indices(result):
        # 只有事实通过共用检查，引用才能作为确定判断的依据。
        return list(range(len(result["predicted_answers"]))) if result["fact_status"] == "CONFIRMED" else []

    def _risk_result(self, policy, status, reason, result):
        manual = status == "UNCERTAIN" or (status == "TRIGGERED" and policy.get("manual_review_on_trigger") is True)
        fields = list(dict.fromkeys(field for problem in result["issues"] for field in problem["fields"])) if status == "UNCERTAIN" else []
        recommendation = ("按缺项补查、补充政策或转人工复核。" if status == "UNCERTAIN"
                          else policy.get("review_note", "保留本项风险提示。") if status == "TRIGGERED"
                          else "保留本类别事实及核验结果。")
        return {"rule_id": policy.get("rule_id"), "status": status,
                "risk_level": policy.get("risk_level") if status == "TRIGGERED" else None,
                "reason": reason, "evidence_indices": self._indices(result), "missing_fields": fields,
                "requires_manual_review": manual, "recommendation": recommendation}
