# 一份真实合同的检索与证据定位案例（v1.0）

项目：基于 RAG 与规则核验的商业合同审查 Agent
代码版本：`RAGTool` v1.0（字符分块 800/120，合同内 BM25，`prepare / retrieve / verify`）

> 这是**单合同开发演示**，用来展示字段、偏移和状态怎么流转，不是测试集成绩。
> 全量结果见 `retrieval.md` §8（510 份合同、6480 个 gold span）。

## 1 合同与运行条件

| 项 | 值 |
| --- | --- |
| document_id | `RISEEDUCATIONCAYMANLTD_04_17_2020-EX-4.23-SERVICE AGREEMENT` |
| 原文长度 | 16,372 个 Unicode 字符 |
| 冻结文本 SHA-256 | `4d9af82e13bc95c4459e66c7d19439753237bc89e6e4bf10819aedcc4018534f` |
| 分块 | 800 字符 / 重叠 120 → 36 块（**本合同的条款标题未命中 0 处，走字符切块兜底**；条款级切块在全量 82% 的合同上生效） |
| 检索 | 合同内 BM25，`top_k=5`，显式传 `category` |
| 数据来源 | CUAD 官方 `CUADv1.json`（训练侧），标注只在评测阶段读取 |

复现：

```bash
python3 evaluation/evaluate_rag_tool.py --limit 0 --cuad /path/to/CUADv1.json   # 全量
python3 demo.py                                      # 十一类冒烟（合成合同）
```

## 2 十一类检索结果

`gold` = 该类在 CUAD 中的人工标注片段数；`covered@5` = top-5 块并集覆盖 ≥80% 字符的片段数；
`top1` = 排名第一的块 ID（块 ID 即块起始字符位置前的 `C` 前缀，便于人工回查）。

| 类别 | gold | covered@5 | top-1 块 | top-1 分数 | 页码 |
| --- | --- | --- | --- | --- | --- |
| Document Name | 1 | 1 | C6155 | 7.46 | 1 |
| Parties | 4 | 4 | C8944 | 6.68 | 1 |
| Agreement Date | 1 | 1 | C14143 | 10.21 | 1 |
| Effective Date | 1 | 1 | C13752 | 12.82 | 1 |
| Expiration Date | 1 | 1 | C13242 | 10.42 | 1 |
| Governing Law | 0 | — | C12365 | 6.75 | 1 |
| Renewal Term | 1 | 1 | C13242 | 10.41 | 1 |
| Notice Period To Terminate Renewal | 0 | — | C13242 | 13.37 | 1 |
| Insurance | 0 | — | C7922 | 5.24 | 1 |
| Audit Rights | 0 | — | C6558 | 5.43 | 1 |
| Termination For Convenience | 0 | — | C11116 | 8.26 | 1 |

这份合同 9 个 gold 片段全部被 top-5 覆盖（9/9）。五类没有正参考片段，
所以对它们**不能计算召回**，只能看检索是否给出了可读的候选（见 §4 的 Insurance 例）。

## 3 例一：Renewal Term —— 检索→抽取→核验全链路

**① 检索**（`retrieve(document_id, "What is the renewal term?", top_k=5, category="Renewal Term")`）：

```json
{"document_id": "...SERVICE AGREEMENT", "status": "OK",
 "query_source": "explicit", "resolved_category": "Renewal Term",
 "text": [{"chunk_id": "C13242", "start": 13242, "end": 13872, "score": 10.41, "rank": 1, "page": 1}]}
```

块 `C13242` 的原文包含第 13 条：

> “The term of this Agreement shall be five (5) years. **This Agreement shall be renewed
> automatically for another five (5) years upon the expiration unless the Parties confirm,
> in writing, the termination of this Agreement.**”

**② 抽取**（4 号做的；这里给一个符合契约的示例）：

```json
{"category_answer": "5 years (automatic)",
 "predicted_answers": [{"text": "This Agreement shall be renewed automatically for another five (5) years upon the expiration unless the Parties confirm, in writing, the termination of this Agreement.",
                        "answer_start": 13414}],
 "processing_status": "COMPLETED"}
```

`answer_start = 13414` 是这段引文在**冻结文本**中的真实位置：
`context[13414 : 13414+len(text)] == text` 成立（已核验）。

**③ 核验**（`verify(...)`，注入确定性桩模型以演示通过分支）：

```json
{"evidence_checks": [{"answer_index": 0, "position_valid": true,
                      "support_status": "SUPPORTED", "reason": "STUB：引文包含答案关键词。", "page": 1}],
 "verification_status": "PASSED",
 "coverage_status": "NOT_APPLICABLE",
 "reason": "STUB 判定，不代表真实模型或人工结论。",
 "context_sha256": "4d9af82e...",
 "model_calls": 1}
```

⚠️ 上例的 `support_status` 来自**桩**。真实运行时由 `DeepSeekClient` 判断；
未配置密钥时同一次调用会返回 `verification_status=UNCERTAIN`、
`reason="语义核验未执行（MODEL_NOT_CONFIGURED）"`——工具不会把"没核验"写成"通过"。

## 4 例二：Insurance 判 No —— 覆盖检查才决定能不能通过

**情形 A：全文没有保险主题词（本案例合同）**

```json
{"verification_status": "PASSED", "coverage_status": "SUFFICIENT",
 "reason": "全文未出现 Insurance 的锚定词，缺席判断有覆盖依据。",
 "coverage_detail": {"total_occurrences": 0, "covered_occurrences": 0}}
```

**情形 B：全文提到保险，但这一轮没检索到（`LIMEENERGYCO_09_09_1999-EX-10-DISTRIBUTOR AGREEMENT`）**

```json
{"verification_status": "UNCERTAIN", "coverage_status": "INSUFFICIENT",
 "reason": "Insurance 有 1 处锚定词落在已检索片段之外，不能据此判定不存在该条款。",
 "coverage_detail": {"total_occurrences": 5, "covered_occurrences": 4,
                     "uncovered": [{"term": "insurance", "start": 21921, "end": 21930}]}}
```

情形 B 就是"不能拿空证据当无风险"的落地：`uncovered` 里的位置可以直接喂给 4 号的
`rewrite_query`（例如把该段附近的词加进检索语句），补查一轮再判。

## 5 例三：位置错了会当场拦下

把例一的 `answer_start` 从 13414 改成 13419（偏移 +5）：

```json
{"verification_status": "FAILED",
 "evidence_checks": [{"answer_index": 0, "position_valid": false,
                      "support_status": "NOT_CHECKED",
                      "reason": "切片与引用不一致（位置错位或文本被改写）。"}]}
```

此时**语义核验不执行**（`model_calls = 0`）。这一条是"可追溯"的底线：
位置对不上，后面的模型判断再对也不能采纳。

## 6 这个案例说明了什么、没说明什么

**说明**：

- 11 类任务都能在同一份冻结文本上跑；偏移可直接切片复核，块 ID 可人工回查；
- 位置核验能拦下 5 个字符的偏移误差；
- `No` 有明确的覆盖判据，不再靠"没检索到"下结论。

**没说明**：

- 不是测试集成绩：本例 9/9 覆盖只是单份合同；默认条款分块的全量 Recall@5 是 0.713（`retrieval.md` §8）；
- 不是语义准确率：通过分支用的是桩，真实模型结论与人工判断都还没有独立标注；
- 不代表长合同、扫描件、跨语言场景：见 `retrieval.md` §10、§12 的局限。

## 7 复现命令

```bash
# 单合同（本案例）需要本地 CUADv1.json，用 --cuad 显式指定路径
python3 -m unittest discover -s tests -v
python3 evaluation/evaluate_rag_tool.py --limit 0 --cuad /path/to/CUADv1.json \
  --out results/eval_k5.json
```
