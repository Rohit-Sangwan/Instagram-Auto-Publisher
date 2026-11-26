from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.meta import BASIC, PUBLISH, Instagram, MetaError


def test_oauth_exchange_and_refresh(monkeypatch):
    monkeypatch.setenv("META_APP_ID", "123")
    monkeypatch.setenv("META_APP_SECRET", "dummy-secret")
    monkeypatch.setenv("PUBLIC_URL", "https://publisher.example")
    calls = []

    def mock(request):
        calls.append(request.url.path)
        if request.url.host == "api.instagram.com":
            assert request.method == "POST"
            assert request.headers["Content-Type"].startswith("multipart/form-data")
            assert b"authorization_code" in request.content
            return httpx.Response(200, json={"data": [{"access_token": "short", "user_id": "42",
                                                       "permissions": f"{BASIC},{PUBLISH}"}]})
        if request.url.path == "/access_token":
            assert request.url.params["grant_type"] == "ig_exchange_token"
            return httpx.Response(200, json={"access_token": "long", "expires_in": 5_184_000})
        if request.url.path == "/refresh_access_token":
            assert request.url.params["grant_type"] == "ig_refresh_token"
            return httpx.Response(200, json={"access_token": "renewed", "expires_in": 5_184_000})
        assert request.headers["Authorization"] == "Bearer long"
        return httpx.Response(200, json={"data": [{"user_id": "42", "username": "authorized"}]})

    with httpx.Client(transport=httpx.MockTransport(mock)) as http:
        api = Instagram(http)
        auth = parse_qs(urlsplit(api.authorize("unique-state")).query)
        assert auth["state"] == ["unique-state"]
        assert auth["scope"] == [f"{BASIC},{PUBLISH}"]
        assert auth["redirect_uri"] == ["https://publisher.example/api/instagram/callback"]
        credentials, profile, scopes = api.exchange("one-time-code")
        assert profile["username"] == "authorized"
        assert scopes == [BASIC, PUBLISH]
        assert api.refresh(credentials["access_token"])["access_token"] == "renewed"
    assert calls[0] == "/oauth/access_token" and len(calls) == 4


def test_api_retry_after_http_date():
    from datetime import timedelta
    retry = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=70), usegmt=True)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        429, headers={"Retry-After": retry}, json={"error": {"code": 4, "message": "sensitive remote detail"}}
    ))) as http:
        with pytest.raises(MetaError) as error:
            Instagram(http).graph("fake-token", "1/media", "POST", image_url="https://publisher.example/image")
    assert 60 <= error.value.wait <= 70
    assert "sensitive" not in str(error.value) and not error.value.uncertain
