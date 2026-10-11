import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from astrolol.core.same_origin import SameOriginMiddleware


def make_client(allowed=None) -> TestClient:
    app = FastAPI()
    app.add_middleware(SameOriginMiddleware, allowed_origins=allowed)

    @app.get("/x")
    def get_x():
        return {"ok": True}

    @app.post("/x")
    def post_x():
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        await socket.send_json({"hi": 1})
        await socket.close()

    return TestClient(app, base_url="http://astro.lan:8000")


def test_no_origin_allowed():
    assert make_client().post("/x").status_code == 200


def test_same_origin_allowed():
    c = make_client()
    assert c.post("/x", headers={"Origin": "http://astro.lan:8000"}).status_code == 200


def test_cross_origin_post_rejected_even_for_simple_request():
    r = make_client().post("/x", content="a", headers={"Origin": "http://evil.example", "Content-Type": "text/plain"})
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("origin", ["null", "http://astro.lan", "http://astro.lan:8000.evil.example"])
def test_near_miss_origins_rejected(origin):
    assert make_client().get("/x", headers={"Origin": origin}).status_code == 403


def test_preflight_rejected():
    r = make_client().options("/x", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert r.status_code == 403


def test_explicitly_allowed_origin():
    c = make_client(["https://other.example/"])
    assert c.get("/x", headers={"Origin": "https://other.example"}).status_code == 200


def test_forwarded_host_counts():
    c = make_client()
    r = c.get("/x", headers={"Origin": "https://astro.example", "X-Forwarded-Host": "astro.example"})
    assert r.status_code == 200


def test_websocket_cross_origin_rejected():
    c = make_client()
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws", headers={"Origin": "http://evil.example"}):
            pass


def test_websocket_same_origin_allowed():
    with make_client().websocket_connect("/ws", headers={"Origin": "http://astro.lan:8000", "Host": "astro.lan:8000"}) as ws:
        assert ws.receive_json() == {"hi": 1}
