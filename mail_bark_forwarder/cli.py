from __future__ import annotations

import argparse
import logging

from .config import load_config
from .oauth2 import run_local_oauth_flow
from .service import ForwarderService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Forward verification mail signals to Bark.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--once", action="store_true", help="Process once and exit")
    subparsers = parser.add_subparsers(dest="command")
    oauth = subparsers.add_parser("gmail-oauth", help="Authorize a Gmail account and print OAuth2 config.")
    oauth.add_argument("--client-id", required=True, help="Google OAuth client ID")
    oauth.add_argument("--client-secret", default="", help="Google OAuth client secret, optional for PKCE desktop flow")
    oauth.add_argument("--email", required=True, help="Gmail address to use as the IMAP username")
    oauth.add_argument("--host", default="127.0.0.1", help="Local callback host")
    oauth.add_argument("--port", type=int, default=8765, help="Local callback port")
    oauth.add_argument("--no-browser", action="store_true", help="Print the URL without opening a browser")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "gmail-oauth":
        token = run_local_oauth_flow(
            client_id=args.client_id,
            client_secret=args.client_secret,
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )
        if not token.refresh_token:
            raise RuntimeError("Google did not return a refresh_token. Re-run and approve the consent screen.")
        print()
        print("Add this Gmail account to config.yaml:")
        print(
            f"""  - name: gmail
    host: imap.gmail.com
    port: 993
    username: {args.email}
    auth: oauth2
    oauth2_client_id: ${{GMAIL_CLIENT_ID}}
    oauth2_client_secret: ${{GMAIL_CLIENT_SECRET}}
    oauth2_refresh_token: ${{GMAIL_REFRESH_TOKEN}}
    mailbox: INBOX
    ssl: true
    idle: true
    search: UNSEEN
    since_days: 3
    post_action: mark_seen"""
        )
        print()
        print("Add these values to .env:")
        print(f"GMAIL_CLIENT_ID={args.client_id}")
        print(f"GMAIL_CLIENT_SECRET={args.client_secret}")
        print(f"GMAIL_REFRESH_TOKEN={token.refresh_token}")
        return 0

    config = load_config(args.config)
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    service = ForwarderService(config)
    try:
        if args.once:
            count = service.run_once()
            logging.info("processed one pass, pushed=%d", count)
            return 0
        service.run_forever()
        return 0
    finally:
        service.close()
