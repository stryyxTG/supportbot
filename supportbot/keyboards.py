from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from supportbot.texts import ACTIVE_STATUSES, status_title


BTN_NEW_TICKET = "➕ Новое обращение"
BTN_MY_TICKETS = "📄 Мои обращения"
BTN_ADMIN_PANEL = "Админская панель"
BTN_HELP = "Как это работает"


def user_menu() -> object:
    builder = ReplyKeyboardBuilder()
    builder.button(text=BTN_NEW_TICKET)
    builder.button(text=BTN_MY_TICKETS)
    builder.adjust(1, 1)
    return builder.as_markup(
        resize_keyboard=True,
        input_field_placeholder="Нажмите «➕ Новое обращение»",
    )


def admin_menu() -> object:
    builder = ReplyKeyboardBuilder()
    builder.button(text=BTN_ADMIN_PANEL)
    builder.adjust(1)
    return builder.as_markup(
        resize_keyboard=True,
        input_field_placeholder="Откройте админскую панель",
    )


def user_ticket_keyboard(ticket: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    ticket_id = ticket["id"]
    if ticket["status"] in ACTIVE_STATUSES:
        builder.button(text="Написать сюда", callback_data=f"u:reply:{ticket_id}")
        builder.button(text="Закрыть обращение", callback_data=f"u:close:{ticket_id}")
    else:
        builder.button(text="Открыть заново", callback_data=f"u:reopen:{ticket_id}")
    builder.adjust(1)
    return builder.as_markup()


def ticket_list_keyboard(tickets: list[dict], prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ticket in tickets:
        status = status_title(ticket["status"])
        builder.button(
            text=f"№{ticket['public_id']} · {status}",
            callback_data=f"{prefix}:view:{ticket['id']}",
        )
    builder.adjust(1)
    return builder.as_markup()


def user_ticket_list_keyboard(
    tickets: list[dict],
    page: int,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for ticket in tickets:
        status = status_title(ticket["status"])
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📄 №{ticket['public_id']} · {status}",
                    callback_data=f"u:view:{ticket['id']}",
                )
            ]
        )

    nav = []
    if has_prev:
        nav.append(InlineKeyboardButton(text="Назад", callback_data=f"u:list:{page - 1}"))
    nav.append(InlineKeyboardButton(text="Обновить", callback_data=f"u:list:{page}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Дальше", callback_data=f"u:list:{page + 1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="common:cancel")]
        ]
    )
