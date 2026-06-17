from __future__ import annotations

from html import escape


STATUS_TITLES = {
    "new": "новое",
    "in_progress": "в работе",
    "waiting_user": "ожидает пользователя",
    "waiting_admin": "ожидает оператора",
    "resolved": "решено",
    "closed": "закрыто",
}


ACTIVE_STATUSES = {"new", "in_progress", "waiting_user", "waiting_admin"}
CLOSED_STATUSES = {"resolved", "closed"}

PREMIUM_EMOJI = {
    "star": '<tg-emoji emoji-id="5870801633104891858">⭐️</tg-emoji>',
    "plus": '<tg-emoji emoji-id="5870741379008698885">➕</tg-emoji>',
    "send": '<tg-emoji emoji-id="5873225338984599714">📤</tg-emoji>',
    "user": '<tg-emoji emoji-id="5870994129244131212">👤</tg-emoji>',
    "camera": '<tg-emoji emoji-id="5870856037455630084">📷</tg-emoji>',
    "folder": '<tg-emoji emoji-id="5870570722778156940">📁</tg-emoji>',
    "doc": '<tg-emoji emoji-id="5873153278023307367">📄</tg-emoji>',
    "mic": '<tg-emoji emoji-id="5873146865637133757">🎤</tg-emoji>',
    "eyes": '<tg-emoji emoji-id="5870903672937911120">👀</tg-emoji>',
    "question": '<tg-emoji emoji-id="5872996816659681395">❓</tg-emoji>',
}


def h(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def pe(name: str) -> str:
    return PREMIUM_EMOJI[name]


def status_title(status: str) -> str:
    return STATUS_TITLES.get(status, status)


def user_label(user: dict) -> str:
    name = " ".join(
        part for part in [user.get("first_name"), user.get("last_name")] if part
    ).strip()
    username = user.get("username")
    bits = [name or "Без имени"]
    if username:
        bits.append(f"@{username}")
    bits.append(f"id:{user.get('tg_id')}")
    return " · ".join(bits)


def compact_user_label(user: dict) -> str:
    username = user.get("username")
    if username:
        return f"@{username}"
    name = " ".join(
        part for part in [user.get("first_name"), user.get("last_name")] if part
    ).strip()
    return name or f"id:{user.get('tg_id')}"


def admin_user_details(user: dict) -> list[str]:
    name = " ".join(
        part for part in [user.get("first_name"), user.get("last_name")] if part
    ).strip()
    username = user.get("username")
    return [
        f"Имя: {h(name or 'не указано')}",
        f"Юзер: {h('@' + username if username else 'нет username')}",
        f"ID: <code>{h(user.get('tg_id'))}</code>",
    ]


def ticket_title(ticket: dict) -> str:
    return f"№{ticket['public_id']} · {status_title(ticket['status'])}"


def ticket_card(ticket: dict, user: dict | None = None) -> str:
    lines = [
        f"<b>Обращение №{h(ticket['public_id'])}</b>",
        f"Статус: <b>{h(status_title(ticket['status']))}</b>",
        f"Создано: {h(ticket['created_at'])}",
    ]
    if ticket.get("assigned_admin_id"):
        lines.append(f"Оператор: <code>{h(ticket['assigned_admin_id'])}</code>")
    if user is not None:
        lines.append("Пользователь:")
        lines.extend(admin_user_details(user))
    if ticket.get("last_message_at"):
        lines.append(f"Последнее сообщение: {h(ticket['last_message_at'])}")
    return "\n".join(lines)


def user_ticket_card(ticket: dict) -> str:
    lines = [
        f"{pe('doc')} <b>Обращение №{h(ticket['public_id'])}</b>",
        f"Статус: <b>{h(status_title(ticket['status']))}</b>",
        f"Создано: {h(ticket['created_at'])}",
    ]
    if ticket.get("last_message_at"):
        lines.append(f"Последнее сообщение: {h(ticket['last_message_at'])}")
    return "\n".join(lines)


def admin_incoming_card(
    title: str,
    ticket: dict,
    user: dict,
    body: str,
    content_type: str,
) -> str:
    message = (body or "").strip()
    if not message:
        message = f"[{content_type}]"
    return "\n".join(
        [
            f"<b>{h(title)}</b>",
            f"Тикет: <b>№{h(ticket['public_id'])}</b>",
            f"Статус: {h(status_title(ticket['status']))}",
            *admin_user_details(user),
            "",
            f"<b>Сообщение:</b>\n{h(message)}",
        ]
    )


def message_preview(message: dict, limit: int = 500) -> str:
    body = " ".join((message.get("body") or "").strip().split())
    content_type = message.get("content_type") or "message"
    if not body:
        body = f"[{content_type}]"
    if len(body) > limit:
        body = body[: limit - 1].rstrip() + "…"
    return h(body)
