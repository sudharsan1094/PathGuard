
import os
from typing import Protocol

from dotenv import load_dotenv
from google import genai


class LLMClient(Protocol):
    """Common interface for all LLM providers."""

    def complete(
        self,
        system: str,
        user: str,
        schema: dict | None = None,
    ) -> str:
        ...


class GeminiClient:
    def __init__(self, model: str | None = None, temperature: float = 0.1):
        import os
        from dotenv import load_dotenv
        from google import genai
        from google.genai import types

        load_dotenv()

        api_key = os.getenv("GEMINI_API_KEY")
        selected_model = model or os.getenv("GEMINI_MODEL")

        if not api_key:
            raise ValueError("GEMINI_API_KEY is missing.")

        if not selected_model:
            raise ValueError("GEMINI_MODEL is missing.")

        self.model = selected_model
        self.temperature = temperature
        self.client = genai.Client(api_key=api_key)
        self.types = types

    def complete(
        self,
        system: str,
        user: str,
        schema: dict | None = None,
    ) -> str:

        config = {
            "system_instruction": system,
            "temperature": self.temperature,
        }

        if schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_schema"] = schema

        response = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config=self.types.GenerateContentConfig(**config),
        )

        if not response.text:
            raise RuntimeError("Gemini returned an empty response.")

        return response.text


class MockLLM:
    """Deterministic LLM replacement for tests."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls = []

    def complete(
        self,
        system: str,
        user: str,
        schema: dict | None = None,
    ) -> str:

        self.calls.append({
            "system": system,
            "user": user,
            "schema": schema,
        })

        if not self.replies:
            raise RuntimeError("MockLLM has no replies remaining.")

        return self.replies.pop(0)
