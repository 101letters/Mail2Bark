from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib import request

from .config import LLMConfig
from .parser import Extraction, ParsedMail

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMDecision:
    should_push: bool
    kind: str
    code: Optional[str]
    url: Optional[str]
    reason: str = ""

    def to_extraction(self) -> Extraction:
        return Extraction(code=self.code, link=self.url, context=self.reason)


class LLMClassifier:
    def __init__(self, config: LLMConfig):
        self.config = config

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def classify(self, parsed: ParsedMail, urls: List[str], rule_extraction: Extraction) -> Optional[LLMDecision]:
        if not self.enabled:
            return None

        prompt = build_prompt(parsed, urls, rule_extraction, self.config.max_text_chars)
        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是邮件验证码和验证链接分类器。只返回 JSON，不要解释。"
                        "你必须只从给定 url_candidates 中选择 url；不能编造 URL。"
                        "验证码 code 必须是邮件原文中出现的短码。广告、账单、营销、帮助、退订、社交链接应 should_push=false。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "stream": False,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.config.base_url}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout) as response:
                response_body = response.read().decode("utf-8", errors="replace")
        except Exception:
            LOGGER.exception("LLM classification request failed")
            return None

        try:
            parsed_body = json.loads(response_body)
            content = parsed_body["choices"][0]["message"]["content"]
            decision = parse_decision(content)
            return validate_decision(decision, parsed.text, urls)
        except Exception:
            LOGGER.exception("LLM classification response parse failed")
            LOGGER.debug("raw LLM response: %s", response_body)
            return None


def build_prompt(parsed: ParsedMail, urls: List[str], rule_extraction: Extraction, max_text_chars: int) -> str:
    body = parsed.text[:max_text_chars]
    return json.dumps(
        {
            "task": "判断这封邮件是否应该推送到 Bark。只推送验证码、登录令牌、验证链接、确认链接、接受邀请、接受转发等动作邮件。",
            "return_schema": {
                "should_push": "boolean",
                "kind": "code | link | code_and_link | none",
                "code": "string|null",
                "url": "string|null，必须完全等于 url_candidates 里的某一项",
                "reason": "short string",
            },
            "subject": parsed.subject,
            "sender": parsed.sender,
            "url_candidates": urls,
            "rule_guess": {
                "code": rule_extraction.code,
                "url": rule_extraction.link,
            },
            "mail_text": body,
        },
        ensure_ascii=False,
    )


def parse_decision(content: str) -> LLMDecision:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()
    data = json.loads(content)
    return LLMDecision(
        should_push=bool(data.get("should_push")),
        kind=str(data.get("kind") or "none"),
        code=data.get("code") or None,
        url=data.get("url") or None,
        reason=str(data.get("reason") or ""),
    )


def validate_decision(decision: LLMDecision, mail_text: str, urls: List[str]) -> LLMDecision:
    code = decision.code
    url = decision.url
    if code and code not in mail_text:
        LOGGER.warning("LLM returned code not present in mail text; dropping code")
        code = None
    if url and url not in urls:
        LOGGER.warning("LLM returned URL not present in candidates; dropping URL")
        url = None
    should_push = decision.should_push and bool(code or url)
    kind = decision.kind if should_push else "none"
    return LLMDecision(should_push=should_push, kind=kind, code=code, url=url, reason=decision.reason)
