# 风险规则模块：运行与调用

本模块接收 4 号汇总的条款答案及 5 号核验结果，输出六类事实描述与风险规则判断，不执行检索、模型抽取或证据核验。每次调用处理一份合同的一个类别。

## 提交内容

```text
3-risk-rules/
├── README.md
├── environment.yml
├── .gitignore
├── docs/
│   ├── 规则文字化说明.md
│   ├── 政策配置说明.md
│   └── 规则模块输入输出接口说明.md
└── rules/
    ├── __init__.py
    ├── rule_tool.py
    ├── rule_engine.py
    └── risk_rules.yaml
```

这 10 个文件是本模块的交接内容。测试程序、测试数据、运行输出、个人笔记及其他准备文档仅本地保留，不随本分支提交。

- [文字规则](docs/规则文字化说明.md)：必要事实、触发条件、例外及信息不足处理。
- [政策配置](docs/政策配置说明.md)：修改阈值、存在性要求、开关、等级及复核要求。
- [输入输出接口](docs/规则模块输入输出接口说明.md)：九个输入字段、完整返回结构及 4 号接入方法。

## 环境

使用 Python 3.10 及以上，仅依赖标准库，无需模型 API 或完整 CUAD 数据集。建议创建 Python 3.12 的 FinAI 环境，在 `3-risk-rules` 目录执行：

```powershell
conda env create -f environment.yml
conda activate FinAI
```

已有 FinAI 环境时只需激活，不必重复创建。

## 可直接运行的示例

在 `3-risk-rules` 目录启动 `python`，粘贴以下代码。引用是模拟合同的完整文本，因此起始偏移设为 0；核验通过状态是模拟输入，不代表已运行真实 RAG。

```python
import json
from rules import RuleTool

item = {
    "document_id": "DEMO_CONTRACT",
    "question_id": "DEMO_CONTRACT__Governing Law",
    "category": "Governing Law",
    "category_answer": "Illinois",
    "predicted_answers": [{
        "text": "This Agreement is governed by the laws of Illinois.",
        "answer_start": 0,
    }],
    "evidence_checks": [{
        "answer_index": 0,
        "position_valid": True,
        "support_status": "SUPPORTED",
        "reason": "模拟上游核验通过",
    }],
    "processing_status": "COMPLETED",
    "verification_status": "PASSED",
    "coverage_status": "NOT_APPLICABLE",
}
check = RuleTool().review(**item)
print(json.dumps(check, ensure_ascii=False, indent=2))
```

默认允许清单为 California / New York，因此本例描述为“识别到适用法律答案为：Illinois。”，规则 LAW-001 触发 MEDIUM 提示并要求人工复核。这仅表示未满足本次演示清单，不表示 Illinois 法律本身风险较高。

## 六项政策

| 规则 | 配置判断 |
| --- | --- |
| LAW-001 | 明确的适用法律地区不在允许清单内时提示 |
| RENEWAL-001 | 明确单次续约期限严格超过月数上限时提示；整数年按 12 个月归一化 |
| NOTICE-001 | 明确通知天数严格超过配置上限时提示；不默认换算月、年或复杂窗口 |
| INS-001 | 政策要求保险义务条款，且充分检查后答案为 No 时提示 |
| AUDIT-001 | 政策要求审计权条款，且充分检查后答案为 No 时提示 |
| TERM-001 | 按政策对已核验存在的无因终止条款提示关注 |

`rules/risk_rules.yaml` 使用 JSON 语法书写，属于 YAML 子集。编辑时保留 JSON 结构。清单、阈值、要求和等级都是可修改的演示政策，不是行业通用标准或 CUAD 风险标签；修改后重新创建 RuleTool 实例生效。

## 4 号接入

推荐调用 `RuleTool.review(**item)`，返回字典可直接加入 `report["checks"]`。结果保留九个输入字段，并增加：

- `fact_status`：CONFIRMED／UNCERTAIN；基于上游结论和输入完整性，不是再次核验证据。
- `clause_description`：六类事实的中文描述；规则关闭仍输出，证据不足时描述为无法确认。
- `rule_execution_status`：EXECUTED／DISABLED／NOT_CONFIGURED。
- `review_results`：触发、未触发、不适用或无法确认，以及等级、理由和复核建议。
- `requires_manual_review`：事实无法确认或任一规则要求复核时为 true。

原 `evaluate()` 继续返回规则列表，兼容仅需要规则判断的调用。`review()` 只处理约定的六类，其他类别由 Agent 自行封装。

共识骨架中的 `level`、`missing_items` 对应本实现的 `risk_level`、`missing_fields`。Agent 需识别 UNCERTAIN 和顶层人工复核标志；确定触发的政策提示不应通过重复检索来消除。

## 验证范围

已在本地 FinAI（Python 3.12.16）通过 44 项测试，覆盖六类规则、阈值边界、证据不足、规则关闭、事实描述及结果封装。测试文件按交接范围不上传；上述调用示例可独立运行。

当前可供队友调用和联调，尚未完成与真实 Agent、RAG 的端到端验证。CUAD 人工答案不作为正式运行时输入。
