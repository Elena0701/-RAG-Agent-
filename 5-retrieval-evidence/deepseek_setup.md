# DeepSeek 语义核验配置

当前 v1.4 对外入口是 `tools.rag_tool.RAGTool`。4 号不需要提供模型函数；本模块自己读取配置并完成证据语义核验。Embedding/BM25 混合检索在本地运行，不调用 DeepSeek，也不消耗 DeepSeek API 额度。

## 1 本地配置

复制 `.env.example` 为项目根目录下的 `deepseek.local.env`，填写：

```text
DEEPSEEK_API_KEY=本地密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_TIMEOUT_SECONDS=60
DEEPSEEK_MAX_TOKENS=4096
```

`deepseek.local.env` 已被 Git 忽略，不得提交。也可以使用同名环境变量；环境变量优先于文件。

只检查配置、不发送请求：

```bash
python3 -c 'from tools.rag_tool import RAGTool; print(RAGTool().model_status())'
```

输出中的 `configured: true` 表示客户端已建立；`request_count: 0` 表示尚未调用 API。

## 2 给 4 号的调用方式

```python
from tools.rag_tool import RAGTool

rag = RAGTool({"chunk_size": 800, "chunk_overlap": 120})

prepared = rag.prepare(document_id, file_path)
retrieval = rag.retrieve(
    document_id=document_id,
    query=question,
    top_k=5,
    category=category,
)

# 4 号从 retrieval["text"] 中抽取答案与逐字引用后调用：
verification = rag.verify(
    document_id=document_id,
    category=category,
    category_answer=category_answer,
    predicted_answers=predicted_answers,
    retrieval_history=retrieval_history,
    question=question,
)
```

没有密钥、网络失败或模型输出不符合 schema 时，`verify` 返回 `verification_status=UNCERTAIN`，不会把技术失败当作证据通过。测试时可通过 `config={"model_call": 桩函数}` 注入确定性模型桩。

## 3 配置与调用错误

- `MISSING_API_KEY`：根目录 `deepseek.local.env` 未填写，或环境变量为空。
- `API_AUTH_FAILED`：密钥认证失败。
- `API_BALANCE_INSUFFICIENT`：账户余额不足。
- `API_RATE_LIMITED`：请求限流。
- `API_TIMEOUT` / `API_NETWORK_ERROR`：超时或网络错误。
- `API_EMPTY_OUTPUT` / `API_OUTPUT_INCOMPLETE`：返回为空或被截断。
- `INVALID_MODEL_OUTPUT`：返回内容不符合证据核验格式。

客户端只允许访问 DeepSeek 官方 HTTPS 地址，禁用重定向；密钥不会进入返回对象、日志或异常正文。
