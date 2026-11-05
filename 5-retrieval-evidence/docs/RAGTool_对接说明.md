# RAGTool 接口说明（v1.4 Hybrid RAG）

日期：2026-11-05　入口：`tools/rag_tool.py`　自动测试：71 项（70 快速 + 1 真实模型可选）

## 1. 接口不变

```python
RAGTool(config: dict | None = None)
    .prepare(document_id: str, file_path: str) -> dict
    .retrieve(document_id: str, query: str, top_k: int = 5,
              category: str | None = None) -> dict
    .verify(document_id: str, category: str, category_answer,
            predicted_answers: list[dict], *,
            retrieval_history: list[dict] | None = None,
            question: str | None = None) -> dict
```

v1.4 使用 Embedding + BM25 混合召回，补充合同开头线索并过滤高度重叠块。4 号原有调用顺序、必需参数和 3 号读取的核验字段不变。

## 2. 安装与构造

4 号仓库需要包含：

```text
tools/rag_tool.py
rag_core/
requirements.txt
requirements-lock.txt
```

安装后直接构造：

```bash
python3 -m pip install -r requirements.txt
```

```python
rag = RAGTool({"chunk_size": 800, "chunk_overlap": 120})
```

默认配置：

| 配置 | 默认值 |
| --- | --- |
| `retrieval_mode` | `embedding` |
| `embedding_model` | `sentence-transformers/multi-qa-MiniLM-L6-cos-v1` |
| `embedding_revision` | `b207367332321f8e44f96e224ef15bc607f4dbf0` |
| `embedding_device` | `cpu` |
| `embedding_batch_size` | `32` |
| `hybrid_enabled` | `True` |
| `ranking_policy` | `structured_protected`（开发子集选定） |
| `hybrid_sparse_quota_ratio` | `1.0`（仅旧 protected 路径使用该实验参数） |
| `hybrid_dense_admission_threshold` | `0.75`（仅用 CUAD 训练拆分选定） |
| `reranker_enabled` | `False`（实测效果下降，仅留作消融） |

若要跑论文 BM25 基线，构造时传 `{"retrieval_mode": "bm25"}`。

## 3. `prepare`

支持 `.pdf/.txt/.json/.md`。成功示例：

```json
{
  "document_id": "DOC-1",
  "status": "SUCCESS",
  "context_sha256": "...",
  "chars": 18342,
  "chunk_count": 31,
  "retrieval_mode": "embedding",
  "retrieval_strategy": "hybrid",
  "embedding_cache_hit": true,
  "method": "pypdf",
  "pages": 12,
  "warnings": []
}
```

Embedding 专用失败码：

| code | 含义 |
| --- | --- |
| `EMBEDDING_DEPENDENCY_MISSING` | 未安装 `sentence-transformers` |
| `EMBEDDING_MODEL_LOAD_FAILED` | 模型未下载、网络/缓存或模型配置有问题 |
| `EMBEDDING_INFERENCE_FAILED` | 编码过程失败 |
| `EMBEDDING_INVALID_OUTPUT` / `EMBEDDING_ZERO_VECTOR` | 后端返回非法向量 |
| `INDEX_TRUNCATED` | 分块超过 `max_chunks`，为避免漏审而拒绝建立不完整索引 |

解析失败和索引失败都返回 `status="FAILED"`；4 号必须在继续拆任务前检查。

## 4. `retrieve`

推荐显式传类别：

```python
result = rag.retrieve(
    document_id=task["document_id"],
    query=task["question"],
    top_k=task["top_k"],
    category=task["category"],
)
```

成功结构：

```json
{
  "document_id": "DOC-1",
  "status": "OK",
  "query": "May a party terminate without cause?",
  "effective_query": "...",
  "query_source": "explicit",
  "resolved_category": "Termination For Convenience",
  "retrieval_mode": "embedding",
  "retrieval_strategy": "hybrid",
  "retrieval_confidence": "HIGH",
  "retrieval_confidence_calibrated": false,
  "requires_followup": false,
  "top_k": 5,
  "text": [
    {"chunk_id": "C120", "text": "...", "start": 120, "end": 966,
     "score": 0.032, "rank": 1, "page": 2,
     "dense_score": 0.63, "bm25_score": 4.21,
     "retrieval_sources": ["embedding", "bm25"]}
  ]
}
```

默认混合模式的 `score` 是 RRF 融合分数，同时给出 `dense_score` 和 `bm25_score`；纯 Embedding
模式下是余弦相似度，纯 BM25 模式下是 BM25 分数。三者数值不能直接比较，也不能把任何分数
当作“条款存在概率”。`retrieval_confidence` 是未校准的排序启发式；低置信度只触发 `requires_followup=true`，绝不会直接判定条款不存在。

结构优先候选可以包含 `retrieval_sources=["structure", ...]`，字段本身不变。以 `rank` 和返回列表顺序作为最终排序，`score` 保留原融合数值，不要二次按 score 排序。

## 5. `verify`

4 号把抽取答案和原文引用传回：

```python
verification = rag.verify(
    document_id=task["document_id"],
    category=task["category"],
    category_answer=extraction["category_answer"],
    predicted_answers=extraction["predicted_answers"],
    retrieval_history=history,
    question=task["question"],
)
```

3、4 号需要消费的字段：

| 字段 | 值 | 用途 |
| --- | --- | --- |
| `verification_status` | `PASSED/FAILED/UNCERTAIN` | 是否允许进入确定性规则判断 |
| `coverage_status` | `SUFFICIENT/INSUFFICIENT/NOT_APPLICABLE` | `No` 是否有足够检索覆盖 |
| `evidence_checks` | 每条引用的位置和语义状态 | 报告与人工复核 |
| `diagnostic_codes` | 机器可读原因 | Agent 重试、补查或升级人工 |
| `coverage_detail.uncovered` | 未覆盖主题位置 | 生成下一轮补查 query |

硬规则：任何引用必须满足冻结全文切片逐字相等。位置错位返回 `FAILED/POSITION_MISMATCH`，不会调用
DeepSeek。没有 DeepSeek 密钥时检索照常工作，但语义核验返回
`UNCERTAIN/MODEL_NOT_CONFIGURED`。

## 6. 4 号必须保存的检索历史

```json
{
  "query": "本轮真实 query",
  "top_k": 5,
  "retrieved_chunk_ids": ["C120", "C966"]
}
```

`No` 覆盖检查依赖这个历史。不要只保存模型最终答案，也不要把未检索过的块伪装进历史。
全文零锚定词也不能证明条款不存在，此时返回 `INSUFFICIENT` 和 `basis=NO_LEXICAL_ANCHOR`，防止同义表达造成假阴性。

v1.4：即使覆盖为 SUFFICIENT，空引用 No 也返回 UNCERTAIN/NO_EVIDENCE。覆盖只说明检索范围；有引用的否定答案仍需语义核验。历史 chunk ID 必须确实由当前文档实例的 retrieve 返回过。部分 PDF 页无文字会发出 warnings，否定答案覆盖保守返回不足。

超过语义全文预算（默认 120000 字符）返回 UNCERTAIN/SEMANTIC_CONTEXT_TOO_LARGE，不发起语义模型调用；4 号按现有 UNCERTAIN 流程转补查或人工。重新 prepare 失败会清除同 ID 的旧状态，不能继续沿用旧引用。

## 7. 3 号规则模块的接法

3 号不直接调用向量模型，只读取本模块的标准化证据：条款类别、识别答案、原文与位置、
`verification_status`、`coverage_status`。建议规则入口遵守：

- `PASSED` 才允许给确定性风险结论；
- `FAILED` 表示引用错误或矛盾，要求重新抽取；
- `UNCERTAIN` 或 `coverage_status=INSUFFICIENT` 转补查/人工复核。

## 8. 联调验收

1. `prepare` 返回 `retrieval_mode="embedding"`；
2. 11 类调用均能返回带 `start/end/page/score` 的候选块；
3. 故意改错 `answer_start`，必须得到 `POSITION_MISMATCH`；
4. `No` 且存在未覆盖主题词时，必须得到 `coverage_status="INSUFFICIENT"`；
5. 日志可按 `document_id + category` 重放 query、top-k 和 chunk IDs；
6. 不提交 `.env`、`deepseek.local.env`、模型缓存或 `.venv`。
