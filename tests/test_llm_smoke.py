
import pytest

from agent.llm import MockLLM


def test_mock_llm_returns_scripted_replies():
    llm = MockLLM(["first", "second"])

    assert llm.complete("system", "question") == "first"
    assert llm.complete("system", "question") == "second"


def test_mock_llm_records_calls():
    llm = MockLLM(["response"])

    llm.complete("system prompt", "user prompt")

    assert len(llm.calls) == 1
    assert llm.calls[0]["system"] == "system prompt"
    assert llm.calls[0]["user"] == "user prompt"


def test_mock_llm_records_schema():
    schema = {"type": "object"}

    llm = MockLLM(["{}"])
    llm.complete("system", "user", schema)

    assert llm.calls[0]["schema"] == schema


def test_mock_llm_raises_when_replies_exhausted():
    llm = MockLLM(["only response"])

    llm.complete("system", "user")

    with pytest.raises(RuntimeError):
        llm.complete("system", "user")
