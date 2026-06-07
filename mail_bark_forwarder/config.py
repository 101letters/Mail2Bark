from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised by environments without dependencies installed
    yaml = None


@dataclass(frozen=True)
class MailAccount:
    name: str
    host: str
    port: int
    username: str
    password: str = ""
    auth: str = "password"
    oauth2_client_id: str = ""
    oauth2_client_secret: str = ""
    oauth2_refresh_token: str = ""
    oauth2_token_url: str = "https://oauth2.googleapis.com/token"
    mailbox: str = "INBOX"
    ssl: bool = True
    idle: bool = True
    search: str = "UNSEEN"
    subject_contains: Optional[str] = None
    since_days: int = 3
    post_action: str = "mark_seen"
    move_to: Optional[str] = None


@dataclass(frozen=True)
class BarkConfig:
    server: str = "https://api.day.app"
    device_key: str = ""
    group: str = "mail-code"
    sound: Optional[str] = None
    level: Optional[str] = None


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: int = 30
    max_text_chars: int = 6000


@dataclass(frozen=True)
class AppConfig:
    bark: BarkConfig
    accounts: List[MailAccount]
    llm: LLMConfig = LLMConfig()
    poll_interval: int = 30
    state_path: str = "/data/state.sqlite3"
    startup_mark_seen: bool = True
    max_body_chars: int = 8000
    code_context_chars: int = 80
    dry_run: bool = False
    log_level: str = "INFO"
    env_file: Optional[str] = None


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_or_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


def _expand_env(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    return env_or_value(obj)


def load_config(config_path: str) -> AppConfig:
    path = Path(config_path)
    raw: Dict[str, Any] = {}
    if path.exists():
        if yaml is None:
            raise RuntimeError("PyYAML is required to load config.yaml. Install with: pip install -r requirements.txt")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    env_file = raw.get("env_file", ".env")
    load_dotenv(path.parent / env_file)
    raw = _expand_env(raw)

    bark_raw = raw.get("bark", {})
    bark = BarkConfig(
        server=os.environ.get("BARK_SERVER", bark_raw.get("server", "https://api.day.app")).rstrip("/"),
        device_key=os.environ.get("BARK_DEVICE_KEY", bark_raw.get("device_key", "")),
        group=bark_raw.get("group", "mail-code"),
        sound=bark_raw.get("sound"),
        level=bark_raw.get("level"),
    )
    if not bark.device_key:
        raise ValueError("Bark device key is required. Set BARK_DEVICE_KEY or bark.device_key.")

    llm_raw = raw.get("llm", {})
    llm = LLMConfig(
        enabled=bool(llm_raw.get("enabled", False)),
        base_url=os.environ.get("LLM_BASE_URL", llm_raw.get("base_url", "")).rstrip("/"),
        api_key=os.environ.get("LLM_API_KEY", llm_raw.get("api_key", "")),
        model=os.environ.get("LLM_MODEL", llm_raw.get("model", "")),
        timeout=int(llm_raw.get("timeout", 30)),
        max_text_chars=int(llm_raw.get("max_text_chars", 6000)),
    )
    if llm.enabled and not (llm.base_url and llm.api_key and llm.model):
        raise ValueError("LLM is enabled, but base_url/api_key/model is incomplete.")

    accounts = []
    for item in raw.get("accounts", []):
        accounts.append(
            MailAccount(
                name=item["name"],
                host=item["host"],
                port=int(item.get("port", 993 if item.get("ssl", True) else 143)),
                username=item["username"],
                password=item.get("password", ""),
                auth=item.get("auth", "password"),
                oauth2_client_id=item.get("oauth2_client_id", ""),
                oauth2_client_secret=item.get("oauth2_client_secret", ""),
                oauth2_refresh_token=item.get("oauth2_refresh_token", ""),
                oauth2_token_url=item.get("oauth2_token_url", "https://oauth2.googleapis.com/token"),
                mailbox=item.get("mailbox", "INBOX"),
                ssl=bool(item.get("ssl", True)),
                idle=bool(item.get("idle", True)),
                search=item.get("search", "UNSEEN"),
                subject_contains=item.get("subject_contains"),
                since_days=int(item.get("since_days", raw.get("since_days", 3))),
                post_action=item.get("post_action", raw.get("post_action", "mark_seen")),
                move_to=item.get("move_to"),
            )
        )
        if accounts[-1].auth == "password" and not accounts[-1].password:
            raise ValueError(f"password is required for account {accounts[-1].name} when auth=password")
        if accounts[-1].auth == "oauth2" and not (
            accounts[-1].oauth2_client_id
            and accounts[-1].oauth2_refresh_token
        ):
            raise ValueError(
                f"oauth2_client_id/oauth2_refresh_token are required "
                f"for account {accounts[-1].name} when auth=oauth2"
            )
        if accounts[-1].auth not in {"password", "oauth2"}:
            raise ValueError(f"unsupported auth for account {accounts[-1].name}: {accounts[-1].auth}")
    if not accounts:
        raise ValueError("At least one IMAP account is required in accounts[].")

    return AppConfig(
        bark=bark,
        llm=llm,
        accounts=accounts,
        poll_interval=int(raw.get("poll_interval", 30)),
        state_path=raw.get("state_path", os.environ.get("STATE_PATH", "/data/state.sqlite3")),
        startup_mark_seen=bool(raw.get("startup_mark_seen", True)),
        max_body_chars=int(raw.get("max_body_chars", 8000)),
        code_context_chars=int(raw.get("code_context_chars", 80)),
        dry_run=bool(raw.get("dry_run", False)),
        log_level=raw.get("log_level", "INFO"),
        env_file=env_file,
    )
