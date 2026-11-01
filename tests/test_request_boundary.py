import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.request_boundary import Policy, SearchRequest, DiemRequest, mount_boundary
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest


def fixture_app(policy, host="127.0.0.1"):
    app = FastAPI()
    called = []
    mount_boundary(app, policy)

    @app.post("/stream-chat")
    async def chat(value: SearchRequest):
        called.append(value.message)
        return {"ok": True}

    return TestClient(app, client=(host, 40000)), called


def test_foreign_site_never_reaches_provider():
    client, called = fixture_app(Policy(("http://localhost:3000",)))
    assert (
        client.post(
            "/stream-chat",
            json={"message": "hello"},
            headers={"Origin": "https://attacker.example"},
        ).status_code
        == 403
    )
    assert called == []


def test_network_default_closed_and_local_example_works():
    client, called = fixture_app(Policy(("http://localhost:3000",)), host="198.51.100.2")
    assert client.post("/stream-chat", json={"message": "hello"}).status_code == 403
    client, called = fixture_app(Policy(("http://localhost:3000",)))
    assert client.post("/stream-chat", json={"message": "hello"}).status_code == 200
    assert called == ["hello"]


def test_public_api_requires_owned_bearer_and_bounded_body():
    client, called = fixture_app(
        Policy(("https://maps.example",), True, "x" * 40), host="198.51.100.2"
    )
    assert client.post("/stream-chat", json={"message": "hello"}).status_code == 401
    assert (
        client.post(
            "/stream-chat",
            json={"message": "hello"},
            headers={"Authorization": "Bearer " + "x" * 40},
        ).status_code
        == 200
    )
    assert called == ["hello"]
    assert (
        client.post(
            "/stream-chat",
            json={"message": "x" * 20000},
            headers={"Authorization": "Bearer " + "x" * 40},
        ).status_code
        == 413
    )
    assert called == ["hello"]


def test_missing_public_token_fails_configuration(monkeypatch):
    monkeypatch.setenv("GEOSPATIAL_PUBLIC_API", "true")
    monkeypatch.delenv("GEOSPATIAL_API_TOKEN", raising=False)
    with pytest.raises(ValueError):
        Policy.from_env()


@pytest.mark.parametrize(
    "value",
    [
        {"lat": 91, "lng": 0},
        {"lat": 0, "lng": 181},
        {"lat": 0, "lng": 0, "top_k": 1001},
        {"lat": float("nan"), "lng": 0},
    ],
)
def test_coordinate_and_search_work_limits(value):
    with pytest.raises(ValidationError):
        DiemRequest(**value)


def test_message_and_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        SearchRequest(message="x" * 4097)
    with pytest.raises(ValidationError):
        SearchRequest(message="hello", instructions="replace server prompt")


def test_sse_response_remains_complete_after_bounded_body_read():
    from fastapi.responses import StreamingResponse

    app = FastAPI()
    mount_boundary(app, Policy(("http://localhost:3000",)))

    @app.post("/stream-chat")
    async def stream(value: SearchRequest):
        async def events():
            yield "data: first\n\n"
            yield "data: done\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    client = TestClient(app, client=("127.0.0.1", 40000))
    result = client.post("/stream-chat", json={"message": "local fixture"})
    assert result.status_code == 200 and result.text == "data: first\n\ndata: done\n\n"


def test_public_cors_configuration_uses_exact_origins(monkeypatch):
    monkeypatch.setenv("GEOSPATIAL_ALLOWED_ORIGINS", "https://maps.example")
    monkeypatch.setenv("GEOSPATIAL_PUBLIC_API", "true")
    monkeypatch.setenv("GEOSPATIAL_API_TOKEN", "a" * 40)
    assert Policy.from_env().origins == ("https://maps.example",)
    monkeypatch.setenv("GEOSPATIAL_ALLOWED_ORIGINS", "*")
    with pytest.raises(ValueError):
        Policy.from_env()
