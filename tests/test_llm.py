import unittest

from mail_bark_forwarder.llm import LLMDecision, parse_decision, validate_decision


class LLMTest(unittest.TestCase):
    def test_parse_json_fenced_decision(self):
        decision = parse_decision(
            '```json\n{"should_push": true, "kind": "link", "code": null, "url": "https://example.com/v", "reason": "确认链接"}\n```'
        )
        self.assertTrue(decision.should_push)
        self.assertEqual(decision.kind, "link")
        self.assertEqual(decision.url, "https://example.com/v")

    def test_validate_drops_fabricated_values(self):
        decision = validate_decision(
            LLMDecision(True, "code_and_link", "999999", "https://evil.example", "bad"),
            mail_text="验证码：123456",
            urls=["https://example.com/verify"],
        )
        self.assertFalse(decision.should_push)
        self.assertIsNone(decision.code)
        self.assertIsNone(decision.url)

    def test_validate_accepts_present_code_and_candidate_url(self):
        decision = validate_decision(
            LLMDecision(True, "code_and_link", "123456", "https://example.com/verify", "ok"),
            mail_text="验证码：123456 https://example.com/verify",
            urls=["https://example.com/verify"],
        )
        self.assertTrue(decision.should_push)
        self.assertEqual(decision.code, "123456")
        self.assertEqual(decision.url, "https://example.com/verify")


if __name__ == "__main__":
    unittest.main()
