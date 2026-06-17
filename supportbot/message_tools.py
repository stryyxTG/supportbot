from __future__ import annotations

from aiogram import Bot
from aiogram.types import Message


def content_type_of(message: Message) -> str:
    value = message.content_type
    return getattr(value, "value", str(value))


def text_of(message: Message) -> str:
    return (message.text or message.caption or "").strip()


def file_id_of(message: Message) -> str | None:
    if message.photo:
        return message.photo[-1].file_id
    for attr in (
        "document",
        "video",
        "animation",
        "audio",
        "voice",
        "video_note",
        "sticker",
    ):
        value = getattr(message, attr, None)
        if value:
            return value.file_id
    return None


async def copy_message_safely(
    bot: Bot,
    chat_id: int,
    from_chat_id: int,
    message_id: int,
) -> None:
    try:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
        )
    except Exception:
        try:
            await bot.send_message(chat_id, "Не удалось переслать вложение или сообщение.")
        except Exception:
            return
