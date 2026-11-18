# CUAD 全类别规则模块扩展

本模块面向 IPO 尽调中的商业合同初筛，供受托律师及券商尽调团队使用。以发行人为分析对象，通过事实描述、证据追溯和风险提示，辅助确定优先复核事项。

工作分支：`feature/risk-rules-full-coverage`。

## 范围与流程

覆盖 CUAD 的 36 个非基础信息类别。合同名称、当事方及三个日期类别由 Agent 展示。

```text
一份合同选定的 n 类结构化结果
              ↓
内部逐类描述事实、执行政策
              ↓
一次返回 n 类结果及人工复核事项
```

四种模式为信息展示、条件触发关注、要求存在、关联复核。输入按层级组织：批量层共用 document_id，其余八字段按类别独立保存。风险等级使用 risk_level，表示预设政策下的初筛提示，辅助安排复核顺序。

## 目录

```text
3-risk-rules-expansion/
├── README.md
├── .gitignore
├── environment.yml
├── docs/
│   ├── 00推进流程.md
│   ├── 01类别与模式总表.md
│   ├── 02审查政策文字化说明.md
│   ├── 03统一配置与批量接口说明.md
│   ├── 04程序运行说明.md
│   └── 05自动化测试说明与结果.md
├── rules/
│   ├── category_registry.json  # 类别与事实描述模板
│   ├── risk_rules.yaml        # 四种模式的政策配置
│   ├── rule_engine.py         # 逐类处理及批量封装
│   ├── validation.py          # 输入与上游状态检查
│   ├── policy_checks.py       # 参数检查及条件比较
│   ├── rule_tool.py           # 导入入口
│   ├── __init__.py
│   └── __main__.py            # 文件调用入口
├── tests/          # 本地测试、数据与结果
└── local_notes/    # 本地样例核查及阅读记录
```

## 进度与成果

| 步骤 | 状态 | 成果 |
| --- | --- | --- |
| 1．类别与模式总表 | 已完成 | [36 类清单](docs/01类别与模式总表.md)：3 类地区／期限、33 类 Yes/No；训练样例及偏移核查记录本地保存 |
| 2．文字化审查政策 | 已完成 | [36 类政策](docs/02审查政策文字化说明.md)：统一事实门槛、逐类条件与复核方向 |
| 3．统一配置模板 | 已完成 | [配置及批量接口](docs/03统一配置与批量接口说明.md)：类别模板、模式、适用性、参数、等级、复核与来源 |
| 4．扩展程序 | 已完成 | [程序运行说明](docs/04程序运行说明.md)：36类四种模式、事实描述、逐项反馈及批量入口 |
| 5．补充测试 | 已完成 | [测试说明与结果](docs/05自动化测试说明与结果.md)：281个自动化用例、366个参数化子检查全部通过 |
| 6．对接与交付 | 待开展 | 真实上游联调、接口与运行说明 |

推进方法与完成标准见 [00推进流程](docs/00推进流程.md)。36类处理程序、批量入口及本地自动化测试已完成，下一步使用真实上游结果联调。

配置入口：[category_registry.json](rules/category_registry.json)、[risk_rules.yaml](rules/risk_rules.yaml)。其中保险、审计权及源代码托管的适用性待选定合同政策时明确；风险等级与数值是本次演示配置。

## 运行与调用

使用Python 3.10及以上，建议激活FinAI环境。在本目录执行文件调用：

```powershell
conda activate FinAI
python -m rules input.json --output result.json
```

代码中使用 `from rules import RuleTool`，通过 `RuleTool().review_batch(document_id, items)` 获取批量结果；单类别使用review，仅需风险列表时使用evaluate。完整可复制示例见 [程序运行说明](docs/04程序运行说明.md)。

本地测试入口为 `python -m tests.run_tests`，生成 `tests/results/test_report.json` 和 `tests/results/unittest.log`。测试程序和数据按材料管理约定仅本地保留。

## 材料管理

正式成果放在 docs/ 和 rules/；tests/、local_notes/、本地环境及缓存由 .gitignore 排除。样例核查记录保存所选训练片段的定位和上下文阅读结果。交付时核对实际文件范围，当前扩展材料尚未提交或推送。
