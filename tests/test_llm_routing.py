import pytest

from skills import llm


def test_local_qwen_routes_by_task_and_requests_json_schema(monkeypatch):
    payloads = []
    monkeypatch.setattr(llm, "USE_LOCAL_LLM", True)
    monkeypatch.setattr(llm, "LOCAL_LLM_MODELS", {"regime": "qwen-regime:3b"})
    monkeypatch.setattr(llm.requests, "post", lambda *args, **kwargs: (
        payloads.append(kwargs["json"])
        or type("Response", (), {
            "status_code": 200,
            "json": lambda self: {"message": {"content": '{"ok": true}'}},
        })()
    ))

    response = llm._ask_local_qwen(
        "return JSON",
        "system",
        128,
        task="regime",
        response_schema={"type": "object"},
    )

    assert response == '{"ok": true}'
    assert payloads[0]["model"] == "qwen-regime:3b"
    assert payloads[0]["format"] == {"type": "object"}


def test_ask_json_rejects_non_json(monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda *args, **kwargs: "not json")

    with pytest.raises(ValueError):
        llm.ask_json("prompt", schema={"type": "object"})
