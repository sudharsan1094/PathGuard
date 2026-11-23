from types import SimpleNamespace

import pytest

from agent.llm import GeminiClient


class FakeModels:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def fake_client(models):
    return SimpleNamespace(models=models)


def test_gemini_records_call_metadata_and_json_schema():
    models = FakeModels(SimpleNamespace(text="{}", usage_metadata=SimpleNamespace(
        prompt_token_count=4, candidates_token_count=2)))
    client = GeminiClient(model="test-model", client=fake_client(models))
    assert client.complete("system", "user", {"type": "object"}) == "{}"
    config = models.calls[0]["config"]
    assert config["response_mime_type"] == "application/json"
    assert config["response_json_schema"] == {"type": "object"}
    assert client.calls[0].prompt_tokens == 4
    assert client.calls[0].attempts == 1


def test_gemini_retries_transient_errors():
    transient = TimeoutError("transient")
    models = FakeModels(transient, SimpleNamespace(text="ok"))
    waits = []
    client = GeminiClient(model="test-model", client=fake_client(models),
                          sleep=waits.append, max_retries=2)
    assert client.complete("system", "user") == "ok"
    assert len(models.calls) == 2
    assert len(waits) == 1
    assert client.calls[0].attempts == 2


def test_gemini_fails_fast_for_non_retryable_errors():
    models = FakeModels(ValueError("bad request"))
    client = GeminiClient(model="test-model", client=fake_client(models))
    with pytest.raises(ValueError, match="bad request"):
        client.complete("system", "user")
    assert len(models.calls) == 1


def test_gemini_empty_response_is_an_error():
    client = GeminiClient(model="test-model", client=fake_client(FakeModels(SimpleNamespace(text=""))))
    with pytest.raises(RuntimeError, match="empty response"):
        client.complete("system", "user")
