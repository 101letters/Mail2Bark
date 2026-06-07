from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional
from urllib import request

from .config import BarkConfig

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BarkMessage:
    title: str
    body: str
    subtitle: Optional[str] = None
    url: Optional[str] = None
    copy: Optional[str] = None
    auto_copy: bool = False


class BarkClient:
    def __init__(self, config: BarkConfig, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run

    def push(self, message: BarkMessage) -> None:
        payload = {
            "device_key": self.config.device_key,
            "title": message.title,
            "body": message.body,
            "group": self.config.group,
        }
        if message.subtitle:
            payload["subtitle"] = message.subtitle
        if message.url:
            payload["url"] = message.url
        if message.copy:
            payload["copy"] = message.copy
        if message.auto_copy:
            payload["autoCopy"] = "1"
        if self.config.sound:
            payload["sound"] = self.config.sound
        if self.config.level:
            payload["level"] = self.config.level

        if self.dry_run:
            LOGGER.info("dry-run Bark push: %s", payload)
            return

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.config.server}/push",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=15) as response:
            body = response.read().decode("utf-8", errors="replace")
            if response.status >= 400:
                raise RuntimeError(f"Bark push failed: HTTP {response.status}: {body}")
            LOGGER.debug("Bark push response: %s", body)
