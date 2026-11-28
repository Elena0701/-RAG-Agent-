# 分工与 GitHub 提交清单

> 核对日期：2026-11-29。原有 DDL 和成员交付表保留为历史计划，计划文件名不代表已经上传。实际文件以 [完整文件清单](文件清单.md) 和下节核对为准；此处只确认文件存在，不代替内容验收或实验复现。

## 最新文件与原计划的对应核对

- **成员 1：**已有 problem_and_data.md、sample_manifest_draft.csv、第一章来源与口径说明及 Word；计划中的最终 sample_manifest.csv 尚未出现，不能将草案标为最终样本清单。
- **成员 2：**已有 theory_and_design.md、references.md 和 agent_rag_review_flow.png。
- **成员 3：**规则代码实际位于 rules/，文字说明在 docs/，另有 README.md、environment.yml。原计划 risk_rules.md、rule_case.md、test_rules.py 未以这些名称提交。模块 README 说明测试仅保留本地，测试结论不等于仓库附有测试文件。
- **成员 4：**已有 agent_system.md、中文命名流程图、第四部分 Word，以及 code/ 下 41 类主程序、集成 RAG／规则工具、测试、配置模板和运行说明。原生执行日志与报告未随代码提交。
- **成员 5：**已有 retrieval.md、retrieval_case.md、可调用 RAG 模块、联调说明、测试、评测脚本和 results/*.json。41 类与旧版结果口径见 results/README.md，不可混引。
- **成员 6：**实际为“第六部分_基准实验设计.md”和“第六章 基准实验与结果分析.md”，对应方案和结果文字；本目录尚无计划中的 experiments/、results/metrics.csv、独立图表或逐条实验记录。成员 5 的检索结果不能直接视为成员 6 完整 Agent 对照实验的原始记录。
- **成员 7：**完整案例实际为 case.md，另有 failure_cases.md、limitations_and_governance.md；新增 web/ 实时网站与 web/showcase/dist/index.html 自包含展示版。原生 contracts/、annotations/、results/ 目录未提交，独立 HTML 内嵌的三个案例仍可直接演示。
- **成员 8：**当前有“金融人工智能小组汇报-第一组.pdf”；计划中的 pre_1107.pptx、pre_1107_notes.md、final_paper.docx/pdf、final_slides.pptx、submission_checklist.md 尚未出现。现有汇报 PDF 不代表全部最终整合材料已经交齐。

运行和下载说明见 [根目录 README](README.md)。展示版可双击查看既有案例；实时版下载整个仓库后，可在自己的电脑配置环境与模型服务运行，不依赖原作者电脑。

## 原定分工与时间安排（历史计划）

汇报时间：11 月 7 日下午。最终提交：11 月 30 日。  
所有成员须提交自己负责部分的文字说明及配套材料。标注为 **【合并用】** 的文件必须写成可直接纳入 PPT／论文的完整文字或结果；第 8 位负责汇总、统一格式和标注缺项，不代写他人内容。

## 完成顺序与并行关系

| 阶段 | DDL | 成员与任务 | 依赖 |
|---|---|---|---|
| 研究问题、数据和理论 | 11 月 2 日 | 1 完成研究问题、场景、CUAD 数据说明和样本范围；2 完成理论框架、研究假设和研究设计初稿 | 1、2 并行，随后共同确认研究问题与目标条款 |
| 规则、检索、实验方案 | 11 月 4 日 | 3 完成风险规则初稿；5 完成检索方案；6 完成实验方式、基准和指标方案 | 3、5、6 可并行；3、5 使用相同的目标条款范围 |
| 最小 Agent 与汇报案例 | 11 月 6 日 | 4 集成最小 Agent 流程；7 准备端到端案例和人工复核说明；8 整合 Pre PPT | 4 依赖 3、5 的接口；7 与 4 协作；8 汇总所有成员的阶段文件 |
| 实验、定稿和整合 | 11 月 24–29 日 | 1–7 更新最终文字和技术材料；8 完成论文、PPT 和提交检查 | 6 依赖 1 的样本、3 的规则、4/5 的系统输出；8 汇总各成员最终文件 |

所有日期均按当日中午 12:00 前提交，便于汇总与反馈。

## 成员交付清单

| 成员／保存目录 | 11 月 7 日前上传 | 11 月 30 日前上传 |
|---|---|---|
| **1. 金融问题与数据说明**<br>`1-problem-data/` | DDL：11 月 2 日。<br>**【合并用】**`problem_and_data.md`：研究问题、业务场景、业务价值、CUAD 来源/结构/标注、样本筛选方案、目标条款范围和数据局限。<br>**【合并用】**`sample_manifest_draft.csv`：拟用合同及筛选字段清单；不上传不必要的原始合同。 | DDL：11 月 24 日。<br>**【合并用】**更新 `problem_and_data.md`；提交 `sample_manifest.csv` 和最终筛选记录，明确实际样本量、字段和排除标准。 |
| **2. 理论框架与研究设计**<br>`2-theory-design/` | DDL：11 月 2 日。<br>**【合并用】**`theory_and_design.md`：Agent、RAG、规则核验与合同审查的理论关系、关键概念、研究假设和初步实验设计。<br>**【合并用】**`references.md`：论文及数据集引用。 | DDL：11 月 24 日。<br>**【合并用】**更新 `theory_and_design.md` 和 `references.md`，说明假设与实际实验、指标和结论的对应关系。 |
| **3. 风险规则与审核标准**<br>`3-risk-rules/` | DDL：11 月 4 日。<br>**【合并用】**`risk_rules.md`：3–5 类目标条款的审核标准、风险提示和人工复核触发条件。<br>`risk_rules.yaml`：规则初稿；`rule_case.md`：至少一个规则判断例子。 | DDL：11 月 24 日。<br>**【合并用】**更新 `risk_rules.md`；提交 `risk_rules.yaml`、`rule_engine.py`、`test_rules.py` 和规则测试结果。 |
| **4. Agent 程序搭建**<br>`4-agent/` | DDL：11 月 6 日。<br>**【合并用】**`agent_system.md`：Agent 状态、工作流、模块接口、输入输出、反馈/重试和人工复核节点。<br>**【合并用】**`agent_flow.png`：阶段流程图；可运行的最小流程和脱敏日志样例。 | DDL：11 月 26 日。<br>**【合并用】**更新 `agent_system.md`；提交可运行主程序、输入输出 schema、启动说明、执行日志及审核结果。 |
| **5. 检索与证据核验**<br>`5-retrieval-evidence/` | DDL：11 月 4 日。<br>**【合并用】**`retrieval.md`：合同分块、检索方法、证据定位和引用核验方案。<br>**【合并用】**`retrieval_case.md`：一份合同的条款检索、原文定位和证据引用示例。 | DDL：11 月 24 日。<br>**【合并用】**更新 `retrieval.md`；提交可调用的检索与引用核验模块，以及证据定位和核验结果。 |
| **6. 基准实验与结果分析**<br>`6-experiments/` | DDL：11 月 4 日。<br>**【合并用】**`evaluation_plan.md`：实验方式、比较基准、指标定义/公式、实验矩阵和压力或失败场景。汇报必须展示实验方式与评测指标，结果未完成时明确标为计划。 | DDL：11 月 26 日。<br>**【合并用】**`evaluation_results.md`：实际实验条件、结果解释、至少两个指标或场景及一个压力/失败场景。<br>`experiments/` 中脚本或 notebook；`results/metrics.csv` 和图表。 |
| **7. 完整案例与风险治理**<br>`7-case-governance/` | DDL：11 月 6 日。<br>**【合并用】**`case_01.md`：端到端案例草稿，包含输入、检索证据、Agent 输出和人工复核点。<br>**【合并用】**`limitations_and_governance.md` 初稿：潜在失败点、局限和治理方案。 | DDL：11 月 26 日。<br>**【合并用】**完成版 `case_01.md`、`failure_cases.md`、`limitations_and_governance.md`，以真实运行记录分析误报、漏报、证据不足和人工升级。 |
| **8. 流程图与汇报材料**<br>`8-slides-integration/` | DDL：11 月 6 日。<br>整合成员 1–7 已提交的 **【合并用】** 文件，提交 `pre_1107.pptx` 和 `pre_1107_notes.md`；检查研究问题、Agent 流程、运行案例、实验方式和评测指标都有展示。 | DDL：11 月 29 日。<br>整合成员 1–7 的最终 **【合并用】** 文件，提交 `final_paper.docx` 或 `final_paper.pdf`、`final_slides.pptx`、`submission_checklist.md`；核对引用、图表、格式和交付完整性。 |

## 汇报与最终整合要求

- 11 月 7 日汇报材料应展示研究问题、理论设计、CUAD 数据与样本、Agent 流程、一个运行样例、**实验方式和评测指标**、风险与人工复核。
- 11 月 30 日最终材料应包含 3–6 页正文论文、系统/流程图、完整运行样例，以及至少一个基准和两个以上指标或场景的评价表/实验图。
- 每位成员的文字说明应包含：本部分问题、方法/依据、结果或进度、可支持的结论、局限、参考来源。
- 不得把尚未运行的实验写成结果；不得把项目自行设定的规则写成法律结论。
