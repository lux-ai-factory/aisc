def test_a_json_post_becomes_one_operation():
    from aisc_connectors.importers.curl import import_curl
    from aisc_connectors.model import operations

    result = import_curl(
        "curl -s -X POST https://api.acme.test/v1/chat?lang=en "
        "-H 'Content-Type: application/json' -H 'X-Tenant: 42' "
        "-H 'Authorization: Bearer sk-secret-123' -d '{\"question\": \"hi\"}'"
    )
    op = operations(result.document)[0]
    assert result.document["servers"] == [{"url": "https://api.acme.test"}]
    assert (op.method, op.path, op.operation_id) == ("post", "/v1/chat", "post_v1_chat")
    assert op.binding["static_headers"] == {"X-Tenant": "42"}
    assert op.spec["requestBody"]["content"]["application/json"]["example"] == {"question": "hi"}
    assert op.spec["parameters"] == [{"in": "query", "name": "lang", "required": False,
                                      "schema": {"type": "string"}, "example": "en"}]
    assert result.auth_suggestion == {"scheme": "bearer"}
    assert result.detected_secrets == {"token": "sk-secret-123"}
    assert "sk-secret-123" not in str(result.document)


def test_data_without_method_is_a_form_post():
    from aisc_connectors.importers.curl import import_curl
    from aisc_connectors.model import operations

    op = operations(import_curl("curl https://h.test/login --data 'a=1&b=2'").document)[0]
    assert op.method == "post"
    assert "application/x-www-form-urlencoded" in op.spec["requestBody"]["content"]


def test_user_flag_is_basic_auth():
    from aisc_connectors.importers.curl import import_curl

    result = import_curl("curl -u svc:pa55 https://h.test/x")
    assert result.auth_suggestion == {"scheme": "basic", "username": "svc"}
    assert result.detected_secrets == {"password": "pa55"}


def test_api_key_headers_are_recognised():
    from aisc_connectors.importers.curl import import_curl

    result = import_curl("curl https://h.test/x -H 'x-api-key: abc'")
    assert result.auth_suggestion == {"scheme": "api_key", "in": "header", "name": "x-api-key"}
    assert result.detected_secrets == {"api_key": "abc"}


def test_json_flag_and_line_continuations():
    from aisc_connectors.importers.curl import import_curl
    from aisc_connectors.model import operations

    op = operations(import_curl("curl https://h.test/x \\\n  --json '{\"a\": 1}'").document)[0]
    assert op.method == "post"
    assert op.spec["requestBody"]["content"]["application/json"]["schema"] == {
        "type": "object", "properties": {"a": {"type": "integer"}}}


def test_repeated_data_flags_are_joined_with_ampersand():
    from aisc_connectors.importers.curl import import_curl
    from aisc_connectors.model import operations

    op = operations(import_curl("curl https://h.test/x -d 'a=1' -d 'b=2'").document)[0]
    assert op.spec["requestBody"]["content"]["application/x-www-form-urlencoded"]["example"] == {"a": "1", "b": "2"}


def test_not_a_curl_command_is_refused():
    import pytest

    from aisc_connectors.importers.curl import import_curl
    from aisc_connectors.importers.errors import ImportFailed

    with pytest.raises(ImportFailed):
        import_curl("wget https://h.test")
