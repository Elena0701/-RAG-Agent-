# 检索评测结果说明

## 41 类回顾性评估

使用 41 类的标准问句从 `RAGTool.retrieve(document_id, question, top_k=5)` 入口检索，在同一份官方 test 拆分上比较默认混合检索和 BM25。每个方法均检查 102 份合同，共有 4,182 个合同与类别组合，其中 1,244 个组合有有效原文标注。指标以这部分的 2,643 个有效标注区间为分母。曾在开发期间查看该拆分。

| 检索方法 | Recall@1 | Recall@5 | 位置精确命中@5 | Macro Recall@5 |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 31.67% | 60.08% | 55.69% | 56.25% |
| MiniLM + BM25 混合检索 | 39.61% | 64.06% | 59.67% | 58.02% |

- 前 K 个片段合计覆盖某个标注原文位置的至少 80% 字符，计为一次召回。位置精确命中要求单个片段完整包含该处标注。宏平均只取有正例的 40 类。
- 原 11 类的混合检索召回了 1,043 / 1,307 条（79.80%）。新增 30 类在 test 中有 29 类出现正例，两种方法均召回 650 / 1,336 条（48.65%）。
- `Price Restrictions` 在 test 没有正例，逐类报告将其召回率记为 `null`。单独用 train 的 15 份有正例合同作功能验证，默认混合检索召回 12 / 27 条（44.44%）。测试指标仅使用 test 的标注。
- 本评估衡量有标注原文的召回与定位。无正例组合、语义审核和最终风险判断需用各自的任务指标评估。

在模块目录内运行以下命令可重现三个结果文件。前两条默认读取 `../data/cuad/source/test.json`，可通过 `--cuad` 指定数据位置。在本机已缓存 Embedding 模型时可设置 `HF_HUB_OFFLINE=1` 离线运行。

```bash
python evaluation/evaluate_rag_tool.py --modes as-agent --out results/cuad41_hybrid_test_replay.json
python evaluation/evaluate_rag_tool.py --retrieval-mode bm25 --modes as-agent --out results/cuad41_bm25_test_replay.json
python evaluation/evaluate_rag_tool.py --cuad ../data/cuad/source/train_separate_questions.json --category "Price Restrictions" --modes as-agent --out results/cuad41_price_restrictions_train.json
```

## 历史 v1.4（原 11 类）：统一口径后的回顾性评估

- `v14_development.json`：官方 train 内按标题哈希固定抽取 74 份，1032 个有效标注；选定 structured_protected。
- `v14_test_replay.json`：102 份官方 test 合同，1307 个有效标注；同口径重跑 BM25、原始问句向量、旧保守混合及选定方案。逐条核对实际工具输出。
- `v14_cache_benchmark.json`：独立计量模型加载、冷文档向量、热缓存。

| 回放方法 | Recall@1 | Recall@5 | 位置精确命中@5 |
| --- | ---: | ---: | ---: |
| BM25 | 0.4178 | 0.7177 | 0.7008 |
| 纯向量（原始问句） | 0.1806 | 0.4682 | 0.4598 |
| 旧保守混合，重算 | 0.4178 | 0.7238 | 0.7070 |
| 当前结构补充混合 | 0.5784 | 0.7980 | 0.7812 |

此前所有官方拆分已经被查看过，不能称未见盲测。此次只在 train 开发子集上比较方案，之后固定方案回放 test。

v1.4 不再把同起点不同长度的标注合并，也不把别处相同文字算成该位置精确命中。旧版 1257 个 spans 与旧 Exact@5 不可直接和新版比较；上表所有方法都已统一重算。

## 历史 v1.3（旧口径，不再作为当前指标）

以下文件保留历史记录。当时虽使用官方拆分，但测试部分此前参与过全量开发，不能消除历史数据泄漏：

- `hybrid_threshold_train.json`：408 份训练合同、5223 个 gold spans，只用于选参；选出阈值 0.75。
- `hybrid_test.json`：102 份官方测试合同的旧口径混合结果。
- `embedding_test.json`：同一测试集的纯 Embedding 消融。
- `bm25_test.json`：同一测试集的 BM25 基线。
- `cache_benchmark.json`：单合同冷/热文档向量缓存耗时。

| 测试集方法 | 合同 | gold spans | Recall@5 | Exact@5 | Macro Recall@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Embedding | 102 | 1257 | 0.4805 | 0.5664 | 0.6037 |
| BM25 | 102 | 1257 | 0.7136 | 0.7630 | 0.7480 |
| Hybrid（默认） | 102 | 1257 | **0.7200** | **0.7693** | **0.7495** |

## v1.2 历史全量实验（不作为正式测试结果）

- `embedding_smoke_10.json`：真实 Embedding 模型、CUAD 前 10 份合同、Agent 默认问法；仅用于工程冒烟。
- `bm25_smoke_10.json`：完全相同 10 份合同和问法的 BM25 对照。
- `hybrid_smoke_10.json`：Embedding + BM25 + weighted RRF 的当前默认方案。
- `embedding_as_agent_full.json`：510 份合同的纯 Embedding 全量消融。
- `hybrid_as_agent_full.json`：510 份合同的最终保护式混合检索结果。

| 模式 | 合同 | gold spans | Recall@5 | Exact@5 |
| --- | ---: | ---: | ---: | ---: |
| Embedding | 10 | 124 | 0.5322 | 0.6613 |
| BM25 | 10 | 124 | 0.7097 | 0.7661 |
| Hybrid（默认） | 10 | 124 | 0.7097 | 0.7661 |

全量结果见 `hybrid_as_agent_full.json`：510 份合同、6480 个 gold spans，Recall@5=0.7148、
Exact@5=0.7465、R@1=0.4048。相同口径 BM25 基线为 Recall@5=0.7126、Exact@5=0.7443、
R@1=0.4048。提升较小，论文中应如实表述。

纯 Embedding 全量结果为 Recall@5=0.4863、Exact@5=0.5593、R@1=0.2264，显著弱于 BM25；
因此最终工程方案不能只依赖向量召回。

## 旧版 BM25 结果

其余 `rag_tool_eval*.json` 和 `case_rows.json` 是 v1.0 BM25 基线或其消融结果。旧版全量
Recall@5=0.7126、Exact@5=0.7443、Recall@10=0.8148，不能标注为 Embedding 指标。

这些 510 份合同的文件曾同时用于开发选择和汇报，只保留为工程历史。
