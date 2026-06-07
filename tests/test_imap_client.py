import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from mail_bark_forwarder.config import MailAccount
from mail_bark_forwarder.imap_client import ImapClient


class ImapClientTest(unittest.TestCase):
    def test_search_criteria_adds_since_days(self):
        account = MailAccount(
            name="qq",
            host="imap.qq.com",
            port=993,
            username="u",
            password="p",
            search="UNSEEN",
            since_days=3,
        )
        client = ImapClient(account)

        class FixedDatetime:
            @staticmethod
            def now():
                return datetime(2026, 6, 3)

        with patch("mail_bark_forwarder.imap_client.datetime", FixedDatetime):
            criteria = client._search_criteria()

        self.assertEqual(criteria, ["UNSEEN", "SINCE", "31-May-2026"])

    def test_connect_uses_oauth2_authenticate(self):
        account = MailAccount(
            name="gmail",
            host="imap.gmail.com",
            port=993,
            username="user@example.com",
            auth="oauth2",
            oauth2_client_id="client",
            oauth2_client_secret="secret",
            oauth2_refresh_token="refresh",
        )
        fake_conn = MagicMock()
        fake_conn.select.return_value = ("OK", [b""])

        with patch("mail_bark_forwarder.imap_client.imaplib.IMAP4_SSL", return_value=fake_conn), patch(
            "mail_bark_forwarder.imap_client.refresh_access_token", return_value="access"
        ):
            ImapClient(account).connect()

        fake_conn.login.assert_not_called()
        fake_conn.authenticate.assert_called_once()
        mechanism, callback = fake_conn.authenticate.call_args.args
        self.assertEqual(mechanism, "XOAUTH2")
        self.assertEqual(callback(None), b"user=user@example.com\x01auth=Bearer access\x01\x01")


if __name__ == "__main__":
    unittest.main()
