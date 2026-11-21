"""输入与核验结论检查；不读取合同原文。"""

ITEM_FIELDS = (
    "question_id", "category", "category_answer", "predicted_answers",
    "evidence_checks", "processing_status", "verification_status", "coverage_status",
)


def issue(code, message, *fields):
    return {"code": code, "message": message, "fields": list(fields)}


def fact_issues(item, definition):
    """同时保留输入格式错误和上游无法确认原因。"""
    problems = []
    if not isinstance(item["question_id"], str) or not item["question_id"].strip():
        problems.append(issue("INPUT_INVALID", "任务标识须为非空字符串。", "question_id"))

    status_options = {
        "processing_status": ("COMPLETED", "INCOMPLETE", "ERROR"),
        "verification_status": ("PASSED", "FAILED", "UNCERTAIN"),
        "coverage_status": ("SUFFICIENT", "INSUFFICIENT", "NOT_APPLICABLE"),
    }
    for field, options in status_options.items():
        if not isinstance(item[field], str) or item[field] not in options:
            problems.append(issue("INPUT_INVALID", f"{field}取值无效。", field))
    if item["processing_status"] in ("INCOMPLETE", "ERROR"):
        problems.append(issue("UPSTREAM_INCOMPLETE", "上游抽取未完成或发生技术错误。", "processing_status"))
    if item["verification_status"] in ("FAILED", "UNCERTAIN"):
        problems.append(issue("EVIDENCE_NOT_VERIFIED", "整体证据核验未通过。", "verification_status"))

    value = item["category_answer"]
    if value is None:
        problems.append(issue("UPSTREAM_INCOMPLETE", "类别答案尚无法确认。", "category_answer"))
    elif (not isinstance(value, str) or not value.strip()
          or (definition["answer_type"] == "BOOLEAN" and value not in ("Yes", "No"))
          or (definition["answer_type"] != "BOOLEAN" and value.strip().casefold() in ("yes", "no", "unknown", "n/a"))):
        problems.append(issue("INPUT_INVALID", "类别答案与注册的答案类型不符。", "category_answer"))

    negative = definition["answer_type"] == "BOOLEAN" and value == "No"
    if negative and item["coverage_status"] != "SUFFICIENT":
        problems.append(issue("COVERAGE_INSUFFICIENT", "No需要充分的覆盖检查。", "coverage_status"))

    answers, checks = item["predicted_answers"], item["evidence_checks"]
    if not isinstance(answers, list) or not isinstance(checks, list):
        problems.append(issue("INPUT_INVALID", "引用和逐条核验结果须为列表。", "predicted_answers", "evidence_checks"))
        return problems
    if not answers and not negative:
        problems.append(issue("EVIDENCE_NOT_VERIFIED", "正向或实体答案缺少支持引用。", "predicted_answers"))

    mapped = {}
    for index, check in enumerate(checks):
        field = f"evidence_checks[{index}]"
        if not isinstance(check, dict):
            problems.append(issue("INPUT_INVALID", "核验结果须为对象。", field))
            continue
        target = check.get("answer_index")
        if type(target) is not int or not 0 <= target < len(answers):
            problems.append(issue("INPUT_INVALID", "核验结果指向无效引用索引。", field + ".answer_index"))
            continue
        if target in mapped:
            problems.append(issue("INPUT_INVALID", "每个引用只能有一项核验结果。", field + ".answer_index"))
        mapped[target] = check
        if check.get("position_valid") is not None and type(check.get("position_valid")) is not bool:
            problems.append(issue("INPUT_INVALID", "位置核验须为布尔值或null。", field + ".position_valid"))
        support = check.get("support_status")
        if not isinstance(support, str) or support not in ("SUPPORTED", "UNSUPPORTED", "UNKNOWN"):
            problems.append(issue("INPUT_INVALID", "语义核验状态无效。", field + ".support_status"))
        if check.get("reason") is not None and not isinstance(check["reason"], str):
            problems.append(issue("INPUT_INVALID", "核验原因须为字符串或null。", field + ".reason"))

    for index, answer in enumerate(answers):
        field = f"predicted_answers[{index}]"
        if (not isinstance(answer, dict) or not isinstance(answer.get("text"), str)
                or not answer["text"].strip() or type(answer.get("answer_start")) is not int
                or answer["answer_start"] < 0):
            problems.append(issue("INPUT_INVALID", "引用原文或起始位置格式无效。", field))
        check = mapped.get(index)
        if check is None or check.get("position_valid") is not True or check.get("support_status") != "SUPPORTED":
            problems.append(issue("EVIDENCE_NOT_VERIFIED", "引用缺少通过的位置或语义核验。", f"evidence_checks[{index}]"))
    return problems
