import json
import unittest
from unittest.mock import patch

from mail_bark_forwarder.oauth2 import build_authorization_url, refresh_access_token


class OAuth2Test(unittest.TestCase):
    def test_build_authorization_url_requests_offline_gmail_scope(self):
        url = build_authorization_url("client", "http://127.0.0.1:8765/oauth2callback", "state")

        self.assertIn("access_type=offline", url)
        self.assertIn("prompt=consent", url)
        self.assertIn("scope=https%3A%2F%2Fmail.google.com%2F", url)

    def test_refresh_access_token_posts_refresh_grant(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def read(self):
                return json.dumps({"access_token": "access"}).encode("utf-8")

        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["body"] = req.data.decode("utf-8")
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("mail_bark_forwarder.oauth2.request.urlopen", fake_urlopen):
            token = refresh_access_token("client", "secret", "refresh")

        self.assertEqual(token, "access")
        self.assertEqual(captured["url"], "https://oauth2.googleapis.com/token")
        self.assertIn("grant_type=refresh_token", captured["body"])
        self.assertIn("client_id=client", captured["body"])
        self.assertIn("client_secret=secret", captured["body"])
        self.assertIn("refresh_token=refresh", captured["body"])


if __name__ == "__main__":
    unittest.main()
