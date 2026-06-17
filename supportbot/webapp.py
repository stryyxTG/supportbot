from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from aiohttp import ClientSession, web
from aiogram import Bot

from supportbot.config import Settings
from supportbot.db import Database
from supportbot.keyboards import user_ticket_keyboard
from supportbot.texts import h, status_title


INDEX_HTML = r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Support Admin</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      color-scheme: dark;
      --bg: #101114;
      --panel: #17191f;
      --panel-2: #20232b;
      --text: #f4f5f7;
      --muted: #9aa0ad;
      --line: #2d313b;
      --accent: #4f8cff;
      --danger: #ff5c73;
      --ok: #45c486;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    button, textarea, input { font: inherit; }
    .app { display: grid; grid-template-columns: 390px 1fr; min-height: 100vh; }
    .side { border-right: 1px solid var(--line); background: var(--panel); min-width: 0; }
    .main { min-width: 0; }
    .top { padding: 14px; border-bottom: 1px solid var(--line); position: sticky; top: 0; background: var(--panel); z-index: 5; }
    .title { font-size: 18px; font-weight: 750; margin-bottom: 12px; }
    .tabs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .tab, .btn {
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 8px;
      padding: 9px 10px;
      cursor: pointer;
    }
    .tab.active { border-color: var(--accent); color: white; background: #263654; }
    .list { padding: 10px; display: grid; gap: 8px; }
    .ticket {
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #15171d;
      cursor: pointer;
    }
    .ticket.active { border-color: var(--accent); }
    .row { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
    .num { font-weight: 750; }
    .status { color: var(--muted); font-size: 12px; }
    .user { color: var(--muted); margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .preview { margin-top: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .empty { color: var(--muted); padding: 20px; text-align: center; }
    .detail { padding: 16px; max-width: 980px; margin: 0 auto; }
    .card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; margin-bottom: 12px; }
    .meta { color: var(--muted); display: grid; gap: 3px; margin-top: 8px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
    .btn.primary { background: #214987; border-color: var(--accent); }
    .btn.ok { background: #1e4937; border-color: #2e8c61; }
    .btn.danger { background: #522331; border-color: var(--danger); }
    .messages { display: grid; gap: 8px; }
    .msg { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #15171d; }
    .msg.admin { background: #161e2c; }
    .msg-head { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    .msg-body { white-space: pre-wrap; word-break: break-word; }
    .composer { display: grid; gap: 8px; margin-top: 12px; }
    textarea {
      width: 100%;
      min-height: 96px;
      resize: vertical;
      border: 1px solid var(--line);
      background: #101217;
      color: var(--text);
      border-radius: 8px;
      padding: 10px;
    }
    .load { width: calc(100% - 20px); margin: 0 10px 12px; }
    @media (max-width: 780px) {
      .app { grid-template-columns: 1fr; }
      .side { border-right: 0; border-bottom: 1px solid var(--line); }
      .detail { padding: 12px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="side">
      <div class="top">
        <div class="title">Админ-панель</div>
        <div class="tabs">
          <button class="tab active" data-section="new">Новые <span id="count-new">0</span></button>
          <button class="tab" data-section="active">Активные <span id="count-active">0</span></button>
          <button class="tab" data-section="closed">Закрытые <span id="count-closed">0</span></button>
        </div>
      </div>
      <div id="list" class="list"></div>
      <button id="load" class="btn load">Загрузить еще</button>
    </aside>
    <main class="main">
      <div id="detail" class="detail">
        <div class="empty">Выберите тикет слева</div>
      </div>
    </main>
  </div>
  <script>
    const tg = window.Telegram?.WebApp;
    tg?.ready();
    tg?.expand();
    const initData = tg?.initData || "";
    let section = "new";
    let offset = 0;
    let selectedId = null;
    const limit = 30;

    async function api(path, options = {}) {
      const res = await fetch(path, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          "X-Telegram-Init-Data": initData,
          ...(options.headers || {})
        }
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    }

    function esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, ch => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
      }[ch]));
    }

    function userLabel(ticket) {
      if (ticket.username) return "@" + ticket.username;
      return [ticket.first_name, ticket.last_name].filter(Boolean).join(" ") || ("id:" + ticket.user_tg_id);
    }

    async function refreshCounts() {
      const data = await api("/api/counts");
      document.getElementById("count-new").textContent = data.new;
      document.getElementById("count-active").textContent = data.active;
      document.getElementById("count-closed").textContent = data.closed;
    }

    async function loadTickets(reset = true) {
      if (reset) {
        offset = 0;
        selectedId = null;
        document.getElementById("list").innerHTML = "";
        document.getElementById("detail").innerHTML = '<div class="empty">Выберите тикет слева</div>';
      }
      const data = await api(`/api/tickets?section=${section}&limit=${limit}&offset=${offset}`);
      const list = document.getElementById("list");
      if (reset && data.tickets.length === 0) list.innerHTML = '<div class="empty">Пусто</div>';
      for (const ticket of data.tickets) {
        const el = document.createElement("div");
        el.className = "ticket";
        el.dataset.id = ticket.id;
        el.innerHTML = `
          <div class="row"><span class="num">№${esc(ticket.public_id)}</span><span class="status">${esc(ticket.status_title)}</span></div>
          <div class="user">${esc(userLabel(ticket))} · ${esc(ticket.last_message_at || "")}</div>
          <div class="preview">${esc(ticket.last_body || "[" + (ticket.last_content_type || "сообщение") + "]")}</div>
        `;
        el.onclick = () => openTicket(ticket.id);
        list.appendChild(el);
      }
      offset += data.tickets.length;
      document.getElementById("load").style.display = data.has_more ? "block" : "none";
      await refreshCounts();
    }

    async function openTicket(id) {
      selectedId = id;
      document.querySelectorAll(".ticket").forEach(el => el.classList.toggle("active", Number(el.dataset.id) === id));
      const data = await api(`/api/tickets/${id}`);
      const t = data.ticket;
      const u = data.user;
      const messages = data.messages;
      document.getElementById("detail").innerHTML = `
        <div class="card">
          <div class="row"><div class="title">Тикет №${esc(t.public_id)}</div><span class="status">${esc(t.status_title)}</span></div>
          <div class="meta">
            <div>Имя: ${esc([u.first_name, u.last_name].filter(Boolean).join(" ") || "не указано")}</div>
            <div>Юзер: ${esc(u.username ? "@" + u.username : "нет username")}</div>
            <div>ID: ${esc(u.tg_id)}</div>
            <div>Создан: ${esc(t.created_at)}</div>
            <div>Последнее: ${esc(t.last_message_at || "")}</div>
          </div>
          <div class="actions">
            ${t.status !== "closed" ? '<button class="btn ok" id="claim">Взять в работу</button><button class="btn danger" id="close">Закрыть</button>' : ""}
          </div>
        </div>
        <div class="card">
          <div class="title">Сообщения</div>
          <div class="messages">
            ${messages.map(renderMessage).join("")}
          </div>
          ${t.status !== "closed" ? `
            <div class="composer">
              <textarea id="reply" placeholder="Ответ пользователю"></textarea>
              <button class="btn primary" id="send">Отправить ответ</button>
            </div>
          ` : ""}
        </div>
      `;
      document.getElementById("claim")?.addEventListener("click", claimTicket);
      document.getElementById("close")?.addEventListener("click", closeTicket);
      document.getElementById("send")?.addEventListener("click", sendReply);
      document.querySelectorAll("[data-file]").forEach(btn => btn.addEventListener("click", () => openFile(btn.dataset.file)));
    }

    function renderMessage(m) {
      const role = m.sender_role === "admin" ? "Оператор" : "Пользователь";
      const media = m.content_type !== "text"
        ? `<button class="btn" data-file="${m.id}">Открыть вложение: ${esc(m.content_type)}</button>`
        : "";
      return `
        <div class="msg ${m.sender_role === "admin" ? "admin" : ""}">
          <div class="msg-head">${esc(m.created_at)} · ${role}</div>
          ${m.body ? `<div class="msg-body">${esc(m.body)}</div>` : ""}
          ${media}
        </div>
      `;
    }

    async function claimTicket() {
      await api(`/api/tickets/${selectedId}/claim`, { method: "POST", body: "{}" });
      await openTicket(selectedId);
      await loadTickets(true);
    }

    async function closeTicket() {
      if (!confirm("Закрыть тикет?")) return;
      await api(`/api/tickets/${selectedId}/close`, { method: "POST", body: "{}" });
      await openTicket(selectedId);
      await loadTickets(true);
    }

    async function sendReply() {
      const text = document.getElementById("reply").value.trim();
      if (!text) return;
      await api(`/api/tickets/${selectedId}/reply`, { method: "POST", body: JSON.stringify({ text }) });
      await openTicket(selectedId);
      await loadTickets(true);
    }

    async function openFile(messageId) {
      const res = await fetch(`/api/messages/${messageId}/file`, {
        headers: { "X-Telegram-Init-Data": initData }
      });
      if (!res.ok) {
        alert("Не удалось открыть вложение");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    }

    document.querySelectorAll(".tab").forEach(btn => btn.onclick = async () => {
      document.querySelectorAll(".tab").forEach(item => item.classList.remove("active"));
      btn.classList.add("active");
      section = btn.dataset.section;
      await loadTickets(true);
    });
    document.getElementById("load").onclick = () => loadTickets(false);
    loadTickets(true).catch(err => {
      document.body.innerHTML = `<div class="empty">Ошибка доступа или загрузки<br>${esc(err.message)}</div>`;
    });
  </script>
</body>
</html>"""


def _json(data: object) -> web.Response:
    return web.json_response(data, dumps=lambda value: json.dumps(value, ensure_ascii=False))


def _validate_init_data(init_data: str, settings: Settings) -> dict:
    if not init_data:
        raise web.HTTPUnauthorized(text="Missing Telegram init data")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", "")
    if not received_hash:
        raise web.HTTPUnauthorized(text="Missing hash")

    data_check_string = "\n".join(f"{key}={parsed[key]}" for key in sorted(parsed))
    secret_key = hmac.new(
        b"WebAppData",
        settings.bot_token.encode(),
        hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise web.HTTPUnauthorized(text="Bad signature")

    user = json.loads(parsed.get("user", "{}"))
    if int(user.get("id", 0)) not in settings.admin_ids:
        raise web.HTTPForbidden(text="Admins only")
    return user


def _admin_user(request: web.Request) -> dict:
    settings: Settings = request.app["settings"]
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    return _validate_init_data(init_data, settings)


def _trim(value: str | None, limit: int = 160) -> str:
    text = " ".join((value or "").split())
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _ticket_row(ticket: dict) -> dict:
    return {
        "id": ticket["id"],
        "public_id": ticket["public_id"],
        "status": ticket["status"],
        "status_title": status_title(ticket["status"]),
        "assigned_admin_id": ticket.get("assigned_admin_id"),
        "created_at": ticket["created_at"],
        "last_message_at": ticket.get("last_message_at"),
        "user_tg_id": ticket.get("user_tg_id"),
        "username": ticket.get("username"),
        "first_name": ticket.get("first_name"),
        "last_name": ticket.get("last_name"),
        "last_body": _trim(ticket.get("last_body")),
        "last_content_type": ticket.get("last_content_type"),
    }


def _message_row(message: dict) -> dict:
    return {
        "id": message["id"],
        "sender_role": message["sender_role"],
        "body": message.get("body") or "",
        "content_type": message["content_type"],
        "created_at": message["created_at"],
        "has_file": bool(message.get("file_id")),
    }


async def index(_: web.Request) -> web.Response:
    return web.Response(text=INDEX_HTML, content_type="text/html")


async def counts(request: web.Request) -> web.Response:
    _admin_user(request)
    db: Database = request.app["db"]
    return _json(await db.admin_section_counts())


async def list_tickets(request: web.Request) -> web.Response:
    _admin_user(request)
    db: Database = request.app["db"]
    section = request.query.get("section", "new")
    limit = max(1, min(int(request.query.get("limit", "30")), 50))
    offset = max(0, int(request.query.get("offset", "0")))
    tickets = await db.list_admin_section(section, limit=limit, offset=offset)
    total = await db.count_admin_section(section)
    return _json(
        {
            "tickets": [_ticket_row(ticket) for ticket in tickets],
            "total": total,
            "has_more": offset + len(tickets) < total,
        }
    )


async def ticket_detail(request: web.Request) -> web.Response:
    _admin_user(request)
    db: Database = request.app["db"]
    ticket_id = int(request.match_info["ticket_id"])
    data = await db.get_ticket_with_user(ticket_id)
    if data is None:
        raise web.HTTPNotFound(text="Ticket not found")
    ticket, user = data
    messages = await db.list_ticket_messages(ticket_id, limit=200)
    return _json(
        {
            "ticket": {
                **ticket,
                "status_title": status_title(ticket["status"]),
            },
            "user": user,
            "messages": [_message_row(message) for message in messages],
        }
    )


async def claim_ticket(request: web.Request) -> web.Response:
    admin = _admin_user(request)
    db: Database = request.app["db"]
    ticket_id = int(request.match_info["ticket_id"])
    ticket = await db.claim_ticket(ticket_id, int(admin["id"]))
    if ticket is None:
        raise web.HTTPConflict(text="Ticket is already claimed or closed")
    return _json({"ok": True, "ticket": ticket})


async def reply_ticket(request: web.Request) -> web.Response:
    admin = _admin_user(request)
    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    ticket_id = int(request.match_info["ticket_id"])
    payload = await request.json()
    text = (payload.get("text") or "").strip()
    if not text:
        raise web.HTTPBadRequest(text="Text is required")

    data = await db.get_ticket_with_user(ticket_id)
    if data is None:
        raise web.HTTPNotFound(text="Ticket not found")
    ticket, user = data
    if ticket["status"] in {"closed", "resolved"}:
        raise web.HTTPConflict(text="Ticket is closed")
    if ticket.get("assigned_admin_id") not in {None, int(admin["id"])}:
        raise web.HTTPConflict(text="Ticket belongs to another admin")
    if not ticket.get("assigned_admin_id"):
        claimed = await db.claim_ticket(ticket_id, int(admin["id"]))
        if claimed is None:
            raise web.HTTPConflict(text="Ticket is already claimed")

    sent = await bot.send_message(
        user["tg_id"],
        f"<b>Ответ по обращению №{h(ticket['public_id'])}</b>\n\n{h(text)}",
    )
    await db.add_message(
        ticket_id=ticket_id,
        sender_role="admin",
        sender_tg_id=int(admin["id"]),
        body=text,
        content_type="text",
        file_id=None,
        telegram_message_id=sent.message_id,
    )
    ticket = await db.set_status(
        ticket_id,
        "waiting_user",
        "admin",
        int(admin["id"]),
        "admin_replied_from_webapp",
    )
    return _json({"ok": True, "ticket": ticket})


async def close_ticket(request: web.Request) -> web.Response:
    admin = _admin_user(request)
    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    ticket_id = int(request.match_info["ticket_id"])
    data = await db.get_ticket_with_user(ticket_id)
    if data is None:
        raise web.HTTPNotFound(text="Ticket not found")
    ticket, user = data
    if ticket.get("assigned_admin_id") not in {None, int(admin["id"])}:
        raise web.HTTPConflict(text="Ticket belongs to another admin")
    ticket = await db.set_status(
        ticket_id,
        "closed",
        "admin",
        int(admin["id"]),
        "closed_by_admin_from_webapp",
    )
    try:
        await bot.send_message(
            user["tg_id"],
            f"Обращение <b>№{h(ticket['public_id'])}</b> закрыто оператором.",
            reply_markup=user_ticket_keyboard(ticket),
        )
    except Exception:
        pass
    return _json({"ok": True, "ticket": ticket})


async def message_file(request: web.Request) -> web.StreamResponse:
    _admin_user(request)
    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    session: ClientSession = request.app["client_session"]
    message_id = int(request.match_info["message_id"])
    message = await db.get_message(message_id)
    if message is None or not message.get("file_id"):
        raise web.HTTPNotFound(text="File not found")

    tg_file = await bot.get_file(message["file_id"])
    settings: Settings = request.app["settings"]
    url = f"https://api.telegram.org/file/bot{settings.bot_token}/{tg_file.file_path}"
    async with session.get(url) as response:
        if response.status != 200:
            raise web.HTTPBadGateway(text="Telegram file download failed")
        body = await response.read()
        return web.Response(
            body=body,
            content_type=response.headers.get("Content-Type", "application/octet-stream"),
        )


async def create_web_app(bot: Bot, db: Database, settings: Settings) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app["db"] = db
    app["settings"] = settings
    app["client_session"] = ClientSession()
    app.router.add_get("/admin", index)
    app.router.add_get("/api/counts", counts)
    app.router.add_get("/api/tickets", list_tickets)
    app.router.add_get("/api/tickets/{ticket_id:\\d+}", ticket_detail)
    app.router.add_post("/api/tickets/{ticket_id:\\d+}/claim", claim_ticket)
    app.router.add_post("/api/tickets/{ticket_id:\\d+}/reply", reply_ticket)
    app.router.add_post("/api/tickets/{ticket_id:\\d+}/close", close_ticket)
    app.router.add_get("/api/messages/{message_id:\\d+}/file", message_file)

    async def close_session(app_: web.Application) -> None:
        await app_["client_session"].close()

    app.on_cleanup.append(close_session)
    return app


async def start_web_app(bot: Bot, db: Database, settings: Settings) -> web.AppRunner:
    app = await create_web_app(bot, db, settings)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.webapp_host, settings.webapp_port)
    await site.start()
    return runner
