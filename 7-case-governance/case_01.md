# CASE-001：商业合同端到端审查案例

- 项目：基于 RAG 与规则核验的商业合同初审 Agent——面向投资并购尽职调查的辅助审查
- 上游依据：`1-problem-data/problem_and_data.md`、`2-theory-design/theory_and_design.md`、`4-agent/agent_system.md`、`5-retrieval-evidence/retrieval.md`、`5-retrieval-evidence/retrieval_case.md`、`6-experiments/第六部分_基准实验设计.md`、**`3-risk-rules/`（分支 `feature/risk-rules-1`：README、`docs/规则文字化说明.md`、`docs/政策配置说明.md`、`docs/规则模块输入输出接口说明.md`、`rules/risk_rules.yaml`、`rules/rule_engine.py`）**
- 配套文件：`failure_cases.md`、`limitations_and_governance.md`

> **本文件的写作纪律**  
> 案例中每一个数字、每一段原文、每一个状态值，都必须能追到上游文件或可复现命令。凡是尚未运行的环节，一律标注为【设计待运行】或【待集成】，**不把预期输出写成运行结果**。D 组（完整 Agent）的端到端结果，需待 4 号 `main.py` 与 3、5 号联调后再回填。

---

---

## 1 案例选择与适用边界

### 1.1 为什么选这份合同

| 选择条件                  | 本案例的满足情况                                                     |
| --------------------- | ------------------------------------------------------------ |
| 属于目标合同类型（服务/供货/许可/合作） | SERVICE AGREEMENT，服务合同，属尽调常见审查对象                             |
| 同时覆盖「基本信息类」与「规则候选类」任务 | 11 类中 9 类有 gold 片段，5 类无 gold 片段（可测「不乱报」）                     |
| 能暴露真实失效模式，而非只演示成功路径   | 条款标题未命中（走字符切块兜底）、Notice Period 无 gold 但与 Renewal 同块，两处均可作为反例 |
| 可复现                   | 有 `document_id`、冻结文本哈希、块数与块 ID，任何人可回到同一份原文                   |

### 1.2 本案例能说明什么、不能说明什么

**能说明**

1. 11 类任务可以在同一份冻结文本上跑完，且所有偏移可直接切片复核。
2. 位置核验能拦下 5 个字符的偏移误差，并在拦截后**不调用**语义核验。
3. 「没检索到」与「不存在」被区分开：`No` 结论必须过覆盖检查，且该检查在规则模块里是硬前置。
4. 同一段原文可以回答「续约期限」，但不能顺带回答「退出续约的通知期」——这是本项目最容易出错的地方。
5. 规则模块能对已核验的条款给出确定结论（如 `RENEWAL-001 TRIGGERED / LOW`），并把「事实确认」与「政策判断」分成两个字段输出。

**不能说明**

1. **不是测试集成绩。** 本例 9/9 覆盖只是单份合同；全量 510 份合同的 span R@5 是 0.713（源：`retrieval.md` §8）。
2. **不是语义准确率。** 语义核验的 `SUPPORTED` 分支目前由桩函数给出，真实模型结论与人工判断都没有独立标注（源：`retrieval_case.md` §6）。
3. **不是端到端的规则效果。** §4.6.3 的规则输出是真实的，但输入是设计值；真实抽取尚未运行，4 号与 3、5 号也未联调。规则模块的 44 项测试只在 3 号本地通过，测试文件未上传。
4. **不代表规则判断等于法律结论。** 六条规则背后的阈值与清单是演示政策，「触发」只表示不符合本次内部政策。
5. **不代表长合同、扫描件、中文合同。** 见 `limitations_and_governance.md` §2 L1–L3。

### 1.3 运行状态标记

| 标记      | 含义                           | 本案例中出现在                       |
| ------- | ---------------------------- | ----------------------------- |
| 【实际运行】  | 已执行，有日志或可复现输出支持              | 合同准备、检索、位置核验、覆盖检查             |
| 【模块级实跑】 | 单个模块独立执行有真实输出，但尚未与上下游联调      | 规则核验（3 号 `RuleTool.review()`） |
| 【桩运行】   | 流程已通，但模型调用由确定性桩替代，结论不可作为效果证据 | 语义核验的 `SUPPORTED` 分支          |
| 【设计待运行】 | 方案与接口已定，尚未执行                 | LLM 抽取、Agent 决策链              |
| 【待集成】   | 对应模块尚未接入 Agent               | 4 号 `main.py` 端到端             |

---

## 2 案例基本信息

| 项目           | 内容                                                                                                                                 |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| 案例编号         | CASE-001                                                                                                                           |
| document_id  | `RISEEDUCATIONCAYMANLTD_04_17_2020-EX-4.23-SERVICE AGREEMENT`                                                                      |
| 数据来源         | CUAD v1 官方 `CUADv1.json`（训练侧），标注仅在评价阶段读取                                                                                           |
| 样本归属         | **不在** 1 号 `sample_manifest_draft.csv` 的 20 份拟用样本内；本案例是 manifest 之外的一份 train 侧样本，仅作流程演示，**不进入 6 号的评价集**（核查过程见 `SAMPLE_LINEAGE.md`） |
| 原文长度         | 16,372 个 Unicode 字符                                                                                                                |
| 冻结文本 SHA-256 | `4d9af82e13bc95c4459e66c7d19439753237bc89e6e4bf10819aedcc4018534f`                                                                 |
| 分块配置         | 800 字符 / 重叠 120 字符 → 36 块                                                                                                          |
| 分块策略实际命中     | **条款标题未命中 0 处，走字符切块兜底**（条款级切块仅在 82% 的 CUAD 合同上生效）                                                                                  |
| 检索方式         | 合同内 BM25，`top_k=5`，显式传 `category`                                                                                                  |
| 规则模块         | 3 号 `RuleTool.review()`；配置 `risk_rules.yaml`（6 条规则全部 `enabled=true`）                                                               |
| 所用政策版本       | 允许法律清单 `["California","New York"]`；续约上限 `12` 个月；通知阈值 `60` 天、口径 `AS_WRITTEN_DAYS`；保险/审计要求存在；无因终止要求关注                                |
| 审查立场         | 潜在投资方/收购方视角，审查目标企业已签署合同（沿用 1 号设定的业务场景）                                                                                             |
| 案例目的         | 验证条款识别、检索定位、证据核验、规则核验、风险提示与证据追溯的完整链路，并暴露失效点                                                                                        |

> 说明 1：CUAD 的人工标注用于确定目标条款及其原文位置，**不代表已有风险等级**。风险等级只能来自 3 号的审核政策。  
> 说明 2：本案例的 `document_id` 正是 5 号 `retrieval_case.md` 使用的同一份合同，因此 §4.3 的检索结果可与该文件逐格对照，无需重新跑数。  
> 说明 3：规则结论会随政策参数变化。本文所有规则结果均绑定上表「所用政策版本」，**换参数后结论失效**，报告里必须同时记录配置值（3 号要求「将结果与所用配置一起保存」）。  
> 说明 4：本案例合同**不是** 1 号 `sample_manifest_draft.csv` 中的样本。该 manifest 是按「控制权变更 / 转让限制 / 无因终止 / 责任上限 / 责任无上限」5 类选的 20 份合同，与本案例的 11 类任务只有「无因终止（Q11）」一类重叠；本案例取自 5 号 `retrieval_case.md` 的单合同演示。因此论文中必须分开表述：**案例样本（1 份，演示用，不进评价集）** 与 **实验样本（1 号清单，评价用）** 是两批数据。详见 `SAMPLE_LINEAGE.md`。

---

## 3 任务设置：11 类审查任务

任务清单由 4 号 `ContractReviewAgent` 在准备阶段一次性生成，全部共享同一份合同索引。

| 任务 ID | 类别                                 | 中文      | 进规则候选 | 本案例检索实况（源：`retrieval_case.md` §2）          |
| ----- | ---------------------------------- | ------- | ----- | ------------------------------------------ |
| Q1    | Document Name                      | 合同名称    | 否     | gold=1，covered@5=1/1，top-1 `C6155`（7.46）   |
| Q2    | Parties                            | 签约方     | 否     | gold=4，covered@5=4/4，top-1 `C8944`（6.68）   |
| Q3    | Agreement Date                     | 签署日期    | 否     | gold=1，covered@5=1/1，top-1 `C14143`（10.21） |
| Q4    | Effective Date                     | 生效日期    | 否     | gold=1，covered@5=1/1，top-1 `C13752`（12.82） |
| Q5    | Expiration Date                    | 到期日期    | 否     | gold=1，covered@5=1/1，top-1 `C13242`（10.42） |
| Q6    | Governing Law                      | 适用法律    | 是     | **gold=0**，top-1 `C12365`（6.75）            |
| Q7    | Renewal Term                       | 续约期限    | 是     | gold=1，covered@5=1/1，top-1 `C13242`（10.41） |
| Q8    | Notice Period To Terminate Renewal | 退出续约通知期 | 是     | **gold=0**，top-1 `C13242`（13.37）——与 Q7 同块  |
| Q9    | Insurance                          | 保险义务    | 是     | **gold=0**，top-1 `C7922`（5.24）             |
| Q10   | Audit Rights                       | 审计权     | 是     | **gold=0**，top-1 `C6558`（5.43）             |
| Q11   | Termination For Convenience        | 无因终止    | 是     | **gold=0**，top-1 `C11116`（8.26）            |

**读表要点（写进论文 §5 的一段话）：**

- 9 个 gold 片段被 top-5 全部覆盖（9/9）。但这只是单份合同，**不能当作召回率**。
- Q6、Q8、Q9、Q10、Q11 五类 gold=0，意味着这份合同没有这类条款的人工标注。对这五类，**不能计算召回**，只能看两件事：检索是否给了可读候选，以及系统会不会把邻近代言内容当成该类条款报出来。
- **Q7 与 Q8 的 top-1 是同一个块 `C13242`**，这是本案例最有价值的一处细节：同一个块同时是「续约期限」的最高分候选与「退出续约通知期」的最高分候选。若不看类别语义，模型很容易把「续约五年」顺手写成「需提前五年通知」。这正是 2 号 §一强调的「‘每次续约一年’与‘退出续约须提前九十天通知’回答的是两个不同问题」。
- **规则侧现状**：Q6–Q11 六类都已配置并接入规则程序（`LAW-001 / RENEWAL-001 / NOTICE-001 / INS-001 / AUDIT-001 / TERM-001`），模块可独立运行；但本案例目前**只有 Q7 拿到真实规则结论**（`RENEWAL-001 TRIGGERED / LOW`），其余五类要看抽取结果，而抽取尚未运行。不要把「规则已配置」写成「六类都已评估」。

---

## 4 端到端执行过程

链路（与 4 号 §4.1 主流程图一致）：

```
prepare → 任务规划(11类) → retrieve → extract → verify → 规则核验 → decide → 汇总/报告
                              ↑                    |
                              └──── RETRY（改写 query，≤2 次）────┘
                                                   |
                                              ESCALATE → 人工复核清单
```

### 4.1 S0 合同准备 `RAGTool.prepare()`　【实际运行】

| 记录项  | 实际值                                                                                               |
| ---- | ------------------------------------------------------------------------------------------------- |
| 输入   | `document_id` + 文件路径                                                                              |
| 输出   | `status=SUCCESS`，冻结文本 16,372 字符，36 块，BM25 索引建立完成                                                  |
| 冻结哈希 | `4d9af82e13bc95c4459e66c7d19439753237bc89e6e4bf10819aedcc4018534f`                                |
| 归一化  | `\r\n→\n`、NBSP→空格、去零宽字符、去行尾空白、压缩空行，**只做一次且不可关闭**                                                  |
| 耗时   | 同级实测参考：38,671 字符 / 80 块的合同 prepare 约 7 ms（源：`retrieval.md` §5）                                    |
| 异常   | 本案例未出现。若为扫描件或加密字体 PDF，应返回 `FAILED`（`PDF_TEXT_EMPTY` / `PDF_TEXT_UNUSABLE`）并**停止自动审查**，不得解释为「没有风险」 |

**为什么这一步要单列：** 冻结哈希是后面所有偏移的基准。一旦上游再次改写文本，`context_sha256` 变化，4 号手里的 `answer_start` 立即全部失效。这是设计上的硬约束，也是本案例可复现的前提。

### 4.2 S1 任务规划　【检索任务配置已运行；Agent 内部规划待核验】

生成 §3 的 11 项任务，每项携带 `question_id`、`category`、`question`、`top_k=5`，各自独立维护重试次数与检索历史。

### 4.3 S2 检索 `RAGTool.retrieve()`　【实际运行】

**调用方式（关键）：**

```python
rag.retrieve(document_id="RISEEDUCATIONCAYMANLTD_...SERVICE AGREEMENT",
             query="What is the renewal term?",
             top_k=5,
             category="Renewal Term")     # 显式传 category
```

| 记录项                 | 实际值                                                                |
| ------------------- | ------------------------------------------------------------------ |
| `query_source`      | `explicit`（调用方显式传了 `category`）                                     |
| `resolved_category` | `Renewal Term`                                                     |
| 返回块                 | `C13242`，`start=13242`，`end=13872`，`score=10.41`，`rank=1`，`page=1` |
| 检索质量                | 该块覆盖了合同第 13 条的续约约定，gold 片段 1/1 被覆盖                                 |

**必须写进案例的一个对照：** 5 号实测显示，若问句与 `CATEGORIES` 模板不一致且未显式传 `category`，span R@5 会从 0.713 掉到 0.307（源：`retrieval.md` §4、§6）。也就是说，**同一个检索模块，调用方式不同，召回差一倍以上**。本案例显式传 `category`，属于最优路径；这一条不是细节，而是局限（见 `limitations_and_governance.md` L3）。


**检索输入的口径澄清：** 本项目的 RAG 检索的是**当前合同自身**的片段，用于给模型提供原文依据；审核政策（阈值、允许地区清单、存在性要求）由 3 号的规则文件提供，**不是检索出来的**。法条类外部知识库当前未接入，凡涉及法律效力的判断一律标注「未评估」。

### 4.4 S3 抽取 `LLM.extract()`　【设计待运行】

| 记录项  | 设计值                                                                                  |
| ---- | ------------------------------------------------------------------------------------ |
| 输入   | 当前任务 + `C13242` 等候选块 + 合同基本信息                                                        |
| 输出字段 | `category_answer`、`predicted_answers[]`（`text` + `answer_start`）、`processing_status` |
| 硬约束  | **偏移由程序定位，不由模型填写**；模型只给引文，`answer_start` 由程序在冻结文本中查找后写入                              |
| 状态取值 | `COMPLETED` / `INCOMPLETE` / `ERROR`                                                 |

**契约示例（用于说明字段流转，不是本次运行结果）：**

```json
{
  "category": "Renewal Term",
  "category_answer": "5 years",
  "predicted_answers": [{
    "text": "This Agreement shall be renewed automatically for another five (5) years upon the expiration unless the Parties confirm, in writing, the termination of this Agreement.",
    "answer_start": 13414
  }],
  "processing_status": "COMPLETED"
}
```

> `answer_start=13414` 已在冻结文本上核对：`context[13414 : 13414+len(text)] == text` 成立（源：`retrieval_case.md` §3）。

### 4.5 S4 证据核验 `RAGTool.verify()`　【实际运行 + 桩运行】

三道检查，顺序不可颠倒。

| 检查     | 谁执行       | 通过条件                                                                   | 未通过后果                                                                              |
| ------ | --------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| ① 位置核验 | 程序，模型不可覆盖 | `context[start:start+len(text)] == text`                               | `position_valid=false` → `verification_status=FAILED`，**不调用语义核验**（`model_calls=0`） |
| ② 语义核验 | 模型（三态）    | `SUPPORTED` / `UNSUPPORTED` / `INSUFFICIENT`，逐条 + 整体 `overall_support` | schema 校验失败、未配置密钥、调用失败 → 整批作废为 `UNCERTAIN`，**不假装通过**                               |
| ③ 覆盖核验 | 程序        | 仅对 `No` 结论：锚定词在全文的每处出现都落在已检索块内                                         | `coverage_status=INSUFFICIENT` → 返回 `uncovered` 位置，交 4 号补查                         |

**本案例 Q7 的实际输出（语义核验为桩）：**

```json
{
  "evidence_checks": [{
    "answer_index": 0,
    "position_valid": true,
    "support_status": "SUPPORTED",
    "reason": "STUB：引文包含答案关键词。",
    "page": 1
  }],
  "verification_status": "PASSED",
  "coverage_status": "NOT_APPLICABLE",
  "context_sha256": "4d9af82e...",
  "model_calls": 1
}
```

⚠️ **必须原样保留的警示**：本例 `PASSED` 中的语义部分来自桩函数。真实运行时由 `DeepSeekClient` 判断；未配置密钥时同一次调用会返回 `verification_status=UNCERTAIN`、`reason="语义核验未执行（MODEL_NOT_CONFIGURED）"`。**工具不会把「没核验」写成「通过」。**


### 4.6 S5 规则核验 `RuleTool.review()`　【模块级实跑 / 全链路未联调】

3 号模块已在分支 `feature/risk-rules-1` 提交（10 个文件），**模块本身可以独立运行，但尚未与 4 号 Agent、5 号 RAG 做过端到端联调**。

#### 4.6.1 真实接口：九个输入，五个新增输出

```python
from rules import RuleTool
check = RuleTool().review(
    document_id=..., question_id=..., category=..., category_answer=...,
    predicted_answers=..., evidence_checks=...,
    processing_status=..., verification_status=..., coverage_status=...,
)
```

| 类别     | 内容                                                                                                                                                                                           |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 九个输入   | `document_id`、`question_id`、`category`、`category_answer`、`predicted_answers`、`evidence_checks`、`processing_status`、`verification_status`、`coverage_status`——**与 4 号、5 号已有的字段完全一致，不增加上游抽取负担** |
| 新增输出   | `fact_status`（CONFIRMED / UNCERTAIN）、`clause_description`（中文事实描述）、`rule_execution_status`（EXECUTED / DISABLED / NOT_CONFIGURED）、`review_results[]`、`requires_manual_review`                  |
| 单条规则字段 | `rule_id`、`status`、`risk_level`、`reason`、`evidence_indices`、`missing_fields`、`requires_manual_review`、`recommendation`                                                                       |
| 状态取值   | 规则状态是 **TRIGGERED / NOT_TRIGGERED / NOT_APPLICABLE / UNCERTAIN** 四态（不是 v2.0 里我推测的 PASS/FLAG/REVIEW）                                                                                          |
| 不处理的类别 | 只处理 Q6–Q11 六类；传入 Q1–Q5 会抛 `ValueError`。基础信息仍由 4 号自行封装                                                                                                                                        |

> **一处需要 4 号注意的接口差异**：4 号 `agent_system.md` 写的是 `RuleTool.evaluate()`；3 号推荐的是 `review()`。`evaluate()` 仍然保留，但**只返回规则列表，不含 `fact_status` 和 `clause_description`**。若 4 号继续用 `evaluate()`，报告里就不会有事实描述，也无法区分「事实确认了但政策无法判断」。建议 4 号改用 `review()`。

#### 4.6.2 六条规则与当前政策值（全部来自 `risk_rules.yaml`）

| rule_id       | 类别                                 | 政策参数与当前值                                                        | 触发条件                    | 等级     | 触发后复核 |
| ------------- | ---------------------------------- | --------------------------------------------------------------- | ----------------------- | ------ | ----- |
| `LAW-001`     | Governing Law                      | `allowed_governing_laws=["California","New York"]`              | 明确地区不在清单内               | MEDIUM | 是     |
| `RENEWAL-001` | Renewal Term                       | `maximum_renewal_months=12`                                     | 明确单次续约期限 **严格大于** 12 个月 | LOW    | 是     |
| `NOTICE-001`  | Notice Period To Terminate Renewal | `notice_period_threshold_days=60`；`day_basis="AS_WRITTEN_DAYS"` | 明确天数 **严格大于** 60        | MEDIUM | 是     |
| `INS-001`     | Insurance                          | `require_insurance_clause=true`                                 | 要求存在，且充分检查后答案为 No       | MEDIUM | 是     |
| `AUDIT-001`   | Audit Rights                       | `require_audit_clause=true`                                     | 要求存在，且充分检查后答案为 No       | LOW    | 是     |
| `TERM-001`    | Termination For Convenience        | `flag_if_present=true`                                          | 要求关注，且已核验答案为 Yes        | LOW    | 是     |

六项 `enabled` 均为 `true`。三个单位口径必须记住：

1. **不等式一律严格大于**，等于阈值不触发（`60 days` → NOT_TRIGGERED，`90 days` → TRIGGERED）。
2. **只做整数月/整数年**，1 年按 12 个月归一化；天数不换算为月，月、年也不换算为天。
3. **布尔类别只认 `Yes` / `No` 两个精确字符串**，小写 `no`、`Unknown` 一律进 `missing_fields`。

#### 4.6.3 在 CASE-001 的输入条件下实跑的结果

下表是**用 3 号模块真实执行**得到的输出（本机下载 `rule_engine.py` + `risk_rules.yaml` 后调用 `RuleTool().review()` 复现）。需要说清楚的是：**规则模块的输出是真实运行结果，但 `category_answer` 是按合同原文设计的输入值**——因为 LLM 抽取（§4.4）尚未运行。所以这张表证明的是「规则模块按配置工作」，不是「系统在真实抽取下得到该结论」。

| 输入（category_answer 及上游状态）            | `fact_status` | 规则          | `status`                          | `risk_level` | 人工复核  |
| ------------------------------------ | ------------- | ----------- | --------------------------------- | ------------ | ----- |
| Q7 `5 years`，核验 PASSED               | CONFIRMED     | RENEWAL-001 | **TRIGGERED**                     | LOW          | true  |
| Q7 `5 years (automatic)`，核验 PASSED   | CONFIRMED     | RENEWAL-001 | **UNCERTAIN**                     | null         | true  |
| Q7 `five (5) years`，核验 PASSED        | CONFIRMED     | RENEWAL-001 | **UNCERTAIN**                     | null         | true  |
| Q7 `5 years`，但位置核验 false             | **UNCERTAIN** | RENEWAL-001 | UNCERTAIN（缺 `evidence_checks[0]`） | null         | true  |
| Q8 `null`（合同无明确天数）                   | UNCERTAIN     | NOTICE-001  | UNCERTAIN（缺 `category_answer`）    | null         | true  |
| Q9 `No` + coverage SUFFICIENT        | CONFIRMED     | INS-001     | **TRIGGERED**                     | MEDIUM       | true  |
| Q9 `No` + coverage INSUFFICIENT      | **UNCERTAIN** | INS-001     | UNCERTAIN（缺 `coverage_status`）    | null         | true  |
| Q9 `no`（小写）+ SUFFICIENT              | UNCERTAIN     | INS-001     | UNCERTAIN（缺 `category_answer`）    | null         | true  |
| Q10 `Yes`                            | CONFIRMED     | AUDIT-001   | NOT_TRIGGERED                     | null         | false |
| Q11 `Yes`                            | CONFIRMED     | TERM-001    | **TRIGGERED**                     | LOW          | true  |
| Q6 `Illinois`                        | CONFIRMED     | LAW-001     | **TRIGGERED**                     | MEDIUM       | true  |
| Q6 `California`                      | CONFIRMED     | LAW-001     | NOT_TRIGGERED                     | null         | false |
| Q6 `laws of the State of California` | CONFIRMED     | LAW-001     | UNCERTAIN（缺 `category_answer`）    | null         | true  |

**四个必须读出来的结论：**

1. **Q7 会真的触发规则。** `5 years` = 60 个月 > 12 个月，输出 `RENEWAL-001 TRIGGERED / LOW / 建议人工确认`，理由原文是「单次续约期限 5 years 按 60 个月比较，大于上限 12 个月」。这是本案例第一个**从检索到规则**的完整结果。
2. **但同一份合同，答案写法不同，结论就从「触发」变成「无法确认」。** 若抽取写成 `5 years (automatic)` 或照抄原文 `five (5) years`，规则只能返回 UNCERTAIN。**这不是规则写错了，而是上游答案没有规范化**（FC-12）。
3. **`fact_status` 和规则状态是两个维度。** `5 years (automatic)` 那一行：事实已确认（CONFIRMED，条款确实写的是 5 年），但政策无法判断（UNCERTAIN）。案例与报告里必须分开写，否则会把「格式不匹配」误报成「条款有问题」。
4. **Q9 的链路是通的，但要看 coverage。** `No` + SUFFICIENT → 触发 INS-001（MEDIUM）；`No` + INSUFFICIENT → 直接 UNCERTAIN，缺的字段是 `coverage_status`。**「不能拿空证据当无风险」。**

- 合同这段只写「除非双方书面确认终止」，**没有天数**，所以合理结果是 `category_answer=null` → `fact_status=UNCERTAIN`、`NOTICE-001 UNCERTAIN`、`missing_fields=["category_answer"]`；
- 即使抽取给 `six months`，规则也会返回 UNCERTAIN（不默认换算），不会强行算成 180 天；
- 若抽取把「五年」写成 `5 years` 塞进 Q8，规则会返回 TRIGGERED——**这才是真正危险的误报**，而且位置核验查不出来。

#### 4.6.5 模块验证状态（如实记录）

| 项             | 状态                                                                 |
| ------------- | ------------------------------------------------------------------ |
| 单元测试          | 3 号本地 FinAI（Python 3.12.16）通过 44 项，覆盖六类规则、阈值边界、证据不足、规则关闭、事实描述与结果封装 |
| 测试文件          | **未上传**（引用是模拟合同的完整文本，按交接范围，仅本地保留）                                  |
| 与 4 号 / 5 号联调 | 未完成                                                                |
| 运行依赖          | 仅标准库，无需模型 API，无需完整 CUAD 数据集                                        |
| 配置生效方式        | 重新创建 `RuleTool` 实例；**程序不实时监控配置文件变化**                               |
| 政策性质          | 演示假设，不是行业惯例、法律标准或 CUAD 风险标签                                        |

> **政策声明**：阈值、地区清单、提示等级均为**项目自设的模拟内部政策**。规则触发 ≠ 条款违法；`[]` 只表示没有配置或没有启用适用规则，**不等于核验成功或合同无风险**。

### 4.7 S6 决策 `Agent.decide_next_action()`　【设计待运行】

| 本轮状态组合                                                                       | 决策                                 | 后续动作                                                   | 依据          |
| ---------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------ | ----------- |
| `fact_status=CONFIRMED` + 规则 `NOT_TRIGGERED` / `NOT_APPLICABLE` / `DISABLED` | `ACCEPT`                           | 保留 `clause_description`，正常汇总                           | 3 号 §四第 4 条 |
| `fact_status=UNCERTAIN`（抽取未完成 / 核验 FAILED / `No` 覆盖不足）                       | `RETRY`                            | 先补查或重抽取；**即使规则关闭，也不能直接接受未确认事实**                        | 3 号 §四第 1 条 |
| `fact_status=CONFIRMED` 但规则 `UNCERTAIN`                                      | 分两种：缺参数 → 补配置；语义复杂 → 直接 `ESCALATE` | **不盲目重复检索**                                            | 3 号 §四第 2 条 |
| 规则 `TRIGGERED` 且 `manual_review_on_trigger=true`                             | `ESCALATE`                         | 保留事实与风险提示，进复核清单                                        | 3 号 §四第 3 条 |
| 重试预算耗尽（`max_retries=2`，即首次 + 最多两次补查）                                         | `ESCALATE`                         | 标记 `needs_manual_review=true`，写入 `manual_review_items` | 4 号 §7.2    |

⚠️ **这里存在一处 4 号与 3 号的设计分歧，必须在联调前定下来。**

- 4 号 `agent_system.md` §4.1 的流程图注释写：「规则结果若要求复核，现有 Agent 会先在重试预算内尝试补查，预算用尽后才标记人工复核。」
- 3 号接口文档 §四 写：「规则已触发且要求人工复核：保留事实与风险提示并进入复核清单，**不为消除风险提示而重试**。」

两者相反。按 3 号的逻辑更合理：风险提示是**政策结论**，不是检索缺陷；再检索几次也不会让「续约 5 年超过 12 个月上限」这件事消失，反而可能因为重新抽取导致答案漂移（`5 years` → `5 years (automatic)`），把本来能触发的规则洗成 UNCERTAIN，**看似「风险消失了」，实际是证据变差了**。

**建议**：`TRIGGERED` 直接 `ESCALATE`；`RETRY` 只用于 `fact_status=UNCERTAIN`。这一条已列入 `REVISION_NOTES.md` 的待确认清单。

> 注意 4 号 §7.3 的措辞：`ESCALATE` 只表示**已交付一项待人工处理的事项**，不等于「有人审过了」。案例文件里不得写成「经人工复核确认」。

### 4.8 S7 汇总与报告　【设计待运行】

报告字段固定 8 项：合同名称 / 审查类别 / 条款识别结果 / 风险等级 / 合同原文片段 / 补查或处理建议 / 是否需要人工复核及原因 / 证据位置。没有规则结论的类别写「未评估 / 无适用规则」，**不得写成「低风险」**。

---

## 5 四条分支深描

> 只写一条「成功路径」的案例没有治理价值。以下四条分支分别对应 `ACCEPT` / `TRIGGERED→ESCALATE` / `UNCERTAIN→RETRY` / `FAILED→拦截`，也是 D 组相对 C 组要检验的增量（H3）。
>
> **共同前提（必须说明）**：这四条分支的**规则输出都是用 3 号模块真实执行**得到的；但 `category_answer` 是**按合同原文设计的输入**，因为 4 号的 LLM 抽取尚未运行。所以它们证明的是「链路在每个分支上如何走」，不是「系统在真实抽取下必然得到该结论」。

### 5.1 分支 B1：正向接受（Q10 Audit Rights）　【设计输入 + 规则模块实跑】

| 步骤     | 内容                                                                                                                                 |
| ------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| ① 检索   | Q10 的 top-1 为 `C6558`（score 5.43，page 1）；该类别 gold=0，即无人工标注片段                                                                       |
| ② 抽取   | 设计输入 `category_answer="Yes"`，`answer_start` 由程序定位，`COMPLETED`                                                                      |
| ③ 位置核验 | `position_valid=true`                                                                                                              |
| ④ 语义核验 | `SUPPORTED`（待真实模型运行）                                                                                                               |
| ⑤ 覆盖核验 | `NOT_APPLICABLE`（非 `No` 结论，不需要覆盖检查）                                                                                                |
| ⑥ 规则核验 | `fact_status=CONFIRMED`；`clause_description="存在审计权条款。"`；`AUDIT-001 NOT_TRIGGERED`，`risk_level=null`，`requires_manual_review=false` |
| ⑦ 决策   | `ACCEPT` —— 事实已确认、政策未触发、无复核要求                                                                                                      |
| ⑧ 报告   | 类别 Q10 / 结果「存在审计权条款」/ 风险等级「未触发（本项政策已执行）」/ 原文 + 块 `C6558` / 是否复核：否                                                                  |

**这一条要说清两件事：**

1. `NOT_TRIGGERED` **不等于「没有风险」**，只表示「本项政策要求已被满足」。3 号原文的理由字段就是这样写的：「存在审计权条款，满足本项存在性要求；**不判断具体内容是否充分**」。报告里写「未触发」，不能写「无风险」。
2. 该类别 gold=0，所以本例的 `Yes` 是假设输入，11 月 26 日必须换成真实抽取结果；否则就是拿设计值当运行值）。

### 5.2 分支 B2：规则触发并转人工（Q7 Renewal Term）　【规则模块实跑】

这是本案例**唯一一条从检索一路走到规则结论**的分支。

| 步骤     | 内容                                                                                                                                                                                                                                |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ① 检索   | `C13242`（score 10.41，rank 1，page 1），gold 1/1 被覆盖                                                                                                                                                                                  |
| ② 原文   | "The term of this Agreement shall be five (5) years. **This Agreement shall be renewed automatically for another five (5) years upon the expiration unless the Parties confirm, in writing, the termination of this Agreement.**" |
| ③ 抽取   | `category_answer="5 years"`，`answer_start=13414`，`COMPLETED`                                                                                                                                                                      |
| ④ 位置核验 | `context[13414:13414+len(text)] == text` 成立 → `position_valid=true`                                                                                                                                                               |
| ⑤ 语义核验 | `SUPPORTED`（**桩**）                                                                                                                                                                                                                |
| ⑥ 覆盖核验 | `NOT_APPLICABLE`                                                                                                                                                                                                                  |
| ⑦ 规则核验 | `fact_status=CONFIRMED`；`clause_description="识别到续约期限答案为：5 years。"`；`RENEWAL-001 TRIGGERED`，`risk_level=LOW`，`requires_manual_review=true`；理由原文：「单次续约期限 5 years 按 60 个月比较，大于上限 12 个月。」                                             |
| ⑧ 决策   | `ESCALATE` —— 已触发且政策要求人工复核，**不通过重复检索来消除提示**                                                                                                                                                                                       |
| ⑨ 报告   | 类别 Q7 / 结果「自动续约五年」/ 风险等级「LOW（政策提示）」/ 原文 + `C13242` / 建议「请人工确认该续约安排是否符合本次业务政策」/ 是否复核：是                                                                                                                                             |

**同一份合同、同一段原文，只改答案写法，结论就变了**（下面三行都是用真实模块跑的）：

| `category_answer`      | `fact_status` | 规则结果             | 后果                 |
| ---------------------- | ------------- | ---------------- | ------------------ |
| `5 years`              | CONFIRMED     | TRIGGERED / LOW  | 报出提示，转人工           |
| `5 years (automatic)`  | CONFIRMED     | UNCERTAIN / null | **提示消失**，退化成「无法确认」 |
| `five (5) years`（照抄原文） | CONFIRMED     | UNCERTAIN / null | 同上                 |

这意味着：**如果为了「消除」风险提示而反复重试，很可能只是把答案从规范写法变成不规范写法**，规则从 TRIGGERED 变成 UNCERTAIN——风险看起来没了，其实是被格式掩盖了。这也是 §4.7 那处分歧里我建议「TRIGGERED 不进 RETRY」的直接理由。详见 `failure_cases.md` FC-12。

### 5.3 分支 B3：覆盖不足 → 补查 → 升级（Insurance 类）　【实际运行（跨案例引用）】

本案例合同 Q9 Insurance 的 gold=0。但「gold=0」不等于「系统判 No 就可以过」。5 号在另一份合同上给出了真实的反例（源：`retrieval_case.md` §4，情形 B）：

| 字段                    | 实际值                                                                                                        |
| --------------------- | ---------------------------------------------------------------------------------------------------------- |
| document_id           | `LIMEENERGYCO_09_09_1999-EX-10-DISTRIBUTOR AGREEMENT`                                                      |
| `verification_status` | `UNCERTAIN`                                                                                                |
| `coverage_status`     | `INSUFFICIENT`                                                                                             |
| `reason`              | "Insurance 有 1 处锚定词落在已检索片段之外，不能据此判定不存在该条款。"                                                                |
| `coverage_detail`     | `total_occurrences=5`，`covered_occurrences=4`，`uncovered=[{"term":"insurance","start":21921,"end":21930}]` |

**处置链路：**

1. `coverage_status=INSUFFICIENT` → 本轮不得输出「无保险义务」；
2. `uncovered` 的 `start=21921` 直接喂给 4 号 `rewrite_query()`：把该位置附近的词（如 `certificate of insurance`、`additional insured`）加进检索语句；
3. 提高 `top_k` 重跑；
4. 若第 2 次补查仍 `INSUFFICIENT` → `ESCALATE`，复核包里写「合同全文出现 insurance 5 处，已覆盖 4 处，未覆盖位置 21921–21930，建议人工核对第 X 段」。

**这就是 v1 缺的那条链**：v1 只写「RAG 检索不到有效依据 → 转人工」，没有说明**怎么知道检索不到、怎么证明覆盖不足、补查时改什么**。上面四步是可以写进代码与 PPT 的。

**这条链在 3 号模块里的落点（实测）**：把这两种 `coverage_status` 分别喂给 `RuleTool.review()`，输出完全不同——

| 上游输入                  | `fact_status` | `clause_description`           | INS-001                                |
| --------------------- | ------------- | ------------------------------ | -------------------------------------- |
| `No` + `SUFFICIENT`   | CONFIRMED     | 经本次充分检查，未发现保险义务条款。             | **TRIGGERED / MEDIUM**，需人工复核           |
| `No` + `INSUFFICIENT` | **UNCERTAIN** | 暂无法确认是否存在保险义务条款：识别、核验或覆盖状态不足…… | UNCERTAIN（缺 `coverage_status`），等级 null |

### 5.4 分支 B4：位置核验拦截（不可绕过的底线）　【实际运行】

把 B1 的 `answer_start` 从 13414 改成 13419（偏移 +5，模拟模型或预处理造成的错位）：

```json
{
  "verification_status": "FAILED",
  "evidence_checks": [{
    "answer_index": 0,
    "position_valid": false,
    "support_status": "NOT_CHECKED",
    "reason": "切片与引用不一致（位置错位或文本被改写）。"
  }],
  "model_calls": 0
}
```

**要点：`model_calls=0`。** 位置对不上就不进入语义核验——即使模型「觉得」这段支持结论，也不能采纳。这是「可追溯」的底线，也是 4 号 §6「位置核验（程序检查）」不可被子模型覆盖的原因。

**再往下传一步（实测）**：这个 `FAILED` 结果进入 3 号模块后，会得到 `fact_status=UNCERTAIN`、`RENEWAL-001 UNCERTAIN`、`missing_fields=["evidence_checks[0]"]`、理由「引用缺少唯一且通过的核验结果」。也就是说，**位置错位不会在后两级被「修复」，只会一路被降级成无法确认**。这正是我们想要的行为：错误不会被掩盖，只会被标记。

---

## 6 人工复核包与复核记录

### 6.1 复核包必须包含的 11 个字段

| #  | 字段                                    | 来源                  | 为什么必须有                                       |
| -- | ------------------------------------- | ------------------- | -------------------------------------------- |
| 1  | `document_id` + 冻结哈希                  | `prepare`           | 证明复核的是同一份文本                                  |
| 2  | `question_id` + `category`            | 任务清单                | 定位是哪一类判断出的问题                                 |
| 3  | `trigger_reason`                      | 决策器                 | ACCEPT 之外必有明确原因码，见 6.1.1                     |
| 4  | `category_answer`                     | 抽取                  | 系统当时给出的结论                                    |
| 5  | `predicted_answers[]`                 | 抽取                  | 引文 + `answer_start`，可直接切片                    |
| 6  | `evidence_checks[]`                   | `verify`            | `position_valid` / `support_status` / `page` |
| 7  | `coverage_detail`                     | `verify`            | `No` 类结论的覆盖证据与 `uncovered` 位置                |
| 8  | `retrieval_history[]`                 | Agent               | 每轮 query、`top_k`、块 ID、核验结果，解释为什么补查           |
| 9  | `fact_status` + `clause_description`  | `RuleTool.review()` | 区分「事实确认了」与「政策判断不了」                           |
| 10 | `review_results[]` + `missing_fields` | `RuleTool.review()` | 规则是否触发、等级、缺哪一项、建议怎么补                         |
| 11 | 所用政策参数（阈值、清单、口径）                      | `risk_rules.yaml`   | 3 号明确要求「结果与所用配置一起保存」，否则结论无法复现                |

> 第 9–11 项是 v2.1 新增的。原因很简单：3 号模块会把「事实」和「政策」分开输出，复核包如果只记 `review_results`，人工就看不到 `clause_description`（合同到底写了什么），也看不到 `missing_fields`（到底缺什么），复核效率会很低。

#### 6.1.1 触发原因码

| 原因码                     | 含义                    | 典型来源                                                 |
| ----------------------- | --------------------- | ---------------------------------------------------- |
| `PREP_FAILED`           | 合同解析失败                | `prepare` 返回 FAILED                                  |
| `EXTRACT_INCOMPLETE`    | 抽取未完成                 | `processing_status=INCOMPLETE/ERROR`                 |
| `POSITION_INVALID`      | 引用位置对不上               | `position_valid=false`                               |
| `SUPPORT_UNSUPPORTED`   | 原文存在但不支持结论            | `support_status=UNSUPPORTED`                         |
| `SUPPORT_UNCERTAIN`     | 语义核验无法执行或结论不确定        | `verification_status=UNCERTAIN`                      |
| `COVERAGE_INSUFFICIENT` | `No` 结论覆盖不足           | `coverage_status=INSUFFICIENT`                       |
| `FACT_UNCERTAIN`        | 规则模块判定事实无法确认          | `fact_status=UNCERTAIN`                              |
| `RULE_TRIGGERED_REVIEW` | 规则已触发且政策要求复核          | `status=TRIGGERED` + `manual_review_on_trigger=true` |
| `RULE_UNCERTAIN`        | 已启用规则无法判断（缺参数或答案不可比较） | `status=UNCERTAIN` + `missing_fields` 非空             |
| `RULE_CONFIG_INVALID`   | 政策配置缺失或非法             | 规则开关/等级/阈值类型错误                                       |
| `RETRY_EXHAUSTED`       | 补查预算耗尽                | `retries=max_retries`                                |

> 原来的 `RULE_REVIEW` 一个码被拆成三个：**触发要复核**、**无法判断**、**配置有问题**。这三种情况的人工动作完全不同——第一种是看业务能否接受，第二种是补信息，第三种是找 3 号改配置。合成一个码，复核人就不知道该干什么。

### 6.2 人工处理结果的判定标准

| 处理状态                | 判定标准                         | 记录要求                                |
| ------------------- | ---------------------------- | ----------------------------------- |
| `ACCEPT`            | AI 的条款结论、引文与规则触发判断均与人工阅读原文一致 | 记录复核人所依据的原文位置                       |
| `MODIFY`            | 条款结论方向对，但风险描述、等级或建议需改        | 必须写出**改前→改后**，供后续算「描述准确率」           |
| `REJECT`            | 条款识别错误、引文不支持结论，或规则不应触发       | 必须归类为 FN/FP 之一，进 `failure_cases.md` |
| `INSUFFICIENT_INFO` | 现有原文与政策不足以判断（如政策阈值未定义）       | 写明缺什么：原文 / 政策参数 / 适用法域              |

> 四态设计的意义：`MODIFY` 与 `REJECT` 分开，才能区分「方向错」与「表述错」。若合并，会把提示质量问题算成识别问题，误导 6 号的指标解释。

### 6.3 复核结果回流

| 复核结论                                            | 回流到哪                            | 动作                                                         |
| ----------------------------------------------- | ------------------------------- | ---------------------------------------------------------- |
| `REJECT` 且属漏报（FN）                               | 5 号词表 / `categories.json`；3 号规则 | 补锚定词或同义词；必要时新增规则                                           |
| `REJECT` 且属误报（FP）                               | 4 号抽取提示词；3 号规则边界                | 增加否定与例外判别；收紧阈值、调整 `risk_level`，或把触发设置为必须人工确认               |
| `INSUFFICIENT_INFO` 属政策缺失                       | 3 号 `risk_rules.yaml`           | 补阈值、清单或明确「不适用」                                             |
| `INSUFFICIENT_INFO` 属答案不可比较（如 `five (5) years`） | **4 号抽取的输出格式**                  | 要求 `category_answer` 规范化；原文细节留在 `predicted_answers`（FC-12） |
| `RULE_CONFIG_INVALID`                           | 3 号配置                           | 修类型或补必填项；不要改规则逻辑绕开                                         |
| 复核后仍 `INSUFFICIENT`                             | 案例库                             | 记为残余风险，进 `limitations_and_governance.md` §9                |

这条回流链是第 7 部分与第 6 部分的接口：**6 号测的是系统表现，7 号要把复核结果变成下一轮的修改项**，否则治理方案只是文字。

---

## 7 案例结论与指标对接

### 7.1 结论（可直接进论文 §5）

1. **检索层对本案例是充分的，但依赖调用方式。** 11 类任务在同一份冻结文本上完成检索，9 个 gold 片段被 top-5 全覆盖；然而这一结果建立在「显式传 `category`」之上，5 号实测表明问句被改写后 span R@5 从 0.713 降至 0.307。因此不能把单例覆盖当作系统能力，也不能忽略调用契约。
2. **「找到条款」与「答对要素」是两件事。** Q7 与 Q8 的 top-1 同落 `C13242`，说明检索相关性高不代表目标要素存在。位置核验能拦下偏移（+5 字符即 `FAILED`，且 `model_calls=0`），但拦不下「把续约期读成通知期」这类要素混淆——后者只能靠语义核验和规则口径。
3. **否定结论必须过覆盖检查，而且这条已经是代码级约束。** `Insurance` 反例中 `total_occurrences=5`、`covered=4`，系统输出 `UNCERTAIN + INSUFFICIENT`；把它送进规则模块，得到 `fact_status=UNCERTAIN` 与 `INS-001 UNCERTAIN`，缺项明确写着 `coverage_status`。只有 `No + SUFFICIENT` 才会触发 `INS-001 / MEDIUM`。**5 号的覆盖检查是 3 号判断的硬前置，不是建议。**
4. **规则层已能给出真实结论，但结论对答案写法极度敏感。** Q7 在 `category_answer="5 years"` 时输出 `RENEWAL-001 TRIGGERED / LOW / 需人工复核`，理由为「按 60 个月比较，大于上限 12 个月」；写成 `5 years (automatic)` 或照抄原文 `five (5) years` 则退化为 `UNCERTAIN`。同一份合同、同一段原文，**风险提示会因为一个括号而消失**。这说明跨模块的答案规范化契约，比模型能力更早成为瓶颈。
5. **人工复核在本案例中只是「被标记」，不是「已完成」。** 复核包 11 字段与 11 个原因码已定，但尚无真实复核记录。

### 7.2 与 6 号指标口径的对接（回填实验表时按此表填）

| 本案例的观察                             | 进入哪个指标       | 口径说明                                               |
| ---------------------------------- | ------------ | -------------------------------------------------- |
| Q7 条款识别正确（gold 1/1）                | 召回率分子        | 以「合同 × 审核规则」为单位，Q7 计 TP                            |
| Q7 `RENEWAL-001 TRIGGERED`         | 风险识别的判定单位    | 6 号的 TP/FP/FN 以「合同×规则」为单位；该单位结果为「已触发」，与人工参考一致则计 TP |
| Q8 若被误报为「有通知期约定」                   | 精确率分母（FP）    | 该合同 Q8 gold=0，报出即为 FP                              |
| Q11 若被判「无无因终止」且覆盖不足却仍输出            | 召回率分母（FN）    | 应升级却给出确定结论，属漏报                                     |
| B1 的 1 条引用（`C6558`，位置正确）           | 引用正确率分子/分母   | 分母=1；分子在真实模型核验后才可计，桩运行不计                           |
| B4 的 `FAILED` 引用                   | 引用正确率分母，不计分子 | 计入「系统给出的引用总数」，同时记入「不可验证引用数」                        |
| B3 的 `INSUFFICIENT`                | 单列「依据缺失结论数」  | 按 6 号补充统计要求，不进引用正确率分子                              |
| 规则 `UNCERTAIN` 但事实 `CONFIRMED`     | 单列「政策无法判断数」  | **不得算进识别错误**：3 号要求「政策判断正确性与 CUAD 条款识别正确性分别评价」      |
| `prepare` 7 ms / `retrieve` 0.1 ms | 平均响应时间       | 仅工具层耗时，不含 LLM 调用，不可当作端到端耗时                         |

> 最后两行要特别提醒 6 号与 8 号：**① 不要把工具层毫秒数写成系统平均响应时间**（6 号口径是「从提交合同到完整报告输出」）；**② 不要把规则 `UNCERTAIN` 算成条款识别错误**（那是政策参数或答案格式问题，不是没找到条款）。

---

## 8 复现与环境记录

**检索与证据核验（5 号）**

```bash
# 模块自测（40 项）
python3 -m unittest discover -s tests -v

# 十一类联调冒烟（抽取与语义核验使用确定性桩）
python3 demo.py

# 全量检索评测（510 份合同、6480 个 gold span）
python3 evaluation/evaluate_rag_tool.py --limit 0 --cuad /path/to/CUADv1.json \
  --out results/eval_k5.json
```

**规则核验（3 号，分支 `feature/risk-rules-1`）**

```bash
# 环境：Python 3.10+，仅标准库；无需模型 API、无需 CUAD 数据集
conda env create -f environment.yml && conda activate FinAI   # 或直接用已有 FinAI
cd 3-risk-rules

# 3 号 README 给出的可运行示例（Governing Law = Illinois → LAW-001 TRIGGERED / MEDIUM）
python -c "
from rules import RuleTool
print(RuleTool().review(
    document_id='DEMO_CONTRACT', question_id='DEMO_CONTRACT__Governing Law',
    category='Governing Law', category_answer='Illinois',
    predicted_answers=[{'text':'This Agreement is governed by the laws of Illinois.','answer_start':0}],
    evidence_checks=[{'answer_index':0,'position_valid':True,'support_status':'SUPPORTED','reason':'模拟上游核验通过'}],
    processing_status='COMPLETED', verification_status='PASSED',
    coverage_status='NOT_APPLICABLE'))"
```

> 3 号说明：该示例的引用是模拟合同的完整文本，偏移设为 0；核验通过状态也是模拟输入，**不代表已运行真实 RAG**。本文件 §4.6.3 的 13 行实测，是把同一入口换成 CASE-001 的 `document_id` 与设计输入后跑出来的。

| 环境记录项          | 需填写内容                                                                   |
| -------------- | ----------------------------------------------------------------------- |
| Python 版本 / 依赖 | 检索模块仅用标准库（PDF 逐页解析依赖 `pypdf`）；规则模块 Python 3.10+ 仅标准库（3 号本地验证环境 3.12.16） |
| 模型与版本          | 待填（抽取用模型、语义核验用模型分别记录）                                                   |
| 是否调用外部 API     | 待填（直接影响响应时间解释）；规则模块**不调用任何 API**                                        |
| 运行日期           | 规则实测 2026-11-05；端到端待填                                                   |
| 冻结哈希一致性        | 必须与 §2 的 `4d9af82e...` 一致，否则偏移不可比                                       |
| 政策配置一致性        | 必须与 §2「所用政策版本」一致，否则规则结论不可比                                              |

---

## 9 待补齐清单（11 月 26 日前）

| # | 待补内容                                         | 依赖                   | 负责人   | 现状       |
| - | -------------------------------------------- | -------------------- | ----- | -------- |
| 1 | 真实 LLM 抽取结果（11 类）                            | 4 号 `main.py` + 模型密钥 | 4 / 7 | 未开始      |
| 2 | 六类规则在真实抽取下的输出                                | 第 1 项 + 3 号模块（已交付）   | 4 / 3 | 模块可用，等输入 |
| 3 | Agent 决策链日志（`ACCEPT/RETRY/ESCALATE` 各至少 1 条） | 4 号决策器按 §4.7 对齐      | 4     | 未开始      |
| 4 | 至少 1 条真实人工复核记录（含 `MODIFY` 或 `REJECT`）        | 人工                   | 7     | 未开始      |
| 5 | 把 §4.6.3 的「设计输入」换成真实抽取值                      | 第 1–2 项              | 7     | 待        |
| 6 | 端到端耗时（秒级）                                    | 全链路跑通                | 4 / 6 | 待        |
| 7 | 与 4 号确认用 `review()` 还是 `evaluate()`          | 4 号                  | 4 / 7 | 待确认      |
| 8 | 与 4 号确认「触发后是否重试」（§4.7 分歧）                    | 4 / 3 号              | 4 / 7 | 待确认      |

> 第 2 项的变化值得单独说明：v2.0 时它写着「依赖 3 号规则文件」，现在 3 号已经交付，**瓶颈从规则侧转移到了抽取侧**。11 月 26 日能否交付完整案例，取决于 4 号的抽取链路，而不是规则。
