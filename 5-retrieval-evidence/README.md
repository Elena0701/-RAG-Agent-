# RAGTool 交付说明（第 5 号，v1.4 Hybrid RAG）

本模块是合同审查 Agent 调用的检索与证据核验工具。对外接口仍是
`prepare / retrieve / verify`，因此 4 号 Agent 不需要因本次改造改变工作流。

默认检索使用本地 Sentence Transformers Embedding 与 BM25 的混合召回；纯 Embedding 和纯 BM25
均保留为论文消融基线。
DeepSeek 只负责 `verify()` 的语义证据核验，不负责生成向量。

## 1. 已完成的能力

```text
PDF / TXT / JSON / Markdown
        ↓
解析并冻结规范文本（保存哈希与页码）
        ↓
按条款切块（默认 800 字符，重叠 120）
        ↓
Embedding 与 BM25 双路召回 → 保守融合 → 开头线索补召回与重叠去重
        ↓
返回原文、全局字符偏移、页码、分数
        ↓
位置核验 + DeepSeek 语义核验 + No 覆盖检查
```

主要文件：

```text
tools/rag_tool.py                 # 唯一对外入口
rag_core/embedding.py             # Embedding 编码与余弦检索
rag_core/ranking.py               # 候选选择、开头结构线索、重叠去重
rag_core/index.py                 # 条款/字符分块与 BM25 基线
rag_core/rerank.py                # 可选 CrossEncoder 二阶段重排序
rag_core/pdf_ingest.py            # 合同解析、冻结文本、页码
rag_core/coverage.py              # No 答案的覆盖充分性检查
rag_core/semantic_review.py       # 证据语义核验提示词与结果校验
rag_core/deepseek_client.py       # DeepSeek 核验客户端
rag_core/categories.json          # 11 类 CUAD 类别与检索词
evaluation/evaluate_rag_tool.py   # CUAD Recall@K 评测
evaluation/diagnose_ranking.py    # 候选诊断、固定开发集选方案、历史测试回放
evaluation/select_hybrid_threshold.py # 仅用训练集选参
evaluation/benchmark_cache.py     # 冷/热向量缓存耗时
tests/                            # 71 项测试（70 快速 + 1 真实模型可选）
```

## 2. 安装

```bash
cd 5-retrieval-evidence
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

第一次使用会从 Hugging Face 下载公开模型，后续从本地缓存加载。默认固定为：

- 模型：`sentence-transformers/multi-qa-MiniLM-L6-cos-v1`
- revision：`b207367332321f8e44f96e224ef15bc607f4dbf0`
- 向量：单位化；检索分数为余弦相似度
- 范围：只搜索当前合同，不把不同合同混入同一索引
- 默认策略：`structured_protected`。保守混合保留强词法候选，补充达到 0.75 的向量候选；名称、当事方、签署日期、生效日期额外检查前 2400 字符的原始块，最多优先加入两块，并过滤高度重叠候选。
- 方案比较在官方 train 内按标题哈希固定抽出的 74 份合同上完成。此前全量数据已被看过，因此后续 official test 结果称为历史回放，不声称是未见盲测。
- 缓存：按合同哈希、模型版本、缓存结构版本与分块配置缓存数字向量到 `.rag_cache/`；默认最多 512 份，目录/文件仅当前用户可读写

模型权重、`.venv`、本地 API 密钥都不应提交 Git。

## 3. 4 号 Agent 的调用方式

```python
from tools.rag_tool import RAGTool

rag = RAGTool({"chunk_size": 800, "chunk_overlap": 120})

prepared = rag.prepare(document_id="DOC-1", file_path="contract.pdf")
if prepared["status"] != "SUCCESS":
    raise RuntimeError(prepared["reason"])

retrieval = rag.retrieve(
    document_id="DOC-1",
    query="May a party terminate without cause?",
    top_k=5,
    category="Termination For Convenience",   # 推荐显式传入
)

verification = rag.verify(
    document_id="DOC-1",
    category="Termination For Convenience",
    category_answer="Yes",
    predicted_answers=[{"text": "原文证据", "answer_start": 1234}],
    retrieval_history=[{
        "query": retrieval["query"],
        "top_k": retrieval["top_k"],
        "retrieved_chunk_ids": [item["chunk_id"] for item in retrieval["text"]],
    }],
)
```

关键返回约定：

| 方法 | 关键字段 | 含义 |
| --- | --- | --- |
| `prepare` | `status`, `context_sha256`, `retrieval_mode`, `retrieval_strategy` | 解析与索引是否成功 |
| `retrieve` | `text[].text/start/end/score/page`, `retrieval_mode` | 可追溯候选证据；原字段保持不变 |
| `verify` | `evidence_checks`, `verification_status`, `coverage_status` | 供 3、4 号继续规则判断与补查 |

`retrieve` 的 `category` 是可选参数，但推荐 4 号显式传入，以便固定检索意图。别名会归一到 11 个正式类别，未知类别返回 `UNSUPPORTED_CATEGORY`。所有
`answer_start` 都相对 `prepare` 冻结后的全文，必须满足：

```python
context[answer_start:answer_start + len(text)] == text
```

## 4. 默认混合检索与实验基线

默认混合检索（外部仍报告 `retrieval_mode="embedding"`，新增
`retrieval_strategy="hybrid"`）：

```python
rag = RAGTool()
```

纯 Embedding 消融：

```python
dense_only = RAGTool({"retrieval_mode": "embedding", "hybrid_enabled": False})
```

纯 BM25 基线：

```python
baseline = RAGTool({"retrieval_mode": "bm25"})
```

三种模式的 Agent 接口和原有证据字段一致。v1.4 修正了同位置不同长度标注的去重、重复文字误算精确命中以及失败样本分母统计。下面各行都用新口径重算；102 份官方 test 合同包含 1307 个去重有效标注。

| 历史测试回放方法 | Recall@5 | 位置精确命中@5 | Macro Recall@5 |
| --- | ---: | ---: | ---: |
| 纯 Embedding（原始问句） | 0.4682 | 0.4598 | 0.5545 |
| BM25 基线 | 0.7177 | 0.7008 | 0.7488 |
| 旧保护式混合，按新口径重算 | 0.7238 | 0.7070 | 0.7502 |
| 当前结构补充混合 | **0.7980** | **0.7812** | **0.8135** |

结果见 `results/v14_development.json` 和 `results/v14_test_replay.json`。不得直接与 v1.3 旧口径 Exact@5 比较。`retrieval_confidence` 是未校准的补查启发式，不是概率。`score` 保留 RRF 数值，结构优先会使最终排序不严格按 score 递减；使用 `rank` 和列表顺序。

缓存基准 `results/v14_cache_benchmark.json` 将模型加载与文档编码分开计时：本机模型加载 2.1055s、冷文档编码/建索引 0.1060s、热文档缓存 0.0012s。仅是单样本耗时，不是跨机器性能结论。

`No` 没有引用一律 `UNCERTAIN`，即使 coverage 为 `SUFFICIENT`。覆盖只表明检查范围；确认答案仍需支持引用与语义核验。带解析警告的全文不能通过否定结论覆盖核验。超过 120000 字符的语义送审返回 `SEMANTIC_CONTEXT_TOO_LARGE`，不静默截断。

## 5. DeepSeek 配置（只用于证据核验）

复制示例文件并在本机填写：

```bash
cp .env.example deepseek.local.env
```

`deepseek.local.env` 已被 `.gitignore` 排除。没有密钥时，解析和 Embedding 检索仍可正常工作；
`verify()` 的语义步骤会明确返回 `UNCERTAIN / MODEL_NOT_CONFIGURED`，不会伪装为通过。

## 6. 验证与评测

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
RUN_MODEL_TESTS=1 HF_HUB_OFFLINE=1 .venv/bin/python -m unittest tests.test_model_integration -v
.venv/bin/python demo.py

# 只在训练拆分上选混合准入阈值
HF_HUB_OFFLINE=1 .venv/bin/python evaluation/select_hybrid_threshold.py
HF_HUB_OFFLINE=1 .venv/bin/python evaluation/benchmark_cache.py

# v1.4 方案选择与固定方案回放
HF_HUB_OFFLINE=1 .venv/bin/python evaluation/diagnose_ranking.py
HF_HUB_OFFLINE=1 .venv/bin/python evaluation/diagnose_ranking.py --split test_replay

# 默认混合检索全量评测，只跑 Agent 的默认问法
HF_HUB_OFFLINE=1 .venv/bin/python evaluation/evaluate_rag_tool.py \
  --retrieval-mode embedding --modes as-agent \
  --cuad ../data/cuad/source/test.json \
  --out results/hybrid_test.json

# 纯 Embedding 消融：额外加 --dense-only

# BM25 对照
.venv/bin/python evaluation/evaluate_rag_tool.py \
  --retrieval-mode bm25 --modes as-agent \
  --cuad ../data/cuad/source/test.json \
  --out results/bm25_test.json
```

`HF_HUB_OFFLINE=1` 只适用于模型已经下载到本机之后，可避免离线环境反复检查网络。

逐模块原理、问题与改动详见 [docs/RAG设计与改进说明.md](docs/RAG设计与改进说明.md)。
更完整的字段、失败码与联调要求见 [docs/RAGTool_对接说明.md](docs/RAGTool_对接说明.md)
和 [docs/与4号联调清单.md](docs/与4号联调清单.md)。
