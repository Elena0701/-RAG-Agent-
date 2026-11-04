# RAGTool 交付说明

对接《CUAD 合同审查 Agent：工程架构、工具接口与核心编排代码（修订版）》。
本包只提供 `tools/rag_tool.py` 这一个类，三个方法：`prepare` / `retrieve` / `verify`。

## 1 目录

```text
rags_tool_package/
├── tools/rag_tool.py            # RAGTool（唯一对外入口）
├── rag_core/
│   ├── index.py                 # 字符分块 + 合同内 BM25
│   ├── pdf_ingest.py            # PDF / TXT / JSON → 冻结文本与页码
│   ├── coverage.py              # No 的覆盖充分性检查
│   ├── semantic_review.py       # 语义核验提示词与输出 schema
│   ├── retrieval.py             # 分词与词表
│   ├── deepseek_client.py       # DeepSeek 客户端
│   └── categories.json          # 十一类类别与检索词表
├── tests/test_rag_tool.py       # 40 项契约测试
├── evaluation/evaluate_rag_tool.py  # CUAD 全量 Recall@K
├── results/                     # 评测结果（k=5 与 k=10）
├── demo.py                      # 十一类联调冒烟（抽取/核验用确定性桩）
└── docs/RAGTool_对接说明.md      # 逐项接口说明与联调问答
```

## 2 接入方式（与 4 号 `main.py` 一致）

```python
from tools.rag_tool import RAGTool

rag = RAGTool(config={"chunk_size": 800, "chunk_overlap": 120})   # 默认按条款标题切块

# 1) 每份合同一次
prep = rag.prepare(document_id=doc["document_id"], file_path=doc["file_path"])
if prep["status"] != "SUCCESS":
    raise RuntimeError(prep["reason"])

# 2) 每个类别至少一次；补查时用改写后的 query
chunks = rag.retrieve(document_id=..., query=task["question"], top_k=task["top_k"],
                      category=task["category"])["text"]

# 3) 每轮抽取后
verification = rag.verify(document_id=..., category=extraction["category"],
                          category_answer=extraction["category_answer"],
                          predicted_answers=extraction["predicted_answers"],
                          retrieval_history=history)
```

`RAGTool(config=...)` 会自动读取本目录的 `deepseek.local.env`（或环境变量）建立语义核验客户端；
没有可用密钥时 `verify` 返回 `verification_status=UNCERTAIN`（`model_status()["reason"]` 说明原因），
**不会假装通过**。测试可传 `config={"model_call": 桩函数}`。

## 3 关键约定

| 项 | 约定 |
| --- | --- |
| 偏移 | 相对 `prepare` 冻结的规范文本；Unicode 码点、0 起始、左闭右开 |
| 位置核验 | `context[start:start+len(text)] == text`，不一致 → `verification_status=FAILED`，语义核验不执行 |
| 语义核验 | 三态 `SUPPORTED / UNSUPPORTED / INSUFFICIENT`；整体状态另给 `overall_support` |
| `No` | 必须有覆盖依据：锚定词全文扫描 + 已检索块覆盖 → `coverage_status` |
| 空证据 | 一律不通过（`UNCERTAIN`），除非是 `No` + `SUFFICIENT` |
| 类别 | 11 类，顺序与 4 号 `CATEGORIES` 一致；`retrieve` 的 `category` 参数为可选扩展 |

## 4 需要agent配合的一点

`retrieve()` 只收到 `question` 时，检索质量取决于问句是否与固定模板逐字一致：

| 调用方式 | span Recall@5 | 说明 |
| --- | --- | --- |
| `retrieve(doc, question)`，问句与模板一致 | **71.3%** | 内部按模板识别类别并附加类别词表 |
| `retrieve(doc, question, category=...)` | **71.3%** | 显式传类别，最稳 |
| 问句被改写（如追加一句说明） | **32.0%** | 不猜意图，只用原句检索 |

建议：**要么保持 `CATEGORIES` 里的问句逐字不变，要么顺手把 `category` 传给 `retrieve`**（一行改动）。
`top_k=10` 可把 Recall@10 提到 81.5%，代价是交给抽取的块数翻倍。

## 5 验证情况

- 40 项单元测试通过（`python3 -m unittest discover -s tests -v`）
- 十一类联调冒烟通过（`python3 demo.py`，抽取与核验为明确标注的桩）
- CUAD 全量 510 份合同、6480 个 gold span 的检索评测见 `results/`，结论见 `docs/RAGTool_对接说明.md` §6
- 真实合同（38,671 字符 / 80 块）：prepare 7ms、retrieve 0.1ms

## 6 已知边界

- PDF：有 `pypdf` 则逐页解析；没有则用标准库兜底（简单文本 PDF 可读，带启发式警告）；加密字体或扫描件直接 `FAILED`，不返回空文本。
- `coverage_status` 是锚定词启发式检查，不是"条款不存在"的证明；锚定词表需要 3 号复核术语。
- 本工具不做风险判断、不读政策、不产出 `review_results`；这些属于 3 号。
- 单实例按顺序调用设计，不承诺跨线程并发安全。
