import unittest
from unittest.mock import MagicMock

from mail_bark_forwarder.config import MailAccount
from mail_bark_forwarder.imap_client import ImapClient


class ImapPostActionTest(unittest.TestCase):
    def test_delete_marks_deleted_and_expunges(self):
        client = ImapClient(MailAccount(name="a", host="h", port=993, username="u", password="p", post_action="delete"))
        client.conn = MagicMock()
        client.conn.uid.return_value = ("OK", [])
        client.conn.expunge.return_value = ("OK", [])

        client.apply_post_action("42")

        client.conn.uid.assert_called_once_with("store", "42", "+FLAGS", r"(\Deleted)")
        client.conn.expunge.assert_called_once_with()

    def test_mark_seen_sets_seen_flag(self):
        client = ImapClient(
            MailAccount(name="a", host="h", port=993, username="u", password="p", post_action="mark_seen")
        )
        client.conn = MagicMock()
        client.conn.uid.return_value = ("OK", [])

        client.apply_post_action("42")

        client.conn.uid.assert_called_once_with("store", "42", "+FLAGS", r"(\Seen)")


if __name__ == "__main__":
    unittest.main()
