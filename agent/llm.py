from __future__ import annotations

import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


class LLMClient(Protocol):
    def complete(self, system: str, user: str, schema: dict | None = None) -> str: ...


@dataclass(frozen=True)
class LLMCallRecord:
    model: str
    latency_ms: int
    attempts: int = 1
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def _build_client(api_key: str, timeout_s: int) -> tuple[Any, Any]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key,
                          http_options=types.HttpOptions(timeout=timeout_s * 1000))
    return client, types


def _retryable(error: BaseException) -> bool:
    code = getattr(error, "code", None)
    if isinstance(code, int):
        return code in {408, 429, 500, 502, 503, 504}
    return isinstance(error, (TimeoutError, ConnectionError)) or type(error).__name__ in {
        "ReadTimeout", "ConnectTimeout", "ConnectError", "RemoteProtocolError"}


class GeminiClient:
    def __init__(self, model: str | None = None, temperature: float = 0.1, *,
                 api_key: str | None = None, timeout_s: int = 60, max_retries: int = 4,
                 client: Any = None, types: Any = None,
                 sleep: Callable[[float], None] = time.sleep):
        from dotenv import load_dotenv

        load_dotenv()
        self.model = model or os.getenv("GEMINI_MODEL") or ""
        if not self.model:
            raise ValueError("GEMINI_MODEL is missing.")
        key = api_key or os.getenv("GEMINI_API_KEY")
        if client is None and not key:
            raise ValueError("GEMINI_API_KEY is missing.")
        if client is None:
            client, sdk_types = _build_client(key, timeout_s)
            types = types or sdk_types
        self.client, self.types = client, types
        self.temperature = temperature
        self.max_retries = max(0, max_retries)
        self._sleep = sleep
        self.calls: list[LLMCallRecord] = []

    def complete(self, system: str, user: str, schema: dict | None = None) -> str:
        started = time.perf_counter()
        config: dict[str, Any] = {"system_instruction": system, "temperature": self.temperature}
        if schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = schema
        if self.types is not None and hasattr(self.types, "GenerateContentConfig"):
            config = self.types.GenerateContentConfig(**config)
        for attempt in range(1, self.max_retries + 2):
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=user, config=config)
                break
            except Exception as error:
                if attempt > self.max_retries or not _retryable(error):
                    raise
                self._sleep(min(30.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5))
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty response (possibly blocked).")
        usage = getattr(response, "usage_metadata", None)
        self.calls.append(LLMCallRecord(
            model=self.model, latency_ms=int((time.perf_counter() - started) * 1000),
            attempts=attempt, prompt_tokens=getattr(usage, "prompt_token_count", None),
            completion_tokens=getattr(usage, "candidates_token_count", None)))
        return text


class MockLLM:
    """Deterministic provider replacement retained for tests and offline runs."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def complete(self, system: str, user: str, schema: dict | None = None) -> str:
        self.calls.append({"system": system, "user": user, "schema": schema})
        if not self.replies:
            raise RuntimeError("MockLLM has no replies remaining.")
        return self.replies.pop(0)
