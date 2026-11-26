import os
import re
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import httpx

BASIC = "instagram_business_basic"
PUBLISH = "instagram_business_content_publish"
FIELDS = "id,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp"
GRAPH = "https://graph.instagram.com"


class MetaError(Exception):
    def __init__(self, message, code=0, wait=0, uncertain=False):
        super().__init__(message)
        self.code = code
        self.wait = wait
        self.uncertain = uncertain


class Instagram:
    def __init__(self, client=None):
        self.client = client or httpx.Client(timeout=30, trust_env=False)
        self.version = os.getenv("META_API_VERSION", "v27.0")
        if not re.fullmatch(r"v\d+\.\d+", self.version):
            raise ValueError("Invalid META_API_VERSION")

    @property
    def redirect(self):
        return os.environ["PUBLIC_URL"].rstrip("/") + "/api/instagram/callback"

    def authorize(self, state, source_only=False):
        return "https://www.instagram.com/oauth/authorize?" + urlencode({
            "client_id": os.environ["META_APP_ID"], "redirect_uri": self.redirect,
            "response_type": "code", "scope": BASIC if source_only else f"{BASIC},{PUBLISH}",
            "state": state, "enable_fb_login": "false", "force_reauth": "true",
        })

    def request(self, method, url, **kwargs):
        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise MetaError("Instagram response unavailable", uncertain=True) from None
        try:
            body = response.json()
        except ValueError:
            if not response.is_error:
                raise MetaError("Instagram returned an unreadable response", uncertain=True) from None
            body = {}
        if response.is_error or isinstance(body, dict) and "error" in body:
            error = body.get("error", {}) if isinstance(body, dict) else {}
            code = error.get("code", response.status_code) if isinstance(error, dict) else response.status_code
            if not isinstance(code, int):
                code = response.status_code
            retry = response.headers.get("Retry-After", "")
            wait = 900 if code in (4, 17, 32, 88, 613, 429) or response.status_code == 429 else 0
            if retry:
                try:
                    wait = max(1, int(retry) if retry.isdigit() else
                               int(parsedate_to_datetime(retry).timestamp() - time.time()))
                except (TypeError, ValueError, OverflowError):
                    pass
            raise MetaError(f"Instagram rejected the request (HTTP {response.status_code}, code {code})",
                            code, wait, response.status_code >= 500)
        return body

    def graph(self, token, node, method="GET", **fields):
        if not re.fullmatch(r"[a-zA-Z0-9_]+(?:/[a-zA-Z0-9_]+)?", node):
            raise MetaError("Invalid Instagram object identifier")
        return self.request(method, f"{GRAPH}/{self.version}/{node}",
                            headers={"Authorization": f"Bearer {token}"},
                            **({"params": fields} if method == "GET" else {"json": fields}))

    def exchange(self, code):
        data = {
            "client_id": os.environ["META_APP_ID"], "client_secret": os.environ["META_APP_SECRET"],
            "grant_type": "authorization_code", "redirect_uri": self.redirect, "code": code,
        }
        short = self.request("POST", "https://api.instagram.com/oauth/access_token",
                             files={key: (None, value) for key, value in data.items()})
        if "data" in short:
            short = short["data"][0]
        long = self.request("GET", GRAPH + "/access_token", params={
            "grant_type": "ig_exchange_token", "client_secret": os.environ["META_APP_SECRET"],
            "access_token": short["access_token"],
        })
        profile = self.graph(long["access_token"], "me", fields="user_id,username,profile_picture_url")
        if "data" in profile:
            profile = profile["data"][0]
        scopes = short.get("permissions") or []
        return long, profile, [value.strip() for value in scopes.split(",")] if isinstance(scopes, str) else scopes

    def refresh(self, token):
        return self.request("GET", GRAPH + "/refresh_access_token",
                            params={"grant_type": "ig_refresh_token", "access_token": token})

    def quota(self, token, account):
        return self.graph(token, f"{account}/content_publishing_limit",
                          fields="quota_usage,config")["data"][0]

    def pages(self, token, node, fields):
        after = None
        seen = set()
        while True:
            params = {"fields": fields, "limit": 50}
            if after:
                params["after"] = after
            page = self.graph(token, node, **params)
            yield from page.get("data", [])
            paging = page.get("paging", {})
            after = paging.get("cursors", {}).get("after")
            if not paging.get("next") or not after:
                return
            if after in seen:
                raise MetaError("Instagram returned a repeated pagination cursor")
            seen.add(after)
