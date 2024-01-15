from typing import Any, Optional

from aqt import mw as mw_optional
from aqt.main import AnkiQt
from aqt.utils import showWarning


def assert_is_not_none(optional: Optional[Any]) -> Any:
    if optional is None:
        raise Exception("Unexpected None")
    return optional


mw: AnkiQt = assert_is_not_none(mw_optional)

VERSION = "0.1.0"
CONFIG_VERSION = 0


class Config:
    answer_field: str
    config_version: int
    max_retries: int
    openai_api_key: str
    question: str
    request_options: str
    tag: str
    timeout: int

    def __init__(
        self,
        answer_field: str,
        config_version: int,
        max_retries: int,
        openai_api_key: str,
        question: str,
        request_options: str,
        tag: str,
        timeout: int,
    ):
        self.answer_field = answer_field
        self.config_version = config_version
        self.max_retries = max_retries
        self.openai_api_key = openai_api_key
        self.question = question
        self.request_options = request_options
        self.tag = tag
        self.timeout = timeout

    def write(self) -> None:
        mw.addonManager.writeConfig(
            __name__,
            {
                "answer_field": self.answer_field,
                "config_version": self.config_version,
                "max_retries": self.max_retries,
                "openai_api_key": self.openai_api_key,
                "question": self.question,
                "request_options": self.request_options,
                "tag": self.tag,
                "timeout": self.timeout,
            },
        )


def parse_config(config: dict[str, Any]) -> Config:
    config_version = config.get("config_version") or 0
    if config_version > CONFIG_VERSION:
        raise Exception(
            f"`config_version' {config_version} too new "
            f"(expecting <= {CONFIG_VERSION})"
        )

    answer_field = config.get("answer_field") or ""
    max_retries = config.get("max_retries") or 5
    openai_api_key = config.get("openai_api_key") or ""
    question = config.get("question") or ""
    request_options = config.get("request_options") or '{"model": "gpt-3.5-turbo"}'
    tag = config.get("tag") or "soothsayer"
    timeout = config.get("timeout") or 5

    return Config(
        answer_field=answer_field,
        config_version=config_version,
        max_retries=max_retries,
        openai_api_key=openai_api_key,
        question=question,
        request_options=request_options,
        tag=tag,
        timeout=timeout,
    )


def load_config() -> Config:
    return parse_config(assert_is_not_none(mw.addonManager.getConfig(__name__)))


def show_update_nag() -> None:
    showWarning(
        "Soothsayer has been updated, and your configuration is out of date. "
        + "Please review the README and update your configuration file."
    )
