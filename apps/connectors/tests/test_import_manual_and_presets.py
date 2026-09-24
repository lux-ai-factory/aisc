def test_manual_builds_an_operation_with_a_response_schema():
    from aisc_connectors.importers.manual import import_manual
    from aisc_connectors.model import operations

    result = import_manual("POST", "http://172.17.0.1:8500/score", '{"amount_eur": 2500}',
                           '{"recommendation": "Approve", "score": 812}', operation_id="score")
    op = operations(result.document)[0]
    assert op.operation_id == "score"
    schema = op.spec["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["properties"]["score"] == {"type": "integer"}


def test_the_openai_preset_suggests_a_chat_mapping():
    from aisc_connectors.importers.presets import openai
    from aisc_connectors.model import operations

    result = openai("https://llm.acme.test/v1", model="acme-7b")
    ids = {o.operation_id for o in operations(result.document)}
    assert ids == {"chat_completions", "list_models"}
    assert result.document["servers"] == [{"url": "https://llm.acme.test/v1"}]
    assert result.chat_suggestion == {"operation_id": "chat_completions", "input_mode": "messages",
                                      "input_field": "messages", "answer_path": "choices[0].message.content",
                                      "extra_body": {"model": "acme-7b"}}
    assert result.auth_suggestion == {"scheme": "bearer"}


def test_the_ollama_and_huggingface_presets():
    from aisc_connectors.importers.presets import huggingface, ollama

    o = ollama("http://gpu.acme.test:11434", model="llama3.1")
    assert o.chat_suggestion["answer_path"] == "message.content"
    assert o.chat_suggestion["extra_body"] == {"model": "llama3.1", "stream": False}
    h = huggingface("https://api-inference.huggingface.co/models/acme/model")
    assert h.chat_suggestion["input_mode"] == "text"
    assert h.chat_suggestion["answer_path"] == "[0].generated_text"
