"""Independent DeepSeek JSON client using only Python's standard library.

Configuration is read as data (never sourced as shell code). API keys are not
included in repr, returned metadata, provider errors or logs. No automatic retry.
Official API contract checked on 2026-11-04:
https://api-docs.deepseek.com/api/create-chat-completion/
https://api-docs.deepseek.com/guides/json_mode/
"""
from __future__ import annotations

import json
import math
import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

# 本地密钥模板与 README 都位于项目根目录；rag_core 只是内部实现目录。
DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / "deepseek.local.env"
ENV_KEYS = {"DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
            "DEEPSEEK_TIMEOUT_SECONDS", "DEEPSEEK_MAX_TOKENS"}


class ModelConfigError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ModelRequestError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable=False):
        self.code, self.retryable = code, retryable
        super().__init__(message)


def read_local_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise ModelConfigError("CONFIG_READ_FAILED", "无法读取本地模型配置文件。") from None
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ModelConfigError("INVALID_CONFIG", f"配置第 {number} 行应为 KEY=value。")
        key, value = (part.strip() for part in line.split("=", 1))
        if key not in ENV_KEYS or key in values:
            raise ModelConfigError("INVALID_CONFIG", f"配置第 {number} 行的字段未知或重复。")
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ModelConfigError("INVALID_CONFIG", f"配置第 {number} 行引号未闭合。")
            value = value[1:-1]
        values[key] = value
    return values


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str = field(repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    timeout_seconds: float = 60
    max_tokens: int = 4096

    def __post_init__(self):
        if (not isinstance(self.api_key, str) or not self.api_key.strip()
                or any(char.isspace() for char in self.api_key)
                or any(ord(char) < 33 or ord(char) > 126 for char in self.api_key)):
            raise ModelConfigError("MISSING_API_KEY", "请在 deepseek.local.env 或环境变量中设置 DEEPSEEK_API_KEY。")
        try:
            parsed = urlsplit(self.base_url)
            valid = (parsed.scheme == "https" and parsed.hostname == "api.deepseek.com"
                     and parsed.port in (None, 443) and parsed.path.rstrip("/") in ("", "/v1")
                     and not parsed.username and not parsed.password
                     and not parsed.query and not parsed.fragment)
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise ModelConfigError("INVALID_BASE_URL", "本适配器使用 DeepSeek 官方 HTTPS 地址；不向其他地址发送密钥。")
        if not isinstance(self.model, str) or not self.model.strip() or any(c.isspace() for c in self.model):
            raise ModelConfigError("INVALID_MODEL", "DEEPSEEK_MODEL 应为非空模型 ID。")
        if (isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float))
                or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 300):
            raise ModelConfigError("INVALID_TIMEOUT", "模型网络超时应在 0 到 300 秒之间。")
        if type(self.max_tokens) is not int or not 1 <= self.max_tokens <= 393216:
            raise ModelConfigError("INVALID_MAX_TOKENS", "模型输出上限必须为有效正整数。")

    @classmethod
    def from_env(cls, env_file: str | Path | None = None, *, environ=None):
        values = read_local_env(Path(env_file) if env_file is not None else DEFAULT_ENV_FILE)
        env = os.environ if environ is None else environ
        # Explicit environment settings override file settings, including empty values.
        values.update({key: env[key] for key in ENV_KEYS if key in env})
        try:
            timeout = float(values.get("DEEPSEEK_TIMEOUT_SECONDS", "60"))
            max_tokens = int(values.get("DEEPSEEK_MAX_TOKENS", "4096"))
        except (ValueError, TypeError):
            raise ModelConfigError("INVALID_CONFIG", "超时和输出 token 上限应为数字。") from None
        return cls(api_key=values.get("DEEPSEEK_API_KEY", ""),
                   base_url=values.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                   model=values.get("DEEPSEEK_MODEL", "deepseek-flash"),
                   timeout_seconds=timeout, max_tokens=max_tokens)

    @property
    def endpoint(self):
        return self.base_url.rstrip("/") + "/chat/completions"

    def public_metadata(self):
        return {"provider": "deepseek", "base_url": self.base_url, "model": self.model,
                "thinking": "disabled", "max_tokens": self.max_tokens,
                "timeout_seconds": self.timeout_seconds}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class DeepSeekClient:
    def __init__(self, config: DeepSeekConfig):
        self.config = config
        self.request_count = 0
        self.last_call = None
        self._opener = build_opener(_NoRedirect())

    @classmethod
    def from_env(cls, env_file: str | Path | None = None):
        return cls(DeepSeekConfig.from_env(env_file))

    def metadata(self):
        return {**self.config.public_metadata(), "request_count": self.request_count,
                "last_call": self.last_call}

    def __call__(self, messages: list[dict[str, str]]) -> str:
        if (not isinstance(messages, list) or not messages
                or any(not isinstance(m, dict) or set(m) != {"role", "content"}
                       or m["role"] not in ("system", "user", "assistant")
                       or not isinstance(m["content"], str) for m in messages)):
            raise ModelRequestError("INVALID_MESSAGES", "模型消息格式不正确。")
        body = {"model": self.config.model, "messages": messages, "stream": False,
                "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
                "max_tokens": self.config.max_tokens}
        request = Request(self.config.endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "application/json", "Accept": "application/json",
                                   "Authorization": "Bearer " + self.config.api_key}, method="POST")
        self.last_call = None
        self.request_count += 1
        start = time.monotonic()
        try:
            with self._opener.open(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            messages_by_status = {
                400: ("API_BAD_REQUEST", "DeepSeek 拒绝请求参数，请检查模型和输出配置。"),
                401: ("API_AUTH_FAILED", "DeepSeek 密钥认证失败，请检查本地密钥。"),
                402: ("API_BALANCE_INSUFFICIENT", "DeepSeek 账户余额不足。"),
                403: ("API_FORBIDDEN", "DeepSeek 拒绝访问，请检查账户权限。"),
                404: ("API_NOT_FOUND", "DeepSeek 接口或模型未找到，请检查配置。"),
                429: ("API_RATE_LIMITED", "DeepSeek 请求限流，请稍后重试。"),
            }
            code, reason = messages_by_status.get(status, ("API_HTTP_ERROR", f"DeepSeek 返回 HTTP {status}。"))
            raise ModelRequestError(code, reason, retryable=(status == 429 or status >= 500)) from None
        except (TimeoutError, socket.timeout):
            raise ModelRequestError("API_TIMEOUT", "DeepSeek 请求超时。", retryable=True) from None
        except (URLError, OSError):
            raise ModelRequestError("API_NETWORK_ERROR", "无法连接 DeepSeek，请检查网络。", retryable=True) from None
        if len(raw) > 2 * 1024 * 1024:
            raise ModelRequestError("API_RESPONSE_TOO_LARGE", "模型返回超出本工具的响应大小限制。")
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError()
            choices = payload["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError()
            choice = choices[0]
            content = choice["message"]["content"]
            finish_reason = choice["finish_reason"]
            usage = payload.get("usage", {})
            usage = {k: v for k, v in usage.items() if k in (
                "prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
                     and type(v) is int and v >= 0} if isinstance(usage, dict) else {}
        except (UnicodeError, ValueError, KeyError, TypeError, IndexError):
            raise ModelRequestError("INVALID_API_RESPONSE", "DeepSeek 返回格式无效。") from None
        self.last_call = {"elapsed_seconds": round(time.monotonic() - start, 3), "usage": usage,
                          "finish_reason": finish_reason if isinstance(finish_reason, str) else "invalid"}
        if finish_reason != "stop":
            raise ModelRequestError("API_OUTPUT_INCOMPLETE", "模型输出未正常结束，不能使用截断或被过滤的答案。")
        if not isinstance(content, str) or not content.strip():
            raise ModelRequestError("API_EMPTY_OUTPUT", "DeepSeek 返回空内容，本次核验未完成。")
        # Detailed evidence schema validation remains in semantic_review.parse_review.
        return content
