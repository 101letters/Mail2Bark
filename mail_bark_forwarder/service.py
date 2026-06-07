from __future__ import annotations

import logging
import signal
import threading
from email.utils import parseaddr
from typing import Optional

from .bark import BarkClient, BarkMessage
from .config import AppConfig, MailAccount
from .imap_client import ImapClient
from .llm import LLMClassifier
from .parser import Extraction, extract_signals, extract_url_candidates, format_bark_body, parse_mail
from .state import StateStore

LOGGER = logging.getLogger(__name__)


class ForwarderService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.state = StateStore(config.state_path)
        self.bark = BarkClient(config.bark, dry_run=config.dry_run)
        self.llm = LLMClassifier(config.llm)
        self.stop_event = threading.Event()

    def install_signal_handlers(self) -> None:
        def stop(signum, _frame):
            LOGGER.info("received signal %s, stopping", signum)
            self.stop_event.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

    def run_once(self) -> int:
        total = 0
        for account in self.config.accounts:
            total += self.process_account(account, wait_for_change=False)
        return total

    def run_forever(self) -> None:
        self.install_signal_handlers()
        LOGGER.info("starting Mail2Bark for %d accounts", len(self.config.accounts))
        if self.config.startup_mark_seen:
            self.mark_existing_as_processed()

        threads = [
            threading.Thread(target=self.run_account_loop, args=(account,), name=f"imap-{account.name}", daemon=True)
            for account in self.config.accounts
        ]
        for thread in threads:
            thread.start()
        while not self.stop_event.is_set():
            self.stop_event.wait(1)
        for thread in threads:
            thread.join(timeout=5)

    def run_account_loop(self, account: MailAccount) -> None:
        LOGGER.info("account worker started: %s", account.name)
        while not self.stop_event.is_set():
            self.process_account(account)

    def mark_existing_as_processed(self) -> None:
        for account in self.config.accounts:
            try:
                with ImapClient(account) as client:
                    for item in client.fetch_new(subject_contains=account.subject_contains):
                        parsed = parse_mail(item.raw, self.config.max_body_chars)
                        self.state.mark_processed(account.name, item.uid, parsed.message_id)
                    LOGGER.info("startup marked current matching mail as processed: %s", account.name)
            except Exception:
                LOGGER.exception("failed to mark existing mail for %s", account.name)

    def process_account(self, account: MailAccount, wait_for_change: bool = True) -> int:
        pushed = 0
        try:
            with ImapClient(account) as client:
                items = client.fetch_new(subject_contains=account.subject_contains)
                LOGGER.debug("account=%s fetched %d candidate mails", account.name, len(items))
                for item in items:
                    pushed += self.process_mail(account, item.uid, item.raw, client)
                if wait_for_change and not self.stop_event.is_set():
                    client.wait_for_change(self.config.poll_interval)
        except Exception:
            LOGGER.exception("account processing failed: %s", account.name)
            if wait_for_change:
                self.stop_event.wait(self.config.poll_interval)
        return pushed

    def process_mail(self, account: MailAccount, uid: str, raw: bytes, client: Optional[ImapClient] = None) -> int:
        parsed = parse_mail(raw, self.config.max_body_chars)
        if account.subject_contains and account.subject_contains.lower() not in parsed.subject.lower():
            LOGGER.debug(
                "subject filter skipped: account=%s uid=%s subject=%s",
                account.name,
                uid,
                parsed.subject,
            )
            return 0
        if self.state.is_processed(account.name, uid, parsed.message_id):
            return 0

        extraction = self.classify_mail(parsed)
        if not extraction.has_signal:
            LOGGER.info("no code/link signal: account=%s uid=%s subject=%s", account.name, uid, parsed.subject)
            self.state.mark_processed(account.name, uid, parsed.message_id)
            return 0

        body = format_bark_body(extraction)
        title_kind = signal_title_kind(extraction.code, extraction.link)
        copy_value = extraction.code or None
        self.bark.push(
            BarkMessage(
                title=f"{title_kind} - {display_sender(parsed.sender)}",
                body=body,
                url=extraction.link,
                copy=copy_value,
                auto_copy=bool(copy_value),
            )
        )
        self.state.mark_processed(account.name, uid, parsed.message_id)
        if client:
            client.apply_post_action(uid)
            LOGGER.info("post action applied: account=%s uid=%s action=%s", account.name, uid, account.post_action)
        LOGGER.info("pushed mail signal: account=%s uid=%s subject=%s", account.name, uid, parsed.subject)
        return 1

    def classify_mail(self, parsed) -> Extraction:
        rule_extraction = extract_signals(parsed.text, self.config.code_context_chars)
        urls = extract_url_candidates(parsed.text)
        if rule_extraction.code and not rule_extraction.link:
            return rule_extraction
        if self.llm.enabled and urls:
            decision = self.llm.classify(parsed, urls, rule_extraction)
            if decision is None:
                LOGGER.info("LLM did not return a usable decision; skipping link-only mail")
                return Extraction(code=None, link=None, context="llm unavailable")
            if decision.should_push:
                LOGGER.info("LLM selected signal: kind=%s reason=%s", decision.kind, decision.reason)
                return decision.to_extraction()
            LOGGER.info("LLM rejected mail: reason=%s", decision.reason)
            return Extraction(code=None, link=None, context=decision.reason)
        return rule_extraction

    def close(self) -> None:
        self.state.close()


def first_non_empty(*values: Optional[str]) -> Optional[str]:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def signal_title_kind(code: Optional[str], link: Optional[str]) -> str:
    if code and link:
        return "验证码/验证链接"
    if code:
        return "验证码"
    return "验证链接"


def display_sender(sender: str) -> str:
    name, email = parseaddr(sender)
    return (name or email or sender).strip() or "未知发件人"
