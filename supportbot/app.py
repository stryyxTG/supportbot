from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from supportbot.config import Settings, normalize_username
from supportbot.db import Database
from supportbot.keyboards import (
    BTN_ADMIN_PANEL,
    BTN_MY_TICKETS,
    BTN_NEW_TICKET,
    admin_menu,
    cancel_keyboard,
    ticket_list_keyboard,
    user_menu,
    user_ticket_keyboard,
    user_ticket_list_keyboard,
)
from supportbot.message_tools import content_type_of, file_id_of, text_of
from supportbot.states import NewTicket, UserReply
from supportbot.texts import (
    ACTIVE_STATUSES,
    CLOSED_STATUSES,
    admin_incoming_card,
    h,
    pe,
    user_ticket_card,
)
from supportbot.webapp import RealtimeHub, start_web_app


logger = logging.getLogger(__name__)
TICKET_PAGE_SIZE = 7


def is_admin(settings: Settings, tg_user_or_id: object) -> bool:
    if isinstance(tg_user_or_id, int):
        return tg_user_or_id in settings.admin_ids
    user_id = getattr(tg_user_or_id, "id", None)
    username = normalize_username(getattr(tg_user_or_id, "username", None))
    return user_id in settings.admin_ids or username in settings.admin_usernames


def parse_callback_id(data: str) -> int:
    return int(data.rsplit(":", 1)[1])


def admin_webapp_keyboard(settings: Settings) -> InlineKeyboardMarkup | None:
    if not settings.webapp_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BTN_ADMIN_PANEL,
                    web_app=WebAppInfo(url=settings.webapp_url),
                )
            ]
        ]
    )


async def send_admin_home(message: Message, settings: Settings) -> None:
    if not settings.webapp_url:
        await message.answer(
            (
                "<b>Админ-панель перенесена в Mini App.</b>\n"
                "Укажите WEBAPP_URL в .env, потом перезапустите бота."
            ),
            reply_markup=admin_menu(),
        )
        return
    await message.answer(
        "<b>Админ-панель</b>\nНижняя кнопка оставлена только для админа.",
        reply_markup=admin_menu(),
    )
    await message.answer(
        "Откройте Mini App кнопкой ниже.",
        reply_markup=admin_webapp_keyboard(settings),
    )


async def send_home(message: Message, settings: Settings) -> None:
    if is_admin(settings, message.from_user):
        await send_admin_home(message, settings)
        return
    await message.answer(
        (
            f"{pe('star')} <b>{h(settings.support_title)}</b>\n"
            f"{pe('plus')} Нажмите «Новое обращение» и напишите проблему одним сообщением."
        ),
        reply_markup=user_menu(),
    )


async def show_user_tickets(
    message: Message,
    db: Database,
    user_id: int,
    page: int = 0,
) -> None:
    page = max(page, 0)
    total = await db.count_user_tickets(user_id)
    offset = page * TICKET_PAGE_SIZE
    tickets = await db.list_user_tickets(
        user_id,
        limit=TICKET_PAGE_SIZE,
        offset=offset,
    )
    if not tickets:
        await message.answer(
            f"{pe('doc')} У вас пока нет обращений.",
            reply_markup=user_menu(),
        )
        return
    await message.answer(
        f"{pe('folder')} <b>Ваши обращения</b>\nСтраница {page + 1} · всего: <b>{total}</b>",
        reply_markup=user_ticket_list_keyboard(
            tickets=tickets,
            page=page,
            has_prev=page > 0,
            has_next=offset + len(tickets) < total,
        ),
    )


async def notify_admins_about_ticket(
    bot: Bot,
    settings: Settings,
    db: Database,
    ticket: dict,
    source_message: Message | None,
    title: str,
) -> None:
    data = await db.get_ticket_with_user(ticket["id"])
    if data is None:
        return
    fresh_ticket, user = data
    body = text_of(source_message) if source_message is not None else ""
    content_type = content_type_of(source_message) if source_message is not None else "service"
    markup = admin_webapp_keyboard(settings)
    recipients = set(settings.admin_ids)
    for admin_user in await db.list_users_by_usernames(settings.admin_usernames):
        recipients.add(int(admin_user["tg_id"]))
    for admin_id in recipients:
        try:
            await bot.send_message(
                admin_id,
                admin_incoming_card(title, fresh_ticket, user, body, content_type),
                reply_markup=markup,
            )
        except Exception as exc:
            logger.warning("Cannot notify admin %s: %s", admin_id, exc)


async def create_ticket_from_message(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
    realtime: RealtimeHub,
) -> None:
    user = await db.upsert_user(message.from_user)
    if user.get("is_blocked"):
        await message.answer(f"{pe('question')} Доступ к поддержке ограничен.")
        await state.clear()
        return

    active_count = await db.count_user_active_tickets(message.from_user.id)
    if active_count >= settings.max_open_tickets:
        await message.answer(
            (
                f"{pe('folder')} У вас уже есть несколько активных обращений. "
                "Закройте решенные тикеты или напишите в существующий."
            ),
            reply_markup=user_menu(),
        )
        await state.clear()
        return

    ticket = await db.create_ticket(user["id"])
    await db.add_message(
        ticket_id=ticket["id"],
        sender_role="user",
        sender_tg_id=message.from_user.id,
        body=text_of(message),
        content_type=content_type_of(message),
        file_id=file_id_of(message),
        telegram_message_id=message.message_id,
    )
    ticket = await db.set_status(
        ticket["id"],
        "waiting_admin",
        "user",
        message.from_user.id,
        "first_message_received",
    )
    await state.clear()

    await message.answer(
        (
            f"{pe('doc')} Обращение <b>№{h(ticket['public_id'])}</b> создано.\n"
            "Оператор ответит здесь. Чтобы добавить детали, просто напишите следующим сообщением."
        ),
        reply_markup=user_ticket_keyboard(ticket),
    )
    await notify_admins_about_ticket(
        bot,
        settings,
        db,
        ticket,
        message,
        "Новый тикет",
    )
    await realtime.publish("ticket_changed", ticket_id=ticket["id"], reason="new_ticket")


async def add_user_reply(
    message: Message,
    ticket: dict,
    db: Database,
    settings: Settings,
    bot: Bot,
    realtime: RealtimeHub,
) -> None:
    if ticket["status"] in CLOSED_STATUSES:
        await message.answer(
            f"{pe('question')} Это обращение закрыто. Откройте его заново или создайте новое.",
            reply_markup=user_ticket_keyboard(ticket),
        )
        return

    await db.add_message(
        ticket_id=ticket["id"],
        sender_role="user",
        sender_tg_id=message.from_user.id,
        body=text_of(message),
        content_type=content_type_of(message),
        file_id=file_id_of(message),
        telegram_message_id=message.message_id,
    )
    next_status = (
        "in_progress"
        if ticket["status"] in {"in_progress", "waiting_user"} or ticket.get("assigned_admin_id")
        else "waiting_admin"
    )
    ticket = await db.set_status(
        ticket["id"],
        next_status,
        "user",
        message.from_user.id,
        "user_replied",
    )
    await message.answer(
        f"{pe('send')} Добавил в обращение <b>№{h(ticket['public_id'])}</b>.",
        reply_markup=user_ticket_keyboard(ticket),
    )
    await notify_admins_about_ticket(
        bot,
        settings,
        db,
        ticket,
        message,
        "Новое сообщение в тикете",
    )
    await realtime.publish("ticket_changed", ticket_id=ticket["id"], reason="user_replied")


def build_router(db: Database, settings: Settings, realtime: RealtimeHub) -> Router:
    router = Router()

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        await db.upsert_user(message.from_user)
        await send_home(message, settings)

    @router.message(Command("id"))
    async def my_id(message: Message) -> None:
        await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")

    @router.message(Command("admin"))
    async def admin(message: Message) -> None:
        await db.upsert_user(message.from_user)
        if not is_admin(settings, message.from_user):
            await message.answer("У вас нет доступа к админ-панели.")
            return
        await send_admin_home(message, settings)

    @router.message(F.text == BTN_ADMIN_PANEL)
    async def admin_panel_button(message: Message) -> None:
        await db.upsert_user(message.from_user)
        if not is_admin(settings, message.from_user):
            await message.answer("У вас нет доступа к админ-панели.", reply_markup=user_menu())
            return
        await send_admin_home(message, settings)

    @router.message(F.text.in_({BTN_NEW_TICKET, "Новое обращение"}))
    async def new_ticket(message: Message, state: FSMContext) -> None:
        if is_admin(settings, message.from_user):
            await send_admin_home(message, settings)
            return
        await db.upsert_user(message.from_user)
        await state.set_state(NewTicket.waiting_message)
        await message.answer(
            (
                f"{pe('plus')} <b>Новое обращение</b>\n"
                f"{pe('camera')} Напишите, что случилось. Можно сразу приложить фото, файл или голосовое."
            ),
            reply_markup=cancel_keyboard(),
        )

    @router.message(F.text.in_({BTN_MY_TICKETS, "Мои обращения"}))
    async def my_tickets(message: Message) -> None:
        if is_admin(settings, message.from_user):
            await send_admin_home(message, settings)
            return
        await db.upsert_user(message.from_user)
        await show_user_tickets(message, db, message.from_user.id)

    @router.message(NewTicket.waiting_message)
    async def new_ticket_message(
        message: Message,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        await create_ticket_from_message(message, state, db, settings, bot, realtime)

    @router.message(UserReply.waiting_message)
    async def user_reply_message(
        message: Message,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        data = await state.get_data()
        ticket_id = int(data["ticket_id"])
        ticket = await db.get_ticket(ticket_id)
        await state.clear()
        if ticket is None:
            await message.answer("Обращение не найдено.", reply_markup=user_menu())
            return
        await add_user_reply(message, ticket, db, settings, bot, realtime)

    @router.callback_query(F.data == "common:cancel")
    async def cancel(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer("Отменено")
        await callback.message.answer("Действие отменено.", reply_markup=user_menu())

    @router.callback_query(F.data == "u:list")
    async def user_list_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        await show_user_tickets(callback.message, db, callback.from_user.id)

    @router.callback_query(F.data.startswith("u:list:"))
    async def user_list_page_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        page = int(callback.data.rsplit(":", 1)[1])
        await show_user_tickets(callback.message, db, callback.from_user.id, page)

    @router.callback_query(F.data.startswith("u:view:"))
    async def user_view_ticket(callback: CallbackQuery) -> None:
        await callback.answer()
        ticket_id = parse_callback_id(callback.data)
        ticket = await db.get_ticket(ticket_id)
        user = await db.get_user_by_tg_id(callback.from_user.id)
        if ticket is None or not user or ticket["user_id"] != user["id"]:
            await callback.message.answer(f"{pe('question')} Обращение не найдено.")
            return
        await callback.message.answer(
            user_ticket_card(ticket),
            reply_markup=user_ticket_keyboard(ticket),
        )

    @router.callback_query(F.data.startswith("u:reply:"))
    async def user_reply_callback(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        ticket_id = parse_callback_id(callback.data)
        ticket = await db.get_ticket(ticket_id)
        user = await db.get_user_by_tg_id(callback.from_user.id)
        if ticket is None or not user or ticket["user_id"] != user["id"]:
            await callback.message.answer(f"{pe('question')} Обращение не найдено.")
            return
        await state.set_state(UserReply.waiting_message)
        await state.update_data(ticket_id=ticket_id)
        await callback.message.answer(
            f"{pe('send')} Напишите сообщение для обращения <b>№{h(ticket['public_id'])}</b>.",
            reply_markup=cancel_keyboard(),
        )

    @router.callback_query(F.data.startswith("u:close:"))
    async def user_close_callback(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer()
        ticket_id = parse_callback_id(callback.data)
        ticket_data = await db.get_ticket_with_user(ticket_id)
        user = await db.get_user_by_tg_id(callback.from_user.id)
        if ticket_data is None or not user:
            await callback.message.answer(f"{pe('question')} Обращение не найдено.")
            return
        ticket, _ = ticket_data
        if ticket["user_id"] != user["id"]:
            await callback.message.answer(f"{pe('question')} Обращение не найдено.")
            return
        ticket = await db.set_status(
            ticket_id,
            "closed",
            "user",
            callback.from_user.id,
            "closed_by_user",
        )
        await callback.message.answer(
            f"{pe('doc')} Обращение <b>№{h(ticket['public_id'])}</b> закрыто.",
            reply_markup=user_ticket_keyboard(ticket),
        )
        await notify_admins_about_ticket(
            bot,
            settings,
            db,
            ticket,
            None,
            "Пользователь закрыл тикет",
        )
        await realtime.publish("ticket_changed", ticket_id=ticket_id, reason="user_closed")

    @router.callback_query(F.data.startswith("u:reopen:"))
    async def user_reopen_callback(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer()
        ticket_id = parse_callback_id(callback.data)
        ticket = await db.get_ticket(ticket_id)
        user = await db.get_user_by_tg_id(callback.from_user.id)
        if ticket is None or not user or ticket["user_id"] != user["id"]:
            await callback.message.answer(f"{pe('question')} Обращение не найдено.")
            return
        ticket = await db.set_status(
            ticket_id,
            "waiting_admin",
            "user",
            callback.from_user.id,
            "reopened_by_user",
        )
        await callback.message.answer(
            f"{pe('doc')} Обращение <b>№{h(ticket['public_id'])}</b> снова открыто.",
            reply_markup=user_ticket_keyboard(ticket),
        )
        await notify_admins_about_ticket(
            bot,
            settings,
            db,
            ticket,
            None,
            "Пользователь переоткрыл тикет",
        )
        await realtime.publish("ticket_changed", ticket_id=ticket_id, reason="user_reopened")

    @router.callback_query(F.data.startswith("a:"))
    async def removed_admin_callbacks(callback: CallbackQuery) -> None:
        await callback.answer("Админ-панель теперь в Mini App", show_alert=True)
        if is_admin(settings, callback.from_user):
            await send_admin_home(callback.message, settings)

    @router.message()
    async def fallback_message(message: Message, bot: Bot) -> None:
        await db.upsert_user(message.from_user)
        if is_admin(settings, message.from_user):
            await send_admin_home(message, settings)
            return

        ticket = await db.get_single_active_ticket(message.from_user.id)
        if ticket is not None:
            await add_user_reply(message, ticket, db, settings, bot, realtime)
            return

        tickets = await db.list_user_tickets(message.from_user.id)
        active = [ticket for ticket in tickets if ticket["status"] in ACTIVE_STATUSES]
        if active:
            await message.answer(
                f"{pe('folder')} У вас несколько активных обращений. Выберите, куда добавить сообщение:",
                reply_markup=ticket_list_keyboard(active, "u"),
            )
            return

        await message.answer(
            f"{pe('plus')} Нажмите «Новое обращение» в меню снизу и опишите проблему.",
            reply_markup=user_menu(),
        )

    return router


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    db = Database(settings.database_path)
    await db.init()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    realtime = RealtimeHub()
    dispatcher.include_router(build_router(db, settings, realtime))

    runner = await start_web_app(bot, db, settings, realtime)
    logger.info(
        "Admin Mini App server started on %s:%s",
        settings.webapp_host,
        settings.webapp_port,
    )
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot)
    finally:
        await runner.cleanup()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
