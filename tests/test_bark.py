import json
import unittest
from unittest.mock import patch

from mail_bark_forwarder.bark import BarkClient, BarkMessage
from mail_bark_forwarder.config import BarkConfig


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def read(self):
        return b'{"code":200}'


class BarkClientTest(unittest.TestCase):
    def test_push_payload(self):
        config = BarkConfig(server="https://bark.example", device_key="key", group="mail-code")
        client = BarkClient(config)

        with patch("mail_bark_forwarder.bark.request.urlopen", return_value=FakeResponse()) as urlopen:
            client.push(
                BarkMessage(
                    title="t",
                    subtitle="s",
                    body="b",
                    url="https://example.com/verify",
                    copy="123456",
                    auto_copy=True,
                )
            )

        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "https://bark.example/push")
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["device_key"], "key")
        self.assertEqual(payload["title"], "t")
        self.assertEqual(payload["subtitle"], "s")
        self.assertEqual(payload["body"], "b")
        self.assertEqual(payload["url"], "https://example.com/verify")
        self.assertEqual(payload["copy"], "123456")
        self.assertEqual(payload["autoCopy"], "1")
        self.assertEqual(payload["group"], "mail-code")


if __name__ == "__main__":
    unittest.main()
