from __future__ import annotations

import imaplib
import logging
import select
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.parser import BytesParser
from email.policy import default
from typing import List, Optional

from .config import MailAccount
from .oauth2 import refresh_access_token

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MailItem:
    uid: str
    raw: bytes


class ImapClient:
    def __init__(self, account: MailAccount):
        self.account = account
        self.conn: Optional[imaplib.IMAP4] = None

    def __enter__(self) -> "ImapClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def connect(self) -> None:
        cls = imaplib.IMAP4_SSL if self.account.ssl else imaplib.IMAP4
        self.conn = cls(self.account.host, self.account.port, timeout=20)
        if self.account.auth == "oauth2":
            self._authenticate_oauth2()
        else:
            self.conn.login(self.account.username, self.account.password)
        status, _ = self.conn.select(self.account.mailbox)
        if status != "OK":
            raise RuntimeError(f"cannot select mailbox {self.account.mailbox}")

    def _authenticate_oauth2(self) -> None:
        assert self.conn is not None
        access_token = refresh_access_token(
            self.account.oauth2_client_id,
            self.account.oauth2_client_secret,
            self.account.oauth2_refresh_token,
            self.account.oauth2_token_url,
        )
        auth_string = f"user={self.account.username}\x01auth=Bearer {access_token}\x01\x01"
        self.conn.authenticate("XOAUTH2", lambda _challenge: auth_string.encode("utf-8"))

    def close(self) -> None:
        if not self.conn:
            return
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.conn.logout()
        except Exception:
            pass
        self.conn = None

    def fetch_new(self, subject_contains: Optional[str] = None) -> List[MailItem]:
        assert self.conn is not None
        criteria = self._search_criteria()
        status, data = self.conn.uid("search", None, *criteria)
        if status != "OK":
            raise RuntimeError(f"imap search failed for {self.account.name}: {data!r}")
        uids = data[0].split() if data and data[0] else []
        items = []
        for uid_bytes in uids:
            uid = uid_bytes.decode("ascii", errors="replace")
            if subject_contains and not self._subject_matches(uid, subject_contains):
                continue
            status, msg_data = self.conn.uid("fetch", uid, "(RFC822)")
            if status != "OK":
                LOGGER.warning("failed to fetch uid=%s account=%s", uid, self.account.name)
                continue
            raw = _extract_rfc822(msg_data)
            if raw:
                items.append(MailItem(uid=uid, raw=raw))
        return items

    def apply_post_action(self, uid: str) -> None:
        action = self.account.post_action
        if action == "none":
            return
        if action == "mark_seen":
            self.mark_seen(uid)
            return
        if action == "delete":
            self.delete(uid)
            return
        if action == "move":
            if not self.account.move_to:
                raise ValueError(f"move_to is required when post_action=move for {self.account.name}")
            self.move(uid, self.account.move_to)
            return
        raise ValueError(f"unsupported post_action for {self.account.name}: {action}")

    def mark_seen(self, uid: str) -> None:
        assert self.conn is not None
        status, data = self.conn.uid("store", uid, "+FLAGS", r"(\Seen)")
        if status != "OK":
            raise RuntimeError(f"failed to mark uid={uid} as seen for {self.account.name}: {data!r}")

    def delete(self, uid: str) -> None:
        assert self.conn is not None
        status, data = self.conn.uid("store", uid, "+FLAGS", r"(\Deleted)")
        if status != "OK":
            raise RuntimeError(f"failed to mark uid={uid} deleted for {self.account.name}: {data!r}")
        status, data = self.conn.expunge()
        if status != "OK":
            raise RuntimeError(f"failed to expunge deleted uid={uid} for {self.account.name}: {data!r}")

    def move(self, uid: str, mailbox: str) -> None:
        assert self.conn is not None
        status, data = self.conn.uid("MOVE", uid, mailbox)
        if status == "OK":
            return
        LOGGER.debug("UID MOVE unavailable for %s uid=%s: %r", self.account.name, uid, data)
        status, data = self.conn.uid("COPY", uid, mailbox)
        if status != "OK":
            raise RuntimeError(f"failed to copy uid={uid} to {mailbox} for {self.account.name}: {data!r}")
        self.delete(uid)

    def _search_criteria(self) -> List[str]:
        criteria = [self.account.search]
        if self.account.since_days > 0:
            since = datetime.now() - timedelta(days=self.account.since_days)
            criteria.extend(["SINCE", since.strftime("%d-%b-%Y")])
        return criteria

    def _subject_matches(self, uid: str, subject_contains: str) -> bool:
        assert self.conn is not None
        status, data = self.conn.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
        if status != "OK":
            LOGGER.warning("failed to fetch subject uid=%s account=%s", uid, self.account.name)
            return False
        raw = _extract_rfc822(data)
        if not raw:
            return False
        msg = BytesParser(policy=default).parsebytes(raw)
        subject = str(msg.get("subject", ""))
        return subject_contains.lower() in subject.lower()

    def wait_for_change(self, timeout: int) -> None:
        if not self.account.idle:
            _sleep_with_select(timeout)
            return
        if not self._try_idle(timeout):
            _sleep_with_select(timeout)

    def _try_idle(self, timeout: int) -> bool:
        assert self.conn is not None
        sock = getattr(self.conn, "sock", None)
        if sock is None:
            return False
        try:
            tag = self.conn._command("IDLE")
            ready = select.select([sock], [], [], timeout)[0]
            if ready:
                try:
                    self.conn._get_response()
                except Exception:
                    pass
            sock.sendall(b"DONE\r\n")
            self.conn._command_complete("IDLE", tag)
            return True
        except (imaplib.IMAP4.error, socket.error, OSError) as exc:
            LOGGER.debug("IMAP IDLE unavailable for %s: %s", self.account.name, exc)
            return False


def _extract_rfc822(msg_data) -> Optional[bytes]:
    for item in msg_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def _sleep_with_select(timeout: int) -> None:
    select.select([], [], [], timeout)
