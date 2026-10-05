import copy
import json

import pytest


def _doc(server_url: str, title: str, path: str, method: str, op_id: str) -> dict:
    return {"openapi": "3.1.0", "info": {"title": title, "version": "1"},
            "servers": [{"url": server_url}],
            "paths": {path: {method: {
                "operationId": op_id, "summary": "",
                "x-aisc-binding": {"protocol": "http", "method": method, "path": path, "static_headers": {}},
                "responses": {"200": {"description": "ok"}}}}}}


# --- one_operation: URL userinfo (item 1) ---

def test_url_userinfo_is_stripped_from_server_and_title_and_becomes_basic_auth():
    from aisc_connectors.importers.build import one_operation

    result = one_operation("GET", "https://svc:s3cr3t@host.test/x", {}, None, None, "get_x")

    assert result.document["servers"] == [{"url": "https://host.test"}]
    assert result.document["info"]["title"] == "host.test"
    assert result.auth_suggestion == {"scheme": "basic", "username": "svc"}
    assert result.detected_secrets == {"password": "s3cr3t"}
    assert "s3cr3t" not in json.dumps(result.document)


def test_url_userinfo_defers_to_an_authorization_header_that_already_set_auth():
    from aisc_connectors.importers.build import one_operation

    result = one_operation("GET", "https://svc:s3cr3t@host.test/x",
                           {"Authorization": "Bearer tok-1"}, None, None, "get_x")

    assert result.auth_suggestion == {"scheme": "bearer"}
    assert result.detected_secrets == {"token": "tok-1"}
    assert result.document["servers"] == [{"url": "https://host.test"}]
    assert "s3cr3t" not in json.dumps(result.document)


# --- one_operation: query-string credentials (item 2) ---

def test_query_string_api_key_is_extracted_and_not_declared_as_a_parameter():
    from aisc_connectors.importers.build import one_operation

    result = one_operation("GET", "https://host.test/x?api_key=abc123&lang=en", {}, None, None, "get_x")

    op = result.document["paths"]["/x"]["get"]
    assert [p["name"] for p in op.get("parameters", [])] == ["lang"]
    assert result.auth_suggestion == {"scheme": "api_key", "in": "query", "name": "api_key"}
    assert result.detected_secrets == {"api_key": "abc123"}
    assert "abc123" not in json.dumps(result.document)


def test_query_string_credential_names_are_recognised_case_insensitively():
    from aisc_connectors.importers.build import one_operation

    result = one_operation("GET", "https://host.test/x?Token=zzz", {}, None, None, "get_x")

    assert result.auth_suggestion == {"scheme": "api_key", "in": "query", "name": "Token"}
    assert result.detected_secrets == {"api_key": "zzz"}
    assert "parameters" not in result.document["paths"]["/x"]["get"]


# --- one_operation: malformed Basic header (item 3) ---

def test_a_malformed_basic_header_is_refused_with_import_failed():
    from aisc_connectors.importers.build import one_operation
    from aisc_connectors.importers.errors import ImportFailed

    with pytest.raises(ImportFailed, match="Basic"):
        one_operation("GET", "https://host.test/x", {"Authorization": "Basic not-base64!!"}, None, None, "get_x")


# --- merge (item 5) ---

def test_merge_takes_info_from_the_first_result_on_the_chosen_server_not_results_zero():
    from aisc_connectors.importers import ImportResult
    from aisc_connectors.importers.build import merge

    minority = ImportResult(document=_doc("https://a.test", "Minority API", "/x", "get", "get_x"))
    majority_first = ImportResult(document=_doc("https://b.test", "Majority API", "/y", "get", "get_y"))
    majority_second = ImportResult(document=_doc("https://b.test", "Should Not Win", "/z", "get", "get_z"))

    out = merge([minority, majority_first, majority_second])

    assert out.document["servers"] == [{"url": "https://b.test"}]
    assert out.document["info"]["title"] == "Majority API"


def test_merge_keeps_the_first_operation_on_a_duplicate_path_and_method_and_warns():
    from aisc_connectors.importers import ImportResult
    from aisc_connectors.importers.build import merge

    first = ImportResult(document=_doc("https://b.test", "B", "/y", "get", "first_op"))
    dup = ImportResult(document=_doc("https://b.test", "B", "/y", "get", "second_op"))

    out = merge([first, dup])

    op = out.document["paths"]["/y"]["get"]
    assert op["operationId"] == "first_op"
    assert any("second_op" in w for w in out.warnings)


def test_merge_does_not_mutate_the_input_results():
    from aisc_connectors.importers import ImportResult
    from aisc_connectors.importers.build import merge

    first = ImportResult(document=_doc("https://b.test", "B", "/y", "get", "call"))
    second = ImportResult(document=_doc("https://b.test", "B", "/z", "get", "call"))
    snapshot_first = copy.deepcopy(first.document)
    snapshot_second = copy.deepcopy(second.document)

    out = merge([first, second])

    assert first.document == snapshot_first
    assert second.document == snapshot_second
    ids = {op["operationId"] for item in out.document["paths"].values() for op in item.values()}
    assert ids == {"call", "call_"}
