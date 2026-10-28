"""Sign in to YouTube once and save the upload permission in .env.

    python3 -m scripts.youtube_auth

Needs YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env (a free Google
Cloud "Desktop app" OAuth client with YouTube Data API v3 enabled). Your
browser opens Google's own sign-in page; this script never sees your
password. The refresh token it receives is written to .env only and never
printed.
"""

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import secrets
import sys
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

import requests

from app_settings import require_settings
from project_paths import PROJECT_ROOT
from youtube_publisher import TOKEN_URL, UPLOAD_SCOPE


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
ENV_PATH = PROJECT_ROOT / ".env"
SETTING = "YOUTUBE_REFRESH_TOKEN"


def save_env_value(env_path, name, value):
    """Set NAME=value in .env: rewrite its line, or add one at the end."""
    from scripts.publish_scheduled import replace_env_value

    try:
        replace_env_value(env_path, name, value)
    except ValueError:
        text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        if text and not text.endswith("\n"):
            text += "\n"
        env_path.write_text(f"{text}{name}={value}\n", encoding="utf-8")


def _wait_for_code(server, expected_state):
    """Serve one redirect from Google and return its code."""
    found = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            found["state"] = (query.get("state") or [""])[0]
            found["code"] = (query.get("code") or [""])[0]
            found["error"] = (query.get("error") or [""])[0]
            ok = found["code"] and found["state"] == expected_state
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"YouTube is connected. You can close this tab."
                if ok
                else b"Sign-in did not finish. Return to the terminal."
            )

        def log_message(self, *args):
            pass

    server.RequestHandlerClass = Handler
    while "code" not in found:
        server.handle_request()
    if found["error"] or found["state"] != expected_state or not found["code"]:
        raise SystemExit(f"Sign-in was not completed ({found['error'] or 'state mismatch'}).")
    return found["code"]


def main():
    settings = require_settings("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET")
    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = AUTH_URL + "?" + urlencode({
        "client_id": settings["YOUTUBE_CLIENT_ID"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": UPLOAD_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    print("Opening Google sign-in in your browser. Choose the YouTube channel's account.")
    print(f"If it does not open, paste this address into your browser:\n{url}\n")
    webbrowser.open(url)
    code = _wait_for_code(server, state)
    response = requests.post(TOKEN_URL, data={
        "client_id": settings["YOUTUBE_CLIENT_ID"],
        "client_secret": settings["YOUTUBE_CLIENT_SECRET"],
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }, timeout=30)
    data = response.json() if response.content else {}
    if response.status_code >= 400 or not data.get("refresh_token"):
        raise SystemExit(f"Google did not return a refresh token ({data.get('error', response.status_code)}).")
    save_env_value(ENV_PATH, SETTING, data["refresh_token"])
    print(f"Saved {SETTING} in .env. Restart the review page to use YouTube.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
