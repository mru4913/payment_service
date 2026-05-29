"""Telegram command menu policy."""

from frontend.core.base_bot import (
    PUBLIC_BOT_COMMAND_KEYS,
    TELEGRAM_COMMAND_LANGS,
    _localized_commands,
)
from frontend.core.utils import tr


def test_public_bot_commands_are_dashboard_only() -> None:
    commands = [command for command, _ in PUBLIC_BOT_COMMAND_KEYS]

    assert commands == ["start", "help"]
    assert "compute" not in commands
    assert "recharge" not in commands
    assert "balance" not in commands


def test_help_text_does_not_expose_slash_workflows() -> None:
    text = tr("common.help_text", "zh_hans")

    assert "/compute" not in text
    assert "/recharge" not in text
    assert "/balance" not in text
    assert "/history" not in text
    assert "/lang" not in text
    assert "首页按钮" in text


def test_public_bot_commands_are_localized() -> None:
    assert TELEGRAM_COMMAND_LANGS == (("zh", "zh_hans"), ("en", "en"))
    assert _localized_commands("zh_hans") == (
        ("start", "打开首页"),
        ("help", "帮助"),
    )
    assert _localized_commands("en") == (
        ("start", "Open dashboard"),
        ("help", "Help"),
    )
