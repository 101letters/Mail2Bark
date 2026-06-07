import tempfile
import unittest
from email.message import EmailMessage

from mail_bark_forwarder.config import AppConfig, BarkConfig, MailAccount
from mail_bark_forwarder.service import ForwarderService


class ServiceTest(unittest.TestCase):
    def test_process_mail_pushes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            account = MailAccount(
                name="test",
                host="imap.example.com",
                port=993,
                username="u",
                password="p",
            )
            config = AppConfig(
                bark=BarkConfig(device_key="key"),
                accounts=[account],
                state_path=f"{tmp}/state.sqlite3",
                dry_run=True,
            )
            service = ForwarderService(config)
            pushed = []
            service.bark.push = pushed.append

            msg = EmailMessage()
            msg["Subject"] = "Login"
            msg["From"] = "noreply@example.com"
            msg["Message-ID"] = "<msg@example.com>"
            msg.set_content("Your login code is 123456. https://example.com/login?token=x")

            self.assertEqual(service.process_mail(account, "1", msg.as_bytes()), 1)
            self.assertEqual(service.process_mail(account, "1", msg.as_bytes()), 0)
            self.assertEqual(len(pushed), 1)
            self.assertEqual(pushed[0].title, "验证码/验证链接 - noreply@example.com")
            self.assertIsNone(pushed[0].subtitle)
            self.assertEqual(pushed[0].body, "验证码：123456\n点击通知打开链接")
            self.assertEqual(pushed[0].url, "https://example.com/login?token=x")
            self.assertEqual(pushed[0].copy, "123456")
            self.assertTrue(pushed[0].auto_copy)
            service.close()

    def test_post_action_runs_only_after_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            account = MailAccount(
                name="test",
                host="imap.example.com",
                port=993,
                username="user@example.com",
                password="p",
                post_action="delete",
            )
            config = AppConfig(
                bark=BarkConfig(device_key="key"),
                accounts=[account],
                state_path=f"{tmp}/state.sqlite3",
                dry_run=True,
            )
            service = ForwarderService(config)
            service.bark.push = lambda _message: None

            class FakeClient:
                def __init__(self):
                    self.actions = []

                def apply_post_action(self, uid):
                    self.actions.append(uid)

            client = FakeClient()
            code_msg = EmailMessage()
            code_msg["Subject"] = "Code"
            code_msg["From"] = "noreply@example.com"
            code_msg["Message-ID"] = "<post-action@example.com>"
            code_msg.set_content("验证码：123456")

            no_signal_msg = EmailMessage()
            no_signal_msg["Subject"] = "News"
            no_signal_msg["From"] = "noreply@example.com"
            no_signal_msg["Message-ID"] = "<no-signal@example.com>"
            no_signal_msg.set_content("hello")

            self.assertEqual(service.process_mail(account, "4", code_msg.as_bytes(), client), 1)
            self.assertEqual(service.process_mail(account, "5", no_signal_msg.as_bytes(), client), 0)
            self.assertEqual(client.actions, ["4"])
            service.close()

    def test_link_only_push_opens_url_without_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            account = MailAccount(
                name="test",
                host="imap.example.com",
                port=993,
                username="user@example.com",
                password="p",
            )
            config = AppConfig(
                bark=BarkConfig(device_key="key"),
                accounts=[account],
                state_path=f"{tmp}/state.sqlite3",
                dry_run=True,
            )
            service = ForwarderService(config)
            pushed = []
            service.bark.push = pushed.append

            msg = EmailMessage()
            msg["Subject"] = "Verify"
            msg["From"] = "noreply@example.com"
            msg["Message-ID"] = "<link@example.com>"
            msg.set_content("Verify your account: https://example.com/verify?token=x")

            self.assertEqual(service.process_mail(account, "2", msg.as_bytes()), 1)
            self.assertEqual(len(pushed), 1)
            self.assertEqual(pushed[0].title, "验证链接 - noreply@example.com")
            self.assertEqual(pushed[0].body, "点击通知打开链接")
            self.assertEqual(pushed[0].url, "https://example.com/verify?token=x")
            self.assertIsNone(pushed[0].copy)
            self.assertFalse(pushed[0].auto_copy)
            service.close()

    def test_sender_title_uses_display_name_without_email(self):
        with tempfile.TemporaryDirectory() as tmp:
            account = MailAccount(
                name="test",
                host="imap.example.com",
                port=993,
                username="user@example.com",
                password="p",
            )
            config = AppConfig(
                bark=BarkConfig(device_key="key"),
                accounts=[account],
                state_path=f"{tmp}/state.sqlite3",
                dry_run=True,
            )
            service = ForwarderService(config)
            pushed = []
            service.bark.push = pushed.append

            msg = EmailMessage()
            msg["Subject"] = "Code"
            msg["From"] = "Example Sender <sender@example.com>"
            msg["Message-ID"] = "<sender@example.com>"
            msg.set_content("验证码：0333771")

            self.assertEqual(service.process_mail(account, "3", msg.as_bytes()), 1)
            self.assertEqual(pushed[0].title, "验证码 - Example Sender")
            self.assertEqual(pushed[0].body, "验证码：0333771")
            self.assertEqual(pushed[0].copy, "0333771")
            service.close()


if __name__ == "__main__":
    unittest.main()
