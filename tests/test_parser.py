import unittest
from email.message import EmailMessage

from mail_bark_forwarder.parser import Extraction, extract_signals, format_bark_body, parse_mail


class ParserTest(unittest.TestCase):
    def test_plain_chinese_code(self):
        text = "您的验证码是 482913，请勿泄露。"
        extraction = extract_signals(text)
        self.assertEqual(extraction.code, "482913")
        self.assertIsNone(extraction.link)

    def test_english_otp_and_link(self):
        text = "Your OTP code is AB12CD. Verify here: https://example.com/verify?token=abc"
        extraction = extract_signals(text)
        self.assertEqual(extraction.code, "AB12CD")
        self.assertEqual(extraction.link, "https://example.com/verify?token=abc")

    def test_ordinary_link_is_not_signal(self):
        text = "Read our newsletter at https://example.com/news and manage preferences."
        extraction = extract_signals(text)
        self.assertFalse(extraction.has_signal)

    def test_ignores_plain_words_without_context(self):
        extraction = extract_signals("Welcome to product news for June.")
        self.assertFalse(extraction.has_signal)

    def test_html_mail(self):
        msg = EmailMessage()
        msg["Subject"] = "Verify"
        msg["From"] = "noreply@example.com"
        msg["Message-ID"] = "<a@example.com>"
        msg.set_content("<html><body><p>Verification code: 135790</p></body></html>", subtype="html")
        parsed = parse_mail(msg.as_bytes())
        self.assertIn("Verification code", parsed.text)
        self.assertEqual(parsed.message_id, "<a@example.com>")
        self.assertEqual(extract_signals(parsed.text).code, "135790")

    def test_html_anchor_href_is_preserved_for_action_link(self):
        msg = EmailMessage()
        msg["Subject"] = "QQ邮箱自动转发验证邮件"
        msg["From"] = "Example User <sender@example.com>"
        msg.set_content(
            '<html><body>请同意此次请求。<a href="https://mail.qq.com/forward/accept?token=abc">接受转发</a>'
            '<a href="https://mail.qq.com/forward/cancel?token=def">取消接受转发</a></body></html>',
            subtype="html",
        )
        parsed = parse_mail(msg.as_bytes())
        extraction = extract_signals(parsed.text)
        self.assertEqual(extraction.link, "https://mail.qq.com/forward/accept?token=abc")

    def test_multipart_prefers_plain(self):
        msg = EmailMessage()
        msg["Subject"] = "Login"
        msg["From"] = "noreply@example.com"
        msg.set_content("Login code: 246810")
        msg.add_alternative("<html><body>Login code: 111111</body></html>", subtype="html")
        parsed = parse_mail(msg.as_bytes())
        self.assertEqual(extract_signals(parsed.text).code, "246810")

    def test_multipart_includes_html_href_when_plain_has_no_url(self):
        msg = EmailMessage()
        msg["Subject"] = "Forward"
        msg["From"] = "Example User <sender@example.com>"
        msg.set_content("请点击接受转发。")
        msg.add_alternative(
            '<html><body>请点击<a href="https://mail.qq.com/forward/accept?token=abc">接受转发</a></body></html>',
            subtype="html",
        )
        parsed = parse_mail(msg.as_bytes())
        extraction = extract_signals(parsed.text)
        self.assertEqual(extraction.link, "https://mail.qq.com/forward/accept?token=abc")

    def test_format_bark_body_keeps_only_key_content(self):
        self.assertEqual(format_bark_body(Extraction(code="123456", link=None, context="ignored")), "验证码：123456")
        self.assertEqual(
            format_bark_body(Extraction(code=None, link="https://example.com/verify", context="ignored")),
            "点击通知打开链接",
        )
        self.assertEqual(
            format_bark_body(Extraction(code="123456", link="https://example.com/verify", context="ignored")),
            "验证码：123456\n点击通知打开链接",
        )

    def test_cloudflare_login_token_is_code_not_authentication_link(self):
        text = (
            "您的 Cloudflare 登录令牌 有新的登录尝试。"
            "请在验证页面输入此令牌：0333771。"
            "如果不是您本人，请立即更改密码 https://dash.cloudflare.com/profile/authentication"
        )
        extraction = extract_signals(text)
        self.assertEqual(extraction.code, "0333771")
        self.assertIsNone(extraction.link)

    def test_code_email_ignores_ordinary_site_link(self):
        text = "邮箱验证码 请使用以下验证码完成验证：878228。https://airbus.shiomisha.top 此邮件由系统自动发送。"
        extraction = extract_signals(text)
        self.assertEqual(extraction.code, "878228")
        self.assertIsNone(extraction.link)

    def test_forwarded_header_year_is_not_code(self):
        text = (
            "Date: 2026年6月3日周三 12:03\n"
            "Subject: 验证码：490792\n"
            "在 1Password 的验证页面输入此代码以继续注册：\n"
            "490792"
        )
        extraction = extract_signals(text)
        self.assertEqual(extraction.code, "490792")

    def test_chatgpt_invite_prefers_encoded_accept_link(self):
        invite_link = (
            "https://chatgpt.com/auth/login?"
            "inv_ws_name=%E5%85%8D%E8%B4%B9%E4%B8%8A%E8%BD%A6%E7%BD%91%E5%9D%80"
            "https%3A%2F%2Ffuckopenai.net&inv_email=changjie101%40gmail.com"
            "&wId=6b16e4eb-1e83-48b1-ace3-875667fc270f"
            "&accept_wId=6b16e4eb-1e83-48b1-ace3-875667fc270f"
        )
        text = (
            "Emily Walker 已邀请你在工作空间“免费上车网址 https://fuckopenai.net”中使用 ChatGPT Business。"
            f"请点击下方链接，以接受邀请并加入该工作空间。加入工作空间 <{invite_link}> "
            "如有任何疑问，请与我们联系 <https://mandrillapp.com/track/click/help.openai.com?p=x>。"
        )
        extraction = extract_signals(text)
        self.assertEqual(extraction.link, invite_link)

    def test_email_verification_code_prefers_numeric_code_over_css_size(self):
        text = (
            "[发现AI] Email Verification Code\n"
            "<img width=\"40px\" height=\"40px\">\n"
            "Your email verification code is 890668."
        )
        extraction = extract_signals(text)
        self.assertEqual(extraction.code, "890668")


if __name__ == "__main__":
    unittest.main()
