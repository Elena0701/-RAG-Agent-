# RAGTool 接口说明（定稿 v1.0）

对齐文档：《CUAD 合同审查 Agent：工程架构、工具接口与核心编排代码（修订版）》
日期：2026-11-05　代码：`tools/rag_tool.py`　测试：40 项通过

## 1 三个方法（签名与 4 号文档一致）

```python
RAGTool(config: dict | None = None)
    .prepare(document_id: str, file_path: str) -> dict
    .retrieve(document_id: str, query: str, top_k: int = 5,
              category: str | None = None) -> dict      # category 为可选扩展，不传也能跑
    .verify(document_id: str, category: str, category_answer: Any,
            predicted_answers: list[dict], *, retrieval_history: list[dict] | None = None,
            question: str | None = None) -> dict   # question 可选，会进语义核验提示词
```

`category` 与 `retrieval_history` 都是**可选**参数，4 号按文档原样调用即可，不需要改签名。

## 2 数据流与九节点对应

| 九节点 | 由谁 | RAGTool 的角色 |
| --- | --- | --- |
| ① 接收合同 | 4 号 | — |
| ② 十一类任务 | 4 号 | — |
| ③ 分块与检索 | **5 号** | `prepare()` 解析文件→冻结文本→分块→索引；`retrieve()` 返回带偏移的块 |
| ④ 识别与抽取 | 4 号 | 只提供块原文与偏移，不生成答案 |
| ⑤ 证据核验 | **5 号** | `verify()`：位置核验 + 语义核验 + `No` 覆盖检查 |
| ⑥ 规则判断 | 3 号 | 不参与；只保证状态字段语义稳定 |
| ⑦ 反馈补查 | 4 号 | 通过 `coverage_detail.uncovered` 与 `retrieval_history` 支持改写 query |
| ⑧ 人工升级 | 4 号 | 提供 `UNCERTAIN` 原因字段 |
| ⑨ 报告与日志 | 4 号 | 输出可 JSON 序列化，含 `context_sha256` 便于复核 |

### 2.1 内部两个缓存（与 4 号的说明一致）

```python
self._indexes: dict[str, dict]   # document_id -> {"chunks": [...], "index": BM25Index}
self._contexts: dict[str, dict]  # document_id -> {"text", "sha256", "pages", "method", "warnings"}
```

- **`_indexes` 存分块与检索结构**：`retrieve` 只认 `document_id`，用它在这里找到块和 BM25 索引；
- **`_contexts` 存完整合同文本**：`verify` 用它做切片核验、`page_of` 用它查页码；
- 两个缓存按 `max_documents` 同步淘汰，键始终一致；调用方**不需要保存或传递原文**，只传 `document_id`。

## 3 `prepare(document_id, file_path)`

| 项 | 说明 |
| --- | --- |
| 支持格式 | `.pdf`、`.txt`、`.json`（`context`/`text`；兼容 CUAD v1 结构）、`.md` |
| 成功 | `{"document_id","status":"SUCCESS","reason","context_sha256","chars","chunk_count","method","pages","warnings"}` |
| 失败 | `{"document_id","status":"FAILED","reason":"<CODE>: <说明>","error_code":"<CODE>"}` |
| 失败码 | `FILE_NOT_FOUND` `UNSUPPORTED_FILE_TYPE` `PDF_PARSE_FAILED` `PDF_TEXT_EMPTY` `PDF_TEXT_UNUSABLE` `INVALID_JSON` `EMPTY_DOCUMENT` `DOCUMENT_TOO_LARGE` `INVALID_ARGUMENT` |
| 幂等 | 同一 `document_id` 再次 `prepare` 会重建索引并替换 `context_sha256`；旧偏移作废，必须重新抽取 |

**规范文本**：读入后做一次保守归一化（`\r\n→\n`、NBSP→空格、去零宽字符、去行尾空白、压缩 3 个以上空行），
之后所有偏移都相对这份文本。归一化只发生一次，保证 4 号的 `answer_start` 与 5 号的核验对得上。

**页码**：`pages=[{page,start,end}]`；`retrieve` 的块与 `verify` 的每条引用都带 `page`，也可调
`RAGTool.page_of(document_id, start)`。PDF 兜底解析拿不到逐页边界时会标记
`page_mapping_unavailable_single_page`，此时页码不可用于引用。

## 4 `retrieve(document_id, query, top_k=5, category=None)`

```json
{"document_id":"DOC-1","status":"OK","query":"...","effective_query":"...",
 "expanded":true,"query_source":"template","resolved_category":"Renewal Term",
 "top_k":5,"text":[{"chunk_id":"C120","text":"...","start":120,"end":966,
                    "score":3.21,"rank":1,"page":2}],
 "note":"候选与分数不代表条款存在或证据支持；空结果不等于没有该条款。"}
```

`text` 就是 4 号文档里的块字典列表（`chunk_id/text/start/end/score`），额外给 `rank` 与 `page`。

**查询扩展的三种来源**（`query_source`）：

| 来源 | 触发条件 | 效果 |
| --- | --- | --- |
| `explicit` | 调用方传了 `category` | 附加该类别词表，最稳 |
| `template` | 未传 `category`，但 `query` 与 4 号 `CATEGORIES` 的固定问句逐字一致 | 自动附加类别词表 |
| `none` | 未传 `category`，问句也不是模板原文 | 只用原句检索（不猜意图） |

实测差异很大（见 §6）：模板一致或显式传类别时 Recall@5 = 71.3%，问句被改写后只剩 32.0%。

## 5 `verify(...)`

```json
{"document_id":"DOC-1","category":"Notice Period To Terminate Renewal",
 "category_answer":"90 days",
 "evidence_checks":[{"answer_index":0,"position_valid":true,"support_status":"SUPPORTED",
                     "reason":"...","page":1}],
 "verification_status":"PASSED","coverage_status":"NOT_APPLICABLE","reason":"...",
 "diagnostic_codes":[],
 "context_sha256":"...","model_calls":1,"overall_support":{...},"coverage_detail":null}
```

判定真值表：

| 情形 | verification_status | coverage_status |
| --- | --- | --- |
| 任一引用位置不匹配 / 越界 / 空引用 | `FAILED`（语义核验不执行） | `NOT_APPLICABLE` |
| 引用齐全，模型判全部 SUPPORTED 且整体 SUPPORTED | `PASSED` | `NOT_APPLICABLE` |
| 模型判任一 UNSUPPORTED 或整体 UNSUPPORTED | `FAILED` | `NOT_APPLICABLE` |
| 模型判 INSUFFICIENT 或混合 | `UNCERTAIN` | `NOT_APPLICABLE` |
| 模型未配置 / 调用失败 / 输出不合 schema | `UNCERTAIN` | `NOT_APPLICABLE` |
| `No` 且无引用，覆盖充分 | `PASSED` | `SUFFICIENT` |
| `No` 且无引用，覆盖不足 | `UNCERTAIN` | `INSUFFICIENT` |
| 其他答案且无引用 | `UNCERTAIN` | `NOT_APPLICABLE` |

`verification_status` 只有 `PASSED / FAILED / UNCERTAIN`；抽取的 `COMPLETED / INCOMPLETE / ERROR` 留在
`processing_status`，两者不混用。

**`diagnostic_codes`（机器可读，4 号按它分支重试）**：

| code | 含义 | 建议动作 |
| --- | --- | --- |
| `POSITION_MISMATCH` | 引用位置与原文不一致 | 重新抽取，别重试核验 |
| `NO_EVIDENCE` | 非 No 答案但没给引用 | 重新抽取 |
| `COVERAGE_INSUFFICIENT` | 判 No 但仍有未检索到的相关段落 | 用 `coverage_detail.uncovered` 改 query 补查 |
| `MODEL_NOT_CONFIGURED` | 没配密钥 | 环境问题，不是证据问题 |
| `MODEL_ERROR` | 模型调用失败 | 按预算重试或转人工 |
| `EVIDENCE_CONTRADICTS` | 模型判定引用与答案矛盾 | 重新抽取 |
| `EVIDENCE_INSUFFICIENT` | 模型判定证据不足 | 补查 |
| `DOCUMENT_NOT_PREPARED` / `UNSUPPORTED_CATEGORY` / `INVALID_INPUT` | 调用错误 | 修调用 |`Yes`/`No` 会做大小写归一化（`"yes" → "Yes"`），但不改写调用方的字典。

### 5.1 `No` 的覆盖检查

空 `evidence_checks` 不能证明条款不存在。对 `No`，`verify` 用类别锚定词在**全文**扫描，
检查每一处出现是否落在 `retrieval_history` 里真正检索过的块内：

```json
"coverage_detail": {"status":"INSUFFICIENT",
  "reason":"Insurance 有 3 处锚定词落在已检索片段之外，不能据此判定不存在该条款。",
  "total_occurrences":5,"covered_occurrences":2,
  "uncovered":[{"term":"insurance","start":691,"end":700}],"anchors":["\\binsur\\w*"]}
```

`uncovered` 里的位置可以直接喂给 4 号的 `rewrite_query`（把该段的关键词加进检索语句）。
**局限**：锚定词由人工维护，覆盖不到的表述仍可能漏判；这是启发式检查，不是证明。

## 6 CUAD 全量评测（冻结文本 + 800/120 分块）

数据：510 份合同、6480 个 gold span（偏移已用冻结文本复核）；口径：top-K 块并集覆盖 gold span ≥80% 字符。

| 调用方式 | span R@1 | span R@5 | 精确@5 | macro R@5 |
| --- | --- | --- | --- | --- |
| 模板问句（等价 `as-agent`） | 0.405 | **0.713** | 0.744 | 0.754 |
| 显式传 `category` | 0.405 | **0.713** | 0.744 | 0.754 |
| 问句被改写 | 0.097 | 0.307 | 0.409 | 0.423 |
| 显式传 `category`，top_k=10 | 0.405 | 0.713（R@10 = **0.815**） | 0.744 | 0.754 |

切块策略对照：字符块 0.703 / **条款块 0.713**（默认）/ 条款块+句子检索 0.709。

分类别（显式传 category，k=5）：

| 类别 | gold span | R@1 | R@5 |
| --- | --- | --- | --- |
| Governing Law | 464 | 0.912 | 0.989 |
| Notice Period To Terminate Renewal | 122 | 0.779 | 0.959 |
| Renewal Term | 209 | 0.746 | 0.938 |
| Termination For Convenience | 246 | 0.577 | 0.850 |
| Agreement Date | 476 | 0.328 | 0.790 |
| Expiration Date | 466 | 0.521 | 0.785 |
| Insurance | 559 | 0.313 | 0.757 |
| Parties | 2327 | 0.400 | 0.708 |
| Audit Rights | 643 | 0.277 | 0.621 |
| Effective Date | 447 | 0.143 | 0.532 |
| Document Name | 521 | 0.115 | 0.361 |

与 v0.3（350 词元块，77.1% macro）相比略低，但块边界更贴近 4 号的 `chunk_size` 配置，
且偏移按字符冻结，和抽取模块的契约一致。若要提升，优先动 query（§4），而不是换检索算法。

## 7 PDF 支持

| 场景 | 行为 |
| --- | --- |
| 有 `pypdf` | 逐页抽取，页码完整 |
| 无 `pypdf`，简单文本 PDF | 标准库兜底（FlateDecode + `Tj/TJ`），`method="stdlib_pdf"`，带启发式警告 |
| 无 `pypdf`，内嵌/CID 字体 | `FAILED`（`PDF_TEXT_UNUSABLE`），提示装 `pypdf` 或用 `.txt` |
| 扫描件 | `FAILED`（`PDF_TEXT_EMPTY`），无 OCR，不会静默返回空文本 |

CUAD 原文是纯文本，建议评测与开发都走 `.txt/.json` 入口；正式演示若必须 PDF，再装 `pypdf`。

## 8 对 4 号文档 §8 的逐条回答

| # | 问题 | 回答 |
| --- | --- | --- |
| 1 | `answer_start` 相对什么 | 相对 `prepare` 冻结的规范文本；切片逐字相等才 `position_valid=true`；`context_sha256` 用于核对版本 |
| 2 | `No` 怎么核验 | 锚定词全文扫描 + 检索覆盖；只有 `SUFFICIENT` 才可能 `PASSED`（§5.1） |
| 3 | `evidence_checks` 与整体状态 | 同一次返回：逐条 `evidence_checks` + 整体 `verification_status` / `coverage_status` |
| 4 | 规则返回值 | 属 3 号；本工具只保证状态语义稳定，不产出 `review_results` |
| 5 | 失败补查要保存什么 | `query`、`top_k`、`retrieved_chunk_ids` 原样回传即可；另给 `coverage_detail.uncovered` 供改写 |
| 6 | LLM 抽取接口 | 属 4 号；本工具只提供块与偏移，抽取结果按 `predicted_answers` 回传 |
| 7 | 可运行性 | 已可运行：40 项测试 + `demo.py` 十一类冒烟；不依赖 4 号抽取实现 |
| 8 | 规则触发条件 | 属 3 号；本工具不读政策、不做分级 |
| 9 | 风险策略 | 不产生任何风险判断 |

## 9 与 v0.3 的差异（变更记录）

| 项 | v0.3 | v1.0（本包） |
| --- | --- | --- |
| 入口 | `EvidenceTools.retrieve_task / verify_evidence` | `RAGTool.prepare / retrieve / verify` |
| 文本来源 | 调用方传 `context` | `prepare` 从文件解析并冻结（保留 `prepare_text` 供评测） |
| 分块 | 350 正则词元 | 字符制 800 / 重叠 120 |
| 检索 query | 类别词表 + CUAD 问句 | query（+ 可选类别词表），三种来源可追溯 |
| 核验状态 | `COMPLETED/INCOMPLETE/ERROR` + `requires_followup` | `PASSED/FAILED/UNCERTAIN` + `coverage_status` |
| `No` | 无覆盖判据 | 锚定词覆盖检查 |
| 模型 | 内置 DeepSeek | 默认读 env 自动构造，可注入 `model_call`；无密钥时 `UNCERTAIN` |
| 类别 | 11 类 | 同 11 类，顺序与 4 号一致 |

保留不变：词表与 BM25 公式、提示词与 schema 校验、文本哈希、日志脱敏、`NOT_CHECKED` 语义。

## 10 运行

```bash
python3 -m unittest discover -s tests -v      # 40 项
python3 demo.py                               # 十一类联调冒烟
python3 evaluation/evaluate_rag_tool.py --limit 0 --cuad /path/to/CUADv1.json \
  --out results/rag_tool_eval_k5.json
```

## 11 待 3、4 号确认

1. **入口**：CUAD 统一走 `.txt/.json`，还是必须支持 PDF（决定是否引入 `pypdf` 依赖）。
2. **query**：4 号是否愿意在 `retrieve()` 里多传 `category`（否则必须保证 `CATEGORIES` 问句逐字不变）。
3. **锚定词表**：由 3 号复核术语（尤其 Insurance / Audit Rights 的表述边界）。
4. **规则侧**：是否消费 `coverage_detail.uncovered` 生成"建议补查哪一段"。
