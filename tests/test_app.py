from io import BytesIO
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db import Account, Asset, Media, Publish, Session
from app.main import app
from app.meta import BASIC, PUBLISH
from app.security import cipher, signature
from app.worker import publish


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="http://localhost:5173") as test_client:
        yield test_client


def sign_in(client):
    result = client.post("/api/login", headers={"Origin": "http://localhost:5173"},
                         json={"username": "admin", "password": "integration-test-password"})
    assert result.status_code == 200, result.text
    assert "HttpOnly" in result.headers["Set-Cookie"]
    return {"Origin": "http://localhost:5173", "X-CSRF-Token": result.json()["csrf"]}


def test_login_csrf_and_rate_limit(client):
    assert client.get("/api/dashboard").status_code == 401
    assert client.post("/api/import", content=b"malformed upload").status_code == 401
    credible = {"username": "admin", "password": "integration-test-password"}
    assert client.post("/api/login", json=credible).status_code == 403
    headers = sign_in(client)
    assert client.get("/api/dashboard").json()["settings"]["dry_run"]
    assert client.post("/api/logout").status_code == 403
    assert client.post("/api/logout", headers=headers).status_code == 200
    assert client.get("/api/dashboard").status_code == 401
    for _ in range(8):
        wrong = {**credible, "password": "wrong"}
        assert client.post("/api/login", json=wrong, headers=headers).status_code == 401
    assert client.post("/api/login", json=credible, headers=headers).status_code == 429
    from sqlalchemy import delete
    from app.db import System
    with Session.begin() as db:
        db.execute(delete(System))


def create_accounts():
    with Session.begin() as db:
        accounts = [Account(ig_id=str(index), username=name, scopes=scopes,
                            token=cipher().encrypt(b"not-for-frontend").decode(), expires=time.time() + 10000)
                    for index, name, scopes in [(10, "source.one", [BASIC]), (11, "destination", [BASIC, PUBLISH])]]
        db.add_all(accounts)
        db.flush()
        return [a.id for a in accounts]


def test_source_import_preview_and_dry_run(client):
    headers = sign_in(client)
    _, destination = create_accounts()
    data = {"profile": "https://www.instagram.com/source.one/", "destinations": [destination],
            "kinds": ["IMAGE", "REELS"], "existing": False}
    result = client.post("/api/sources", json=data, headers=headers)
    assert result.status_code == 200, result.text
    assert client.post("/api/sources", json=data, headers=headers).status_code == 409
    assert client.post("/api/sources", json={**data, "profile": "unauthorized"}, headers=headers).status_code == 422
    assert client.get("/api/instagram/callback", params={"state": "wrong", "code": "ignored"}).status_code == 403
    assert client.get("/api/schema").status_code == 200
    first, second = BytesIO(), BytesIO()
    Image.new("RGB", (400, 400), "green").save(first, format="PNG")
    Image.new("RGB", (400, 400), "blue").save(second, format="PNG")
    response = client.post("/api/import", headers=headers, data={"account_id": destination, "authorized": True},
                           files=[("files", ("one.png", first.getvalue(), "image/png")),
                                  ("files", ("two.png", second.getvalue(), "image/png"))])
    assert response.status_code == 200, response.text
    with Session() as db:
        media = db.get(Media, response.json()["id"])
        assert media.kind == "CAROUSEL_ALBUM"
        asset, other = list(db.scalars(select(Asset).where(Asset.media_id == media.id).order_by(Asset.position)))
        job = db.scalar(select(Publish).where(Publish.media_id == media.id))
    assert asset.checksum != other.checksum
    assert client.get(f"/api/preview/{asset.id}").headers["content-type"] == "image/jpeg"
    deadline = int(time.time()) + 60
    url = f"/media/{asset.filename}?until={deadline}&sig="
    assert client.get(url + "x" * 64).status_code == 404
    assert client.head(url + signature(asset.filename, deadline)).status_code == 200
    assert client.get(url + signature(asset.filename, deadline), headers={"Range": "bytes=0-9"}).status_code == 206
    assert client.post(f"/api/queue/{job.id}", headers=headers, json={"action": "publish"}).status_code == 200
    publish(job.id)
    dashboard = client.get("/api/dashboard")
    assert "not-for-frontend" not in dashboard.text
    assert dashboard.json()["counts"]["dry_run"] == 1
