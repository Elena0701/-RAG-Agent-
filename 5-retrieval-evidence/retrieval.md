# 第 5 部分：混合检索与证据可追溯方案（v1.4，合并用）

## 1. 模块边界

Agent 负责理解用户要求、拆分 11 类 CUAD 核查任务、调用工具和汇总风险。本模块只负责：

1. 解析并冻结合同文本；
2. 切分条款并建立合同内向量索引；
3. 根据“单个 CUAD 类别 + 核查问句”召回候选原文；
4. 核验引用位置、语义支持关系与 `No` 的覆盖充分性；
5. 把结构化证据交给 3 号规则模块和 4 号 Agent。

本模块不做用户意图识别、不拆任务、不输出风险等级。

## 2. 检索链路

```text
合同文件
  → 解析与保守归一化
  → 冻结全文、SHA-256、页码映射
  → 条款切块（默认 800 字符 / 重叠 120）
  → 文档块 Embedding + 合同内 BM25
  → 语义查询与词法查询分别检索
  → weighted RRF 计算双路分数
  → 保守混合（新向量候选门槛 0.75）
  → 四类基础信息补充开头线索，过滤高度重叠候选
  → top-k 原文块、全局字符偏移、页码和分数
```

默认模型是 `sentence-transformers/multi-qa-MiniLM-L6-cos-v1`，模型 revision 固定为
`b207367332321f8e44f96e224ef15bc607f4dbf0`。该模型分别提供 query/document 编码入口；
向量归一化后，点积就是余弦相似度。

当前按“单份合同”建立内存矩阵并精确搜索，不需要额外向量数据库。向量按合同哈希、模型版本和分块参数
缓存为只包含数字的 `.npy` 文件。这样可以避免不同合同串证据，
也能保留 `start/end` 与冻结全文的严格映射。若以后进入大规模跨合同检索，再将相同向量接入 FAISS
或其他向量库，Agent 接口不需要变化。

## 3. 查询构造

4 号推荐调用：

```python
rag.retrieve(document_id, question, top_k=5, category=category)
```

显式 `category` 会产生两条互不干扰的查询：BM25 使用“类别词表 + 原问句”，Embedding 使用原问句，
混合模式还可追加类别的自然语言定义。若未传类别，只有问句与 4 号固定模板完全一致时才自动匹配类别；
改写问句不会被工具擅自分类。返回值记录 `query/effective_query/lexical_query/query_source`，便于日志重放。

## 4. 可追溯证据

每个命中块至少包含：

```json
{
  "chunk_id": "C120",
  "text": "合同原文",
  "start": 120,
  "end": 966,
  "score": 0.63,
  "rank": 1,
  "page": 2
}
```

`score` 只是检索相似度，不代表条款一定存在，更不代表风险等级。抽取模块必须从 `text` 里逐字引用，
并把块内位置换算成冻结全文的全局 `answer_start`。核验硬条件是：

```python
context[start:start + len(text)] == text
```

## 5. 证据核验

`verify()` 依次执行：

1. 程序化位置核验；不匹配直接 `FAILED`，不调用模型；
2. DeepSeek 语义核验，判断引用是否支持答案；
3. 若答案为 `No`，扫描全文主题锚定词并检查检索覆盖，避免“没检索到”被误当成“不存在”。

v1.4：空引用的 No 始终 UNCERTAIN，即使覆盖充分。覆盖只表示检查范围；有引用的 No 还需通过语义核验。未实际返回的块不计入覆盖。结构补充会改变融合分数次序，最终排序以列表顺序和 rank 为准。

输出的核心状态为：

- `verification_status`: `PASSED / FAILED / UNCERTAIN`
- `coverage_status`: `SUFFICIENT / INSUFFICIENT / NOT_APPLICABLE`
- `diagnostic_codes`: 供 Agent 决定重试、补查或转人工

## 6. 实验设计

代码保留两条完全相同接口的检索路径：

| 实验组 | 配置 | 用途 |
| --- | --- | --- |
| Hybrid | `retrieval_mode="embedding", hybrid_enabled=True` | 当前默认方案 |
| Embedding | `retrieval_mode="embedding", hybrid_enabled=False` | 纯向量消融 |
| BM25 | `retrieval_mode="bm25"` | 关键词检索基线 |
| Hybrid + Reranker | `reranker_enabled=True` | 可选消融，当前不默认启用 |

在官方 train 内固定抽取 74 份合同（1032 条标注）比较方案，再固定选中的方案回放官方 test 的 102 份合同（1307 条标注）。

| 方法，同口径重算 | Recall@1 | Recall@5 | 位置精确命中@5 |
| --- | ---: | ---: | ---: |
| 纯向量，原始问句 | 0.1806 | 0.4682 | 0.4598 |
| BM25 | 0.4178 | 0.7177 | 0.7008 |
| 原保守混合 | 0.4178 | 0.7238 | 0.7070 |
| 当前结构补充混合 | 0.5784 | 0.7980 | 0.7812 |

提升集中于名称、当事方、签署日期、生效日期。其余七类回放召回率未变，不能解释为所有条款的理解能力增强。当前未默认启用通用重排模型或句子子块实验。

此前全部官方划分曾被开发查看，以上属于回顾性评估，不是未见盲测。新版修复同起点不同长度标注误去重、重复原文误算精确命中及失败样本分母遗漏，新旧方案均已重算；勿直接比较历史文件的旧 Exact@5。结果见 results/v14_development.json 与 results/v14_test_replay.json。

## 7. 已知限制

1. 通用语义模型并非法律领域专门训练，未必优于强词表 BM25；当前用混合召回降低这一风险。
2. 第一次运行需要下载公开模型；之后可以设置 `HF_HUB_OFFLINE=1` 使用缓存。
3. 当前索引只存在于进程内；Agent 重启后需要重新 `prepare()`。
4. 扫描件 PDF 没有 OCR，解析失败会明确返回 `FAILED`。
5. `No` 覆盖检查依赖人工锚定词，是防误判机制，不是数学上的“不存在证明”。

## 8. 复现

```bash
.venv/bin/python -m unittest discover -s tests -t . -v

HF_HUB_OFFLINE=1 .venv/bin/python evaluation/evaluate_rag_tool.py \
  --retrieval-mode embedding --modes as-agent \
  --cuad /path/to/test.json \
  --out results/hybrid_as_agent.json

# 纯向量消融在上面的命令增加 --dense-only

.venv/bin/python evaluation/evaluate_rag_tool.py \
  --retrieval-mode bm25 --modes as-agent \
  --cuad /path/to/test.json \
  --out results/bm25_as_agent.json
```

逐模块说明见 docs/RAG设计与改进说明.md；3、4 号按 docs/RAGTool_对接说明.md 接入。原始 CUAD 文件需本地提供，不包含在交付包中。
