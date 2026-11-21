# 测试交接说明

本说明面向接手 Agent 集成测试的同学。入口为 `main.py`，先完成不联网回归，再进行单项在线冒烟和完整流程测试。这里验证功能与接口，不提供数据集抽样、指标计算或模型排名模块。

## 1. 交付范围

| 内容 | 位置 |
|---|---|
| 环境安装、配置和完整参数 | [README.md](README.md) |
| 快速运行和断点恢复 | [RUNNING.md](RUNNING.md) |
| 41 类编号及问句 | `agents/clause_catalog.py` / `python main.py --list-clauses` |
| 共用类别定义、排除条件 | `tools/clause_definitions.py` |
| 默认业务政策 | `tools/rules/risk_rules.yaml` |
| 配置模板 | `.env.example`、`tools/rag_tool/deepseek.local.env.example` |
| 不联网回归 | `tests/` |
| 人工编写的虚构合同 | `examples/smoke_contract.txt` |

测试所需真实 API Key、真实合同和历史报告不在仓库中，由测试同学在本地配置。虚构合同可用于联调，但不能用来证明真实合同的识别准确率。

## 2. 开始前核对

从仓库的 `4-agent/code` 目录执行所有命令：

```powershell
git rev-parse --short HEAD
python --version
python -m pip install -r requirements.txt
python -m pip check
python main.py --list-clauses
```

建议使用独立 Python 3.12 环境。安装说明见 README。记录 Git 提交号、Python 版本和依赖版本，反馈问题时一并提供。

在线测试前，按 README 复制并填写两个配置文件：

1. 根 `.env` 配置抽取 Key、Base URL、模型名。
2. `tools/rag_tool/deepseek.local.env` 配置核验 Key、Base URL、模型名。
3. 检查进程环境变量是否覆盖了文件配置，不要输出 Key。
4. 首次真实运行通常要下载 Embedding 模型；确保下载和模型 API 均可访问。

抽取服务接收候选片段，核验服务接收规范化全文。虚构样本没有真实合同内容；真实合同测试须在已获授权的范围内进行。

## 3. 第一轮：不联网回归

```powershell
python -m unittest discover -s tests
```

预期：测试结束显示 `OK`，不需要真实 API Key，不下载 Embedding 模型，也不向模型服务发送内容。测试数量随提交变化，以当前运行输出为准。

已覆盖的主要情形：

- 全部 41 类任务的编号、分发和共用定义。
- 原文偏移匹配、无效引文拒绝、候选 No 覆盖及全文核验协议。
- Q7 不将普通无因终止通知期当成退出续约通知期。
- 规则命中、政策不完整、上下文意见与转人工决策。
- 规则或核验异常保留成功抽取结果，后续重试复用前序结果。
- 定向取回覆盖检查指出的遗漏片段，并计入覆盖统计。
- 中断后的逐项恢复；合同、模型、政策或任务变化时拒绝旧断点。
- CLI 终端报告、最终 JSON 和对话输出。

回归失败应先修复或反馈，再进行在线测试，避免用真实 API 消耗定位本地接口问题。

## 4. 第二轮：在线冒烟

### 4.1 少量条款

```powershell
python main.py "examples\smoke_contract.txt" --clauses Q1 Q3 Q4 Q5 Q7 --max-retries 0 --output-dir outputs\handoff_smoke
```

这是在线调用，会消耗 API 额度。这里把补查次数设为 0，便于快速观察首轮结果；若需要验证补查行为，使用默认参数另开输出目录。

虚构合同中的已知事实：

| 编号 | 应识别的事实 | 原文位置 |
|---|---|---|
| Q1 | Sample Services Agreement，大小写可合理保留 | 标题和开头 |
| Q2 | Sample Provider Ltd. / Sample Recipient Ltd. | 开头 |
| Q3 | `01/15/26` | 开头 |
| Q4 | `02/01/26` | Section 1 |
| Q5 | `12/31/27` | Section 1 |
| Q6 | 1 year，保留 successive 等合理限定 | Section 2 |
| Q7 | **30 days**；不能使用 Section 3 的 60 days | Section 2 |
| Q8 | California / State of California | Section 5 |
| Q16 | Yes，任一方提前 60 天可无因终止 | Section 3 |
| Q19 | Yes，转让合同需要对方事先书面同意 | Section 8 |
| Q26 | No，明确不授予知识产权许可 | Section 9 |
| Q27 / Q29 | No，普通合同转让限制不能证明存在许可或关联企业许可 | Sections 8–9 |
| Q33 | No，仅返还保密文件且明确不提供过渡或继续服务 | Section 10 |
| Q34 | Yes，Recipient 有费用记录审计权 | Section 7 |
| Q39 | Yes，Provider 有保险维持义务 | Section 6 |

这张表是样本事实清单，不是保证在线模型必然返回的结果。若事实、核验或引用不一致，请按缺陷记录；不要为了达到预期而手动修改报告。未列条款按共用定义人工核对。

**答案正确和自动接收是两个检查点。** 默认政策可能使正确答案转人工，尤其是政策适用性未配置或命中关注条件时，不能将 ESCALATE 直接判定为抽取错误。

### 4.2 全部 41 项

```powershell
python main.py "examples\smoke_contract.txt" --output-dir outputs\handoff_full
```

预期检查：

- `checks` 有 41 项，Q1–Q41 唯一且按顺序排列。
- 所有任务最终为 ACCEPT 或 ESCALATE；报告不应保留尚待执行的 RETRY。
- 自动接收项数与人工项数之和为 41；人工列表与条款处理结果一致。
- 终端展示合同信息、条款答案、转人工原因、证据溯源及保存路径。
- 有答案的条款，包括未通过核验的候选答案，应展示证据详情或说明无引文。
- 缺失答案仍在条款总览和必要的人工列表中，不伪造原文证据。
- 最终 JSON、`.conversation.json`、逐项断点和过程 JSONL 均存在。

不要给真实调用固定“必须自动接收多少项”的要求：模型响应和业务政策都会影响数量。要核对具体原因和状态一致性。

## 5. 专项测试与验收点

| 测试 | 操作 | 通过标准 |
|---|---|---|
| 任务选择 | `--clauses Q3 Q5 Q17` | 仅审查这 3 项，按目录顺序，报告统计为 3 |
| TXT / PDF | 同一虚构文本分别用 TXT、含可选文本的 PDF 输入 | 均能准备并审查；PDF 的规范化偏移可不同 |
| 不支持的文件 | 使用 `.docx` 路径 | 清晰提示仅支持 PDF/TXT，不进入审查 |
| 不存在的文件 | 使用不存在的路径 | 清晰报错，不伪造成功结果 |
| 无效编号 | `--clauses Q42` | argparse 拒绝，不调用模型 |
| 引文溯源 | 对照规范化文本检查 `answer_start`、`text` | 逐字匹配；偏移从 0 开始，不能拿 PDF 字节位置比对 |
| 候选 No | 检查 No 条款状态和覆盖详情 | 不能因关键词零命中直接通过，须有语义核验支持 |
| 核验否决 | 运行现有回归及检查 FAILED 案例 | FAILED 不被覆盖不足改写为 UNCERTAIN |
| 补查 | 默认重试参数，观察发生覆盖不足的任务 | 优先补取遗漏片段；新片段进入检索历史和覆盖统计 |
| 异常保留 | 运行 `test_review_resilience.py` 的回归 | 规则/核验失败后候选答案仍在，异常阶段可追踪 |
| 政策差异 | 复制政策，用 `--policy` 指定；只修改理解明确的字段 | 抽取事实不因政策改变；规则与人工结论可改变 |
| 网络/额度错误 | 在专用测试配置中模拟错误，不修改共享密钥 | 不自动通过；报告区分错误阶段，最终按规则转人工 |

在线模型不保证必然触发覆盖不足或网络异常，因此这些分支优先用已有确定性回归检查。扫描 PDF 当前没有 OCR，不把扫描件解析失败作为已支持能力的通过案例。

## 6. 断点恢复实测

1. 启动上面的 41 项测试，等待至少一项结束并保存断点。
2. 用 Ctrl+C 中断。此时最终报告可能尚不存在，但 JSONL 与已保存断点应存在。
3. 找到终端打印的实际断点路径，在**相同原命令**后添加：

```powershell
python main.py "examples\smoke_contract.txt" --output-dir outputs\handoff_full --resume "outputs\handoff_full\checkpoints\实际文件名.checkpoint.json"
```

4. 检查显示的恢复数量；已完成条款不再次调用模型，未完成的那一项从头执行。
5. 最终报告包含恢复前后的全部任务，使用同一个 document_id。
6. 更换 `--model`、所选条款、合同内容或政策后，尝试恢复旧断点：应拒绝并说明不一致。

注意：已转人工的任务属于终态，也会跳过。若要重新审查它，另开一轮运行并选择相应 Q 编号。不要在原文件上改合同后期待沿用旧结果。

## 7. 结果阅读与故障定位

优先分别看以下字段：

1. 抽取：`processing_status`、`category_answer`、`predicted_answers`、`extraction_reason`。
2. 核验：`verification_status`、`coverage_status`、`coverage_detail`、`overall_support`、`evidence_checks`。
3. 规则：`review_results`、`rule_review.issues`、上下文意见。
4. 调度：`next_action`、`needs_manual_review`、`retry_count`。
5. 异常与历史：`stage_error`、`attempt_history`、`retrieval_history`。

`processing_status=COMPLETED` 只表示抽取完成。核验或规则异常时仍可能保留 COMPLETED，但 `stage_error` 非空且不能自动接收。`evidence_indices` 是本条款引文列表索引，不是字符偏移。

判断转人工原因时区分：候选没抽取到、引文不符、语义否决、覆盖不足、模型调用失败、政策缺失、业务规则要求人工。前三阶段成功但命中政策转人工，属于正常业务流程。

## 8. 缺陷反馈与交接产物

每个缺陷建议提交以下信息；反馈前移除密钥，真实合同与完整报告按团队授权范围共享：

```text
问题标题：
Git 提交号：
系统 / Python / 依赖版本：
抽取模型 / 核验模型 / Base URL（不含 Key）：
完整运行命令（不含凭据）：
合同：虚构样本或脱敏标识 / 文件哈希：
条款编号 / 类别：
复现步骤：
预期结果与原文依据：
实际结果：
processing_status / verification_status / coverage_status / next_action：
stage_error / diagnostic_codes：
复现频次：
附件：脱敏的条款 JSON、相关引文、必要的日志和运行配置：
```

建议交回：回归命令及结果、冒烟报告路径、41 项流程检查表、断点恢复记录、未解决缺陷及复现步骤。不要把离线回归通过写成真实合同准确率，也不要把正常政策转人工统计成模型失败。
