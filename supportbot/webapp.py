from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import mimetypes
import time
from contextlib import suppress
from pathlib import PurePosixPath
from urllib.parse import parse_qsl

from aiohttp import ClientSession, web
from aiogram import Bot

from supportbot.config import Settings, normalize_username
from supportbot.db import Database
from supportbot.keyboards import user_ticket_keyboard
from supportbot.texts import h, status_title


class RealtimeHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict]] = set()

    def subscribe(self) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=20)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event_type: str, **payload: object) -> None:
        if not self._subscribers:
            return
        event = {
            "type": event_type,
            "ts": time.time(),
            **payload,
        }
        for queue in tuple(self._subscribers):
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(event)


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
      --attention: #f0b84b;
    }
    * { box-sizing: border-box; }
    html { background: var(--bg); }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    button, textarea, input { font: inherit; }
    button:disabled { cursor: default; opacity: .45; }
    .app { min-height: 100vh; }
    .side { width: min(100%, 760px); min-height: 100vh; margin: 0 auto; background: var(--panel); }
    .main { display: none; min-height: 100vh; background: var(--bg); }
    .app.detail-open .side { display: none; }
    .app.detail-open .main { display: block; }
    .top {
      padding: 14px;
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      background: rgba(23, 25, 31, .96);
      backdrop-filter: blur(12px);
      z-index: 5;
    }
    .title { font-size: 18px; font-weight: 750; margin: 0; }
    .top-title { margin-bottom: 12px; }
    .tabs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .section-tools { display: none; margin-top: 8px; }
    .section-tools.visible { display: block; }
    .section-tools .btn { width: 100%; }
    .tab, .btn {
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 8px;
      padding: 9px 10px;
      cursor: pointer;
    }
    .tab.active { border-color: var(--accent); color: white; background: #263654; }
    .tab-count { color: var(--muted); }
    .tab.active .tab-count { color: white; }
    .unread-count {
      display: inline-grid;
      place-items: center;
      min-width: 18px;
      height: 18px;
      margin-left: 3px;
      padding: 0 5px;
      border-radius: 999px;
      background: var(--attention);
      color: #18130a;
      font-size: 11px;
      font-weight: 800;
    }
    .unread-count.hidden { display: none; }
    .list { padding: 10px; display: grid; gap: 8px; }
    .ticket {
      position: relative;
      min-width: 0;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #15171d;
      cursor: pointer;
      transition: border-color .15s ease, background .15s ease, transform .15s ease;
    }
    .ticket:hover { border-color: #454b58; }
    .ticket:active { transform: scale(.995); }
    .ticket.unread {
      border-color: #8d6b2e;
      background: #211d16;
      box-shadow: inset 3px 0 0 var(--attention);
    }
    .row { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
    .num { font-weight: 750; }
    .ticket-state { display: flex; justify-content: flex-end; align-items: center; gap: 6px; flex-wrap: wrap; text-align: right; }
    .status { color: var(--muted); font-size: 12px; }
    .new-message {
      display: inline-block;
      padding: 2px 6px;
      border-radius: 999px;
      background: var(--attention);
      color: #18130a;
      font-size: 11px;
      font-weight: 800;
    }
    .user { color: var(--muted); margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .preview {
      display: -webkit-box;
      margin-top: 6px;
      overflow: hidden;
      line-height: 1.4;
      overflow-wrap: anywhere;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      line-clamp: 2;
    }
    .empty { color: var(--muted); padding: 20px; text-align: center; }
    .detail-top {
      position: sticky;
      top: 0;
      z-index: 8;
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 56px;
      padding: 8px 12px;
      border-bottom: 1px solid var(--line);
      background: rgba(16, 17, 20, .96);
      backdrop-filter: blur(12px);
    }
    .back-btn {
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 8px;
      padding: 8px 11px;
      cursor: pointer;
    }
    .detail-title { min-width: 0; font-weight: 750; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .detail { padding: 16px; max-width: 920px; margin: 0 auto; }
    .card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; margin-bottom: 12px; }
    .meta { color: var(--muted); display: grid; gap: 3px; margin-top: 8px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
    .btn.primary { background: #214987; border-color: var(--accent); }
    .btn.ok { background: #1e4937; border-color: #2e8c61; }
    .btn.danger { background: #522331; border-color: var(--danger); }
    .messages { display: grid; gap: 8px; }
    .msg { width: fit-content; max-width: 84%; border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #15171d; }
    .msg.admin { margin-left: auto; background: #172338; border-color: #294266; }
    .msg-head { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    .msg-body { white-space: pre-wrap; word-break: break-word; }
    .thumb-link { display: block; margin-top: 8px; }
    .thumb {
      display: block;
      width: min(100%, 360px);
      max-height: 320px;
      object-fit: contain;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #0d0f13;
    }
    .file-link { display: inline-block; margin-top: 8px; text-decoration: none; }
    .file-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
    .file-actions .file-link { margin-top: 0; }
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
      .detail { padding: 12px; }
      .tabs { gap: 6px; }
      .tab { padding: 9px 6px; }
      .back-btn { padding: 8px 10px; }
      .msg { max-width: 94%; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="side">
      <div class="top">
        <div class="title top-title">Админ-панель</div>
        <div class="tabs">
          <button class="tab active" data-section="new">Новые <span id="count-new" class="tab-count">0</span></button>
          <button class="tab" data-section="active">Активные <span id="count-active" class="tab-count">0</span><span id="count-active-unread" class="unread-count hidden">0</span></button>
          <button class="tab" data-section="closed">Закрытые <span id="count-closed" class="tab-count">0</span></button>
        </div>
        <div id="closed-tools" class="section-tools">
          <button id="clear-closed" class="btn danger">Очистить закрытые</button>
        </div>
      </div>
      <div id="list" class="list"></div>
      <button id="load" class="btn load">Загрузить еще</button>
    </aside>
    <main class="main">
      <div class="detail-top">
        <button id="back-to-list" class="back-btn" type="button">← К списку</button>
        <div id="detail-title" class="detail-title">Тикет</div>
      </div>
      <div id="detail" class="detail">
        <div class="empty">Загрузка тикета...</div>
      </div>
    </main>
  </div>
  <script>
    const tg = window.Telegram?.WebApp;
    tg?.ready();
    tg?.expand();
    const initData = tg?.initData || "";
    const app = document.querySelector(".app");
    let section = "new";
    let offset = 0;
    let selectedId = null;
    let currentTicketSignature = "";
    let autoRefreshBusy = false;
    let pendingRealtimeRefresh = false;
    let lastAttentionCount = null;
    let eventSource = null;
    const limit = 30;
    const refreshIntervalMs = 4000;

    async function api(path, options = {}) {
      const res = await fetch(path, {
        ...options,
        cache: "no-store",
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

    function fileUrl(messageId, download = false) {
      const url = `/api/messages/${messageId}/file?init_data=${encodeURIComponent(initData)}`;
      return download ? `${url}&download=1` : url;
    }

    function userLabel(ticket) {
      if (ticket.username) return "@" + ticket.username;
      return [ticket.first_name, ticket.last_name].filter(Boolean).join(" ") || ("id:" + ticket.user_tg_id);
    }

    async function refreshCounts() {
      const data = await api("/api/counts");
      const attentionCount = data.new + data.active_unread;
      if (lastAttentionCount !== null && attentionCount > lastAttentionCount) {
        tg?.HapticFeedback?.notificationOccurred("warning");
      }
      lastAttentionCount = attentionCount;
      document.getElementById("count-new").textContent = data.new;
      document.getElementById("count-active").textContent = data.active;
      document.getElementById("count-closed").textContent = data.closed;
      const unread = document.getElementById("count-active-unread");
      unread.textContent = data.active_unread;
      unread.classList.toggle("hidden", data.active_unread === 0);
      document.getElementById("clear-closed").disabled = data.closed === 0;
    }

    function updateSectionTools() {
      document.getElementById("closed-tools").classList.toggle("visible", section === "closed");
    }

    async function loadTickets(reset = true, preserveLoaded = false) {
      let requestOffset = offset;
      let requestLimit = limit;
      if (reset) {
        requestLimit = preserveLoaded ? Math.max(offset, limit) : limit;
        requestOffset = 0;
        offset = 0;
      }
      updateSectionTools();
      const data = await api(`/api/tickets?section=${section}&limit=${requestLimit}&offset=${requestOffset}`);
      const list = document.getElementById("list");
      const fragment = document.createDocumentFragment();
      for (const ticket of data.tickets) {
        const el = document.createElement("div");
        const unread = section === "active" && ticket.admin_unread;
        el.className = `ticket${unread ? " unread" : ""}`;
        el.dataset.id = ticket.id;
        el.innerHTML = `
          <div class="row">
            <span class="num">№${esc(ticket.public_id)}</span>
            <span class="ticket-state"><span class="status">${esc(ticket.status_title)}</span>${unread ? '<span class="new-message">Новое сообщение</span>' : ""}</span>
          </div>
          <div class="user">${esc(userLabel(ticket))} · ${esc(ticket.last_message_at || "")}</div>
          <div class="preview">${esc(ticket.last_body || "[" + (ticket.last_content_type || "сообщение") + "]")}</div>
        `;
        el.onclick = () => openTicket(ticket.id);
        fragment.appendChild(el);
      }
      if (reset) {
        list.replaceChildren();
      }
      if (data.tickets.length === 0 && reset) {
        list.innerHTML = '<div class="empty">Пусто</div>';
      } else {
        list.appendChild(fragment);
      }
      offset = requestOffset + data.tickets.length;
      document.getElementById("load").style.display = data.has_more ? "block" : "none";
      await refreshCounts();
    }

    async function showList() {
      app.classList.remove("detail-open");
      tg?.BackButton?.hide();
      selectedId = null;
      currentTicketSignature = "";
      window.scrollTo({ top: 0, behavior: "auto" });
      await loadTickets(true);
    }

    function ticketSignature(data) {
      const messages = data.messages;
      const lastMessage = messages.length ? messages[messages.length - 1] : null;
      return [
        data.ticket.status,
        data.ticket.assigned_admin_id || "",
        data.ticket.last_message_at || "",
        messages.length,
        lastMessage?.id || "",
      ].join(":");
    }

    async function openTicket(id, options = {}) {
      const preserveDraft = Boolean(options.preserveDraft);
      const onlyIfChanged = Boolean(options.onlyIfChanged);
      const reply = document.getElementById("reply");
      const draft = preserveDraft ? (reply?.value || "") : "";
      const replyFocused = preserveDraft && document.activeElement === reply;
      const selectionStart = reply?.selectionStart ?? draft.length;
      const selectionEnd = reply?.selectionEnd ?? draft.length;
      const previousScroll = window.scrollY;
      const nearBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 120;

      selectedId = id;
      const data = await api(`/api/tickets/${id}`);
      if (selectedId !== id) return;
      const nextSignature = ticketSignature(data);
      if (onlyIfChanged && nextSignature === currentTicketSignature) {
        await refreshCounts();
        return;
      }
      currentTicketSignature = nextSignature;
      const t = data.ticket;
      const u = data.user;
      const messages = data.messages;
      const isClosed = ["closed", "resolved"].includes(t.status);
      const ticketElement = document.querySelector(`.ticket[data-id="${id}"]`);
      ticketElement?.classList.remove("unread");
      ticketElement?.querySelector(".new-message")?.remove();
      app.classList.add("detail-open");
      tg?.BackButton?.show();
      document.getElementById("detail-title").textContent = `Тикет №${t.public_id}`;
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
            ${!isClosed && !t.assigned_admin_id ? '<button class="btn ok" id="claim">Взять в работу</button>' : ""}
            ${!isClosed ? '<button class="btn danger" id="close">Закрыть обращение</button>' : ""}
          </div>
        </div>
        <div class="card">
          <div class="title">Сообщения</div>
          <div class="messages">
            ${messages.map(renderMessage).join("")}
          </div>
          ${!isClosed ? `
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
      const nextReply = document.getElementById("reply");
      if (nextReply && preserveDraft) {
        nextReply.value = draft;
        if (replyFocused) {
          nextReply.focus();
          nextReply.setSelectionRange(selectionStart, selectionEnd);
        }
      }
      await refreshCounts();
      if (preserveDraft) {
        if (nearBottom) {
          window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
        } else {
          window.scrollTo({ top: previousScroll, behavior: "auto" });
        }
      } else {
        window.scrollTo({ top: 0, behavior: "auto" });
      }
    }

    function renderMessage(m) {
      const role = m.sender_role === "admin" ? "Оператор" : "Пользователь";
      const hasFile = m.has_file && m.content_type !== "text";
      const url = hasFile ? fileUrl(m.id) : "";
      const downloadUrl = hasFile ? fileUrl(m.id, true) : "";
      const label = m.content_type === "photo" ? "Открыть фото" : `Открыть вложение: ${m.content_type}`;
      const preview = m.content_type === "photo"
        ? `<a class="thumb-link" href="${esc(url)}" target="_blank" rel="noopener"><img class="thumb" src="${esc(url)}" alt=""></a>`
        : "";
      const media = hasFile
        ? `${preview}<div class="file-actions"><a class="btn file-link" href="${esc(url)}" target="_blank" rel="noopener">${esc(label)}</a><a class="btn file-link" href="${esc(downloadUrl)}" target="_blank" rel="noopener">Скачать</a></div>`
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
    }

    async function closeTicket() {
      if (!confirm("Закрыть обращение?")) return;
      await api(`/api/tickets/${selectedId}/close`, { method: "POST", body: "{}" });
      await openTicket(selectedId);
    }

    async function clearClosedTickets() {
      if (section !== "closed") return;
      const total = Number(document.getElementById("count-closed").textContent || "0");
      if (total <= 0) return;
      if (!confirm(`Удалить все закрытые обращения? Количество: ${total}`)) return;
      const data = await api("/api/tickets/closed/clear", { method: "POST", body: "{}" });
      selectedId = null;
      document.getElementById("detail").innerHTML = `<div class="empty">Удалено закрытых обращений: ${esc(data.deleted)}</div>`;
      await loadTickets(true);
    }

    async function sendReply() {
      const text = document.getElementById("reply").value.trim();
      if (!text) return;
      await api(`/api/tickets/${selectedId}/reply`, { method: "POST", body: JSON.stringify({ text }) });
      await openTicket(selectedId);
    }

    async function autoRefresh() {
      if (autoRefreshBusy || document.hidden) return;
      autoRefreshBusy = true;
      try {
        if (app.classList.contains("detail-open") && selectedId !== null) {
          await openTicket(selectedId, { preserveDraft: true, onlyIfChanged: true });
        } else {
          await loadTickets(true, true);
        }
      } catch (error) {
        console.error("Auto refresh failed", error);
      } finally {
        autoRefreshBusy = false;
        if (pendingRealtimeRefresh && !document.hidden) {
          pendingRealtimeRefresh = false;
          window.setTimeout(autoRefresh, 80);
        }
      }
    }

    function scheduleRealtimeRefresh() {
      if (document.hidden) {
        pendingRealtimeRefresh = true;
        return;
      }
      if (autoRefreshBusy) {
        pendingRealtimeRefresh = true;
        return;
      }
      autoRefresh();
    }

    function startRealtime() {
      if (!window.EventSource || eventSource || !initData) return;
      eventSource = new EventSource(`/api/events?init_data=${encodeURIComponent(initData)}`);
      eventSource.addEventListener("update", event => {
        try {
          const data = JSON.parse(event.data || "{}");
          if (data.type === "ticket_changed" || data.type === "tickets_changed") {
            scheduleRealtimeRefresh();
          }
        } catch (error) {
          console.error("Bad realtime event", error);
          scheduleRealtimeRefresh();
        }
      });
      eventSource.onerror = () => {
        console.warn("Realtime connection interrupted; polling fallback is still active.");
      };
    }

    document.querySelectorAll(".tab").forEach(btn => btn.onclick = async () => {
      document.querySelectorAll(".tab").forEach(item => item.classList.remove("active"));
      btn.classList.add("active");
      section = btn.dataset.section;
      await loadTickets(true);
    });
    document.getElementById("load").onclick = () => loadTickets(false);
    document.getElementById("clear-closed").onclick = clearClosedTickets;
    document.getElementById("back-to-list").onclick = showList;
    tg?.BackButton?.onClick(showList);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        pendingRealtimeRefresh = false;
        autoRefresh();
      }
    });
    window.addEventListener("pagehide", () => {
      eventSource?.close();
      eventSource = null;
    });
    if (!initData) {
      document.body.innerHTML = `
        <div class="empty">
          <b>Админ-панель нужно открыть через кнопку бота</b><br>
          Напишите /admin новому боту и нажмите inline-кнопку «Админская панель».<br>
          Если токен менялся, перезапустите бота на сервере.
        </div>
      `;
    } else {
      loadTickets(true)
        .then(() => {
          startRealtime();
          window.setInterval(autoRefresh, refreshIntervalMs);
        })
        .catch(err => {
          document.body.innerHTML = `<div class="empty">Ошибка доступа или загрузки<br>${esc(err.message)}</div>`;
        });
    }
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
    username = normalize_username(user.get("username"))
    if int(user.get("id", 0)) not in settings.admin_ids and username not in settings.admin_usernames:
        raise web.HTTPForbidden(text="Admins only")
    return user


def _admin_user(request: web.Request) -> dict:
    settings: Settings = request.app["settings"]
    init_data = request.headers.get("X-Telegram-Init-Data", "") or request.query.get("init_data", "")
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
        "admin_unread": bool(ticket.get("admin_unread")),
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


async def _publish_ticket_changed(request: web.Request, ticket_id: int, reason: str) -> None:
    hub: RealtimeHub = request.app["realtime"]
    await hub.publish("ticket_changed", ticket_id=ticket_id, reason=reason)


async def index(_: web.Request) -> web.Response:
    return web.Response(
        text=INDEX_HTML,
        content_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


async def events(request: web.Request) -> web.StreamResponse:
    _admin_user(request)
    hub: RealtimeHub = request.app["realtime"]
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    queue = hub.subscribe()
    try:
        await response.write(b"retry: 1000\n\n")
        await response.write(b'event: update\ndata: {"type":"ready"}\n\n')
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=25)
            except TimeoutError:
                await response.write(b": ping\n\n")
                continue
            payload = json.dumps(event, ensure_ascii=False)
            await response.write(f"event: update\ndata: {payload}\n\n".encode())
    except asyncio.CancelledError:
        raise
    except ConnectionResetError:
        pass
    finally:
        hub.unsubscribe(queue)

    return response


async def counts(request: web.Request) -> web.Response:
    _admin_user(request)
    db: Database = request.app["db"]
    return _json(await db.admin_section_counts())


async def list_tickets(request: web.Request) -> web.Response:
    _admin_user(request)
    db: Database = request.app["db"]
    section = request.query.get("section", "new")
    limit = max(1, min(int(request.query.get("limit", "30")), 200))
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


async def clear_closed_tickets(request: web.Request) -> web.Response:
    _admin_user(request)
    db: Database = request.app["db"]
    deleted = await db.clear_closed_tickets()
    if deleted:
        hub: RealtimeHub = request.app["realtime"]
        await hub.publish("tickets_changed", reason="closed_cleared", deleted=deleted)
    return _json({"ok": True, "deleted": deleted})


async def ticket_detail(request: web.Request) -> web.Response:
    _admin_user(request)
    db: Database = request.app["db"]
    ticket_id = int(request.match_info["ticket_id"])
    data = await db.get_ticket_with_user(ticket_id)
    if data is None:
        raise web.HTTPNotFound(text="Ticket not found")
    ticket, user = data
    messages = await db.list_ticket_messages(ticket_id, limit=200)
    await db.mark_ticket_read(ticket_id)
    ticket["admin_unread"] = 0
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
    await _publish_ticket_changed(request, ticket_id, "claimed")
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
    await _publish_ticket_changed(request, ticket_id, "admin_replied")
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
    await _publish_ticket_changed(request, ticket_id, "closed")
    return _json({"ok": True, "ticket": ticket})


def _file_meta(message: dict, file_path: str | None, telegram_content_type: str | None) -> tuple[str, str]:
    path = PurePosixPath(file_path or "")
    extension = path.suffix.lower()
    message_type = message.get("content_type") or "file"

    if message_type == "photo" and extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        extension = ".jpg"
    elif not extension and telegram_content_type:
        extension = mimetypes.guess_extension(telegram_content_type.split(";", 1)[0].strip()) or ""

    filename = f"ticket-{message['ticket_id']}-message-{message['id']}{extension}"
    guessed_type = mimetypes.guess_type(filename)[0]

    if message_type == "photo":
        content_type = guessed_type or "image/jpeg"
    elif guessed_type:
        content_type = guessed_type
    else:
        content_type = telegram_content_type or "application/octet-stream"

    return filename, content_type


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
        filename, content_type = _file_meta(
            message,
            tg_file.file_path,
            response.headers.get("Content-Type"),
        )
        disposition = "attachment" if request.query.get("download") == "1" else "inline"
        return web.Response(
            body=body,
            content_type=content_type,
            headers={
                "Content-Disposition": f'{disposition}; filename="{filename}"',
                "Cache-Control": "private, max-age=300",
            },
        )


async def create_web_app(
    bot: Bot,
    db: Database,
    settings: Settings,
    realtime: RealtimeHub | None = None,
) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app["db"] = db
    app["settings"] = settings
    app["realtime"] = realtime or RealtimeHub()
    app["client_session"] = ClientSession()
    app.router.add_get("/admin", index)
    app.router.add_get("/api/events", events)
    app.router.add_get("/api/counts", counts)
    app.router.add_get("/api/tickets", list_tickets)
    app.router.add_post("/api/tickets/closed/clear", clear_closed_tickets)
    app.router.add_get("/api/tickets/{ticket_id:\\d+}", ticket_detail)
    app.router.add_post("/api/tickets/{ticket_id:\\d+}/claim", claim_ticket)
    app.router.add_post("/api/tickets/{ticket_id:\\d+}/reply", reply_ticket)
    app.router.add_post("/api/tickets/{ticket_id:\\d+}/close", close_ticket)
    app.router.add_get("/api/messages/{message_id:\\d+}/file", message_file)

    async def close_session(app_: web.Application) -> None:
        await app_["client_session"].close()

    app.on_cleanup.append(close_session)
    return app


async def start_web_app(
    bot: Bot,
    db: Database,
    settings: Settings,
    realtime: RealtimeHub | None = None,
) -> web.AppRunner:
    app = await create_web_app(bot, db, settings, realtime)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.webapp_host, settings.webapp_port)
    await site.start()
    return runner
