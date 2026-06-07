import tempfile
import unittest
from pathlib import Path

from mail_bark_forwarder.config import load_config


class ConfigTest(unittest.TestCase):
    def test_load_oauth2_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                """
bark:
  device_key: key
accounts:
  - name: gmail
    host: imap.gmail.com
    port: 993
    username: user@example.com
    auth: oauth2
    oauth2_client_id: client
    oauth2_client_secret: secret
    oauth2_refresh_token: refresh
""",
                encoding="utf-8",
            )

            config = load_config(str(config_path))

        self.assertEqual(config.accounts[0].auth, "oauth2")
        self.assertEqual(config.accounts[0].oauth2_refresh_token, "refresh")
        self.assertEqual(config.accounts[0].password, "")

    def test_password_auth_requires_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                """
bark:
  device_key: key
accounts:
  - name: qq
    host: imap.qq.com
    username: user@example.com
    auth: password
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "password is required"):
                load_config(str(config_path))


if __name__ == "__main__":
    unittest.main()
