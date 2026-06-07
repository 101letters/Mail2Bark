from __future__ import annotations

import html
import re
from dataclasses import dataclass
from email.message import Message
from email.policy import default
from email.parser import BytesParser
from html.parser import HTMLParser
from typing import Iterable, List, Optional


CONTEXT_WORDS = (
    "验证码",
    "校验码",
    "动态码",
    "确认码",
    "令牌",
    "登录令牌",
    "输入此令牌",
    "code",
    "verification",
    "verify",
    "otp",
    "login",
    "auth",
    "security",
)
URL_KEYWORDS = (
    "verify",
    "verification",
    "confirm",
    "activate",
    "login",
    "reset",
    "token",
)
CODE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{4,8})(?![A-Za-z0-9])")
URL_RE = re.compile(r"https?://[^\s<>'\"）)】\]。；，、”’]+", re.IGNORECASE)
TRAILING_URL_CHARS = ".,;:。；，、”’)]】"


@dataclass(frozen=True)
class ParsedMail:
    subject: str
    sender: str
    message_id: Optional[str]
    text: str


@dataclass(frozen=True)
class Extraction:
    code: Optional[str]
    link: Optional[str]
    context: str

    @property
    def has_signal(self) -> bool:
        return bool(self.code or self.link)


class TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        tag_name = tag.lower()
        if tag_name == "a":
            href = dict(attrs).get("href")
            if href and href.startswith(("http://", "https://")):
                self.parts.append(f" {href} ")
        if tag_name in {"br", "p", "div", "li", "tr"}:
            self.parts.append("\n")

    def get_text(self) -> str:
        return " ".join(self.parts)


def html_to_text(value: str) -> str:
    parser = TextHTMLParser()
    parser.feed(value)
    return html.unescape(parser.get_text())


def parse_mail(raw: bytes, max_body_chars: int = 8000) -> ParsedMail:
    msg = BytesParser(policy=default).parsebytes(raw)
    subject = str(msg.get("subject", "")).strip()
    sender = str(msg.get("from", "")).strip()
    message_id = str(msg.get("message-id", "")).strip() or None
    text = "\n".join(_iter_text_parts(msg))
    text = normalize_text(text)[:max_body_chars]
    return ParsedMail(subject=subject, sender=sender, message_id=message_id, text=text)


def _iter_text_parts(msg: Message) -> Iterable[str]:
    if msg.is_multipart():
        plain_parts: List[str] = []
        html_parts: List[str] = []
        for part in msg.walk():
            if part.is_multipart():
                continue
            content_type = part.get_content_type()
            if content_type not in {"text/plain", "text/html"}:
                continue
            try:
                content = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                content = payload.decode(charset, errors="replace")
            if content_type == "text/plain":
                plain_parts.append(str(content))
            else:
                html_parts.append(html_to_text(str(content)))
        yield from plain_parts
        yield from html_parts
        return

    content_type = msg.get_content_type()
    if content_type == "text/plain":
        yield str(msg.get_content())
    elif content_type == "text/html":
        yield html_to_text(str(msg.get_content()))


def normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def extract_signals(text: str, context_chars: int = 80) -> Extraction:
    code = choose_code(text)
    link = choose_link(text, code=code)
    context = build_context(text, code, link, context_chars)
    return Extraction(code=code, link=link, context=context)


def choose_link(text: str, code: Optional[str] = None) -> Optional[str]:
    urls = extract_url_candidates(text)
    if not urls:
        return None
    cleaned = urls
    for url in cleaned:
        low = url.lower()
        if _is_ignored_link(low):
            continue
        if code and not _is_strong_verification_link(low):
            continue
        if any(keyword in low for keyword in URL_KEYWORDS):
            return url
    low_text = text.lower()
    for url in cleaned:
        low = url.lower()
        if _is_ignored_link(low):
            continue
        index = text.find(url)
        if index < 0:
            continue
        start = max(0, index - 80)
        end = min(len(text), index + len(url) + 80)
        window = low_text[start:end]
        if code and not _has_link_action_context(window):
            continue
        if _has_link_action_context(window):
            return url
    return None


def _is_strong_verification_link(url: str) -> bool:
    return any(keyword in url for keyword in ("verify", "verification", "confirm", "activate", "token", "accept_wid"))


def _is_ignored_link(url: str) -> bool:
    ignored = (
        "/profile/authentication",
        "account-security",
        "/2fa",
        "facebook.com",
        "linkedin.com",
        "x.com/",
        "community.cloudflare.com",
    )
    return any(part in url for part in ignored)


def _has_link_action_context(window: str) -> bool:
    words = (
        "验证链接",
        "点击",
        "确认链接",
        "激活",
        "接受邀请",
        "接受转发",
        "确认请求",
        "加入工作空间",
        "加入该工作空间",
        "verify",
        "verification",
        "confirm",
        "activate",
        "accept",
        "invite",
    )
    return any(word in window for word in words)


def clean_url(url: str) -> str:
    return url.rstrip(TRAILING_URL_CHARS)


def extract_url_candidates(text: str) -> List[str]:
    urls = []
    seen = set()
    for raw_url in URL_RE.findall(text):
        url = clean_url(raw_url)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _looks_like_css_dimension(code: str) -> bool:
    return bool(re.fullmatch(r"\d+(px|em|rem|vh|vw|pt|pc|in|cm|mm|ex|ch|vmin|vmax)", code.lower()))


def choose_code(text: str) -> Optional[str]:
    candidates = []
    low_text = text.lower()
    for match in CODE_RE.finditer(text):
        code = match.group(1)
        if code.lower() in {"http", "https", "html", "email", "login"}:
            continue
        if _looks_like_css_dimension(code):
            continue
        if code.isdigit() and 1900 <= int(code) <= 2099:
            continue
        if code.isalpha() and len(code) < 6:
            continue
        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 40)
        window = low_text[start:end]
        score = 0
        if any(word in window for word in CONTEXT_WORDS):
            score += 10
        if code.isdigit():
            score += 2
        elif any(char.isdigit() for char in code):
            score += 5
        elif code.isalpha():
            score -= 6
        if 4 <= len(code) <= 6:
            score += 1
        candidates.append((score, match.start(), code))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    if candidates[0][0] < 10:
        return None
    return candidates[0][2]


def build_context(text: str, code: Optional[str], link: Optional[str], width: int) -> str:
    target = code or link
    if target and target in text:
        index = text.index(target)
        start = max(0, index - width)
        end = min(len(text), index + len(target) + width)
        return re.sub(r"\s+", " ", text[start:end]).strip()
    return re.sub(r"\s+", " ", text[: width * 2]).strip()


def format_bark_body(extraction: Extraction) -> str:
    lines = []
    if extraction.code:
        lines.append(f"验证码：{extraction.code}")
    if extraction.link:
        lines.append("点击通知打开链接")
    return "\n".join(lines)
