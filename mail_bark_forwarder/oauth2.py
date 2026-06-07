from __future__ import annotations

import json
import base64
import hashlib
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib import error, parse, request

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SCOPE = "https://mail.google.com/"


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    expires_in: int = 3600
    refresh_token: Optional[str] = None


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str, token_url: str = GOOGLE_TOKEN_URL) -> str:
    params = {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if client_secret:
        params["client_secret"] = client_secret
    payload = parse.urlencode(params).encode("utf-8")
    req = request.Request(
        token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google token refresh failed: HTTP {exc.code} {body}") from exc
    return str(data["access_token"])


def exchange_code_for_token(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    token_url: str = GOOGLE_TOKEN_URL,
) -> TokenResponse:
    params = {
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    if client_secret:
        params["client_secret"] = client_secret
    payload = parse.urlencode(params).encode("utf-8")
    req = request.Request(
        token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google token exchange failed: HTTP {exc.code} {body}") from exc
    return TokenResponse(
        access_token=str(data["access_token"]),
        expires_in=int(data.get("expires_in", 3600)),
        refresh_token=data.get("refresh_token"),
    )


def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: Optional[str] = None,
    scope: str = GMAIL_SCOPE,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    query = parse.urlencode(
        params
    )
    return f"{GOOGLE_AUTH_URL}?{query}"


def run_local_oauth_flow(
    client_id: str,
    client_secret: str,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> TokenResponse:
    state = secrets.token_urlsafe(24)
    code_verifier = _new_code_verifier()
    code_challenge = _code_challenge(code_verifier)
    redirect_uri = f"http://{host}:{port}/oauth2callback"
    auth_url = build_authorization_url(client_id, redirect_uri, state, code_challenge=code_challenge)
    server = _OAuthServer((host, port), _CallbackHandler, expected_state=state)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print("Open this URL in your browser to authorize Gmail IMAP access:")
    print(auth_url)
    if open_browser:
        webbrowser.open(auth_url)

    deadline = time.time() + 300
    while thread.is_alive() and time.time() < deadline:
        time.sleep(0.1)
    if thread.is_alive():
        server.server_close()
        raise TimeoutError("OAuth callback timed out after 300 seconds")
    if server.error:
        raise RuntimeError(server.error)
    if not server.code:
        raise RuntimeError("OAuth callback did not include an authorization code")
    return exchange_code_for_token(client_id, client_secret, server.code, redirect_uri, code_verifier)


def _new_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]


def _code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class _OAuthServer(HTTPServer):
    def __init__(self, server_address, handler_class, expected_state: str):
        super().__init__(server_address, handler_class)
        self.expected_state = expected_state
        self.code: Optional[str] = None
        self.error: Optional[str] = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = parse.urlparse(self.path)
        params = parse.parse_qs(parsed.query)
        state = params.get("state", [""])[0]
        if state != self.server.expected_state:
            self.server.error = "OAuth state mismatch"
            self._respond(400, "Authorization failed. You can close this window.")
            return
        if "error" in params:
            self.server.error = params["error"][0]
            self._respond(400, "Authorization failed. You can close this window.")
            return
        self.server.code = params.get("code", [""])[0]
        self._respond(200, "Authorization complete. You can close this window.")

    def log_message(self, format, *args) -> None:
        return

    def _respond(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
