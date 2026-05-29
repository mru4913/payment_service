"""Dashboard entry UI."""

from frontend.bot.keyboards import (
    dashboard_keyboard,
    language_keyboard,
    my_account_keyboard,
    pagination_keyboard,
)
from frontend.bot.dashboard_view import account_text, dashboard_text
from frontend.core.utils import tr


def test_dashboard_text_is_localized() -> None:
    zh = dashboard_text(
        "zh_hans",
        name="Hannah",
        created=False,
    )
    en = dashboard_text("en", name="Hannah", created=False)

    assert "Eshow" in zh
    assert "👇 从下面 6 个入口开始" in zh
    assert "账号：<code>123</code>" not in zh
    assert "🎭 <b>AI 换脸</b>" in zh
    assert "🖌 <b>去水印 / 去 Logo</b>" in zh
    assert "Start with one of these 6 actions" in en
    assert "🎭 <b>AI Face Swap</b>" in en
    assert "🖌 <b>Remove Watermark / Logo</b>" in en


def test_dashboard_keyboard_contains_main_actions() -> None:
    markup = dashboard_keyboard("zh_hans")
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]

    assert callbacks == [
        "dashboard:my",
        "dashboard:recharge",
        "dashboard:compute",
        "dashboard:remove_watermark",
        "dashboard:batch",
        "dashboard:help",
    ]
    labels = [
        button.text
        for row in markup.inline_keyboard
        for button in row
    ]
    assert labels == [
        "👤 我的",
        "💳 充值",
        "🎭 AI 换脸",
        "🖌 去水印 / 去 Logo",
        "📦 去水印 / 去 Logo 批量处理",
        "❓ 帮助",
    ]


def test_my_account_text_and_keyboard() -> None:
    text = account_text(
        "zh_hans",
        telegram_id=123,
        balance="5.000000",
        available="4.500000",
        held="0.500000",
    )
    markup = my_account_keyboard("zh_hans")
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]

    assert "👤 <b>我的</b>" in text
    assert "账号：<code>123</code>" in text
    assert "总余额：<b>5</b> USD" in text
    assert "可用余额：4.5 USD" in text
    labels = [
        button.text
        for row in markup.inline_keyboard
        for button in row
    ]
    assert callbacks == [
        "dashboard:history",
        "dashboard:task_history",
        "dashboard:lang",
        "dashboard:home",
    ]
    assert labels == ["📋 交易记录", "🗂 任务历史", "🌐 语言设置", "↩️ 返回"]


def test_history_entry_order_is_time_content_amount() -> None:
    text = tr(
        "history.entry",
        "zh_hans",
        time="2026-05-18 10:28",
        icon="⚡",
        type_name="算力消费",
        amount="-0.05",
    )

    assert text == "2026-05-18 10:28 | ⚡ 算力消费 | -0.05 USD"


def test_history_pagination_uses_angle_buttons() -> None:
    assert tr("history.prev", "zh_hans") == "《"
    assert tr("history.next", "zh_hans") == "》"


def test_task_history_entry_order_is_id_time_type_status() -> None:
    text = tr(
        "task_history.entry",
        "zh_hans",
        code="791CC7EE",
        time="2026-05-18 10:28",
        type="face_swap",
        status="succeeded",
    )

    assert text == "<code>791CC7EE</code> | 2026-05-18 10:28 | face_swap | succeeded"


def test_task_type_labels_are_localized() -> None:
    assert tr("task_type.face_swap", "zh_hans") == "AI 换脸"
    assert tr("task_type.remove_watermark", "zh_hans") == "去水印 / 去 Logo"


def test_history_keyboard_has_pagination_and_back() -> None:
    first = pagination_keyboard(
        1,
        2,
        "history_page",
        "zh_hans",
        back_callback="dashboard:my",
    )
    middle = pagination_keyboard(
        2,
        3,
        "history_page",
        "zh_hans",
        back_callback="dashboard:my",
    )

    assert [button.text for row in first.inline_keyboard for button in row] == [
        "》",
        "↩️ 返回",
    ]
    assert [button.text for row in middle.inline_keyboard for button in row] == [
        "《",
        "》",
        "↩️ 返回",
    ]


def test_language_keyboard_can_return_to_account() -> None:
    markup = language_keyboard("zh_hans", back_callback="dashboard:my")

    labels = [button.text for row in markup.inline_keyboard for button in row]
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]

    assert labels == ["简体中文", "繁體中文", "English", "↩️ 返回"]
    assert callbacks == ["lang:zh_hans", "lang:zh_hant", "lang:en", "dashboard:my"]
