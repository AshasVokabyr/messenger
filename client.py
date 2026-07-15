import argparse
import asyncio
import html
import json
import re
import sys
import uuid
from datetime import datetime

import httpx
import websockets

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout


class MessengerClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
        self.token: str | None = None
        self.login_name: str | None = None
        self.current_chat_id: str | None = None
        self._chats_cache: dict[str, dict] = {}
        self._chat_list: list[dict] = []
        self._chat_ids_by_login: dict[str, str] = {}
        self._ws_queue: asyncio.Queue = asyncio.Queue()
        self._subscribed_chats: set[str] = set()
        self._stop = asyncio.Event()
        self._ws_task: asyncio.Task | None = None

    @property
    def authenticated(self) -> bool:
        return self.token is not None and self.login_name is not None

    def _prompt(self) -> HTML:
        ctx = self.login_name or ""
        if self.current_chat_id:
            name = self._chat_display_name(self.current_chat_id)
            ctx += "@" + name
        return HTML(f"<b>{ctx}</b> > ") if ctx else HTML("> ")

    def _print(self, text: str, end: str = "\n") -> None:
        try:
            print_formatted_text(HTML(text), end=end)
        except Exception:
            clean = re.sub(r'</?[^>]+>', '', text)
            print(clean, end=end)

    @staticmethod
    def _format_member_list(members: list[dict]) -> str:
        return ", ".join(m["login"] for m in members)

    def _chat_name(self, chat: dict) -> str:
        if chat["type"] == "personal" and self.login_name:
            others = [m["login"] for m in chat.get("members", []) if m["login"] != self.login_name]
            return others[0] if others else "personal"
        return chat.get("name", "Unnamed") or "Unnamed"

    def _chat_display_name(self, chat_id: str) -> str:
        chat = self._chats_cache.get(chat_id)
        if chat:
            return self._chat_name(chat)
        return chat_id[:12]

    def _cache_chat(self, chat: dict) -> None:
        cid = chat["id"]
        self._chats_cache[cid] = chat
        if all(c["id"] != cid for c in self._chat_list):
            self._chat_list.append(chat)
        if chat["type"] == "personal" and self.login_name:
            others = [m["login"] for m in chat.get("members", []) if m["login"] != self.login_name]
            for ol in others:
                self._chat_ids_by_login[ol] = cid

    def _build_completer_words(self) -> list[str]:
        if not self.authenticated:
            return ["/help", "/register", "/login", "/quit", "/exit"]
        words = [
            "/help", "/chats", "/leave", "/enter", "/switch",
            "/back", "/clear", "/kick", "/invite", "/delete", "/search",
            "/personal", "/group", "/register", "/login", "/logout",
            "/users", "/messages", "/members", "/exit",
        ]
        words.extend(self._chat_ids_by_login.keys())
        for i in range(len(self._chat_list)):
            words.append(str(i + 1))
        return sorted(set(words))

    def resolve_chat_ref(self, ref: str) -> str | None:
        if not ref:
            return None
        if ref.isdigit():
            idx = int(ref) - 1
            if 0 <= idx < len(self._chat_list):
                return self._chat_list[idx]["id"]
        if ref in self._chat_ids_by_login:
            return self._chat_ids_by_login[ref]
        if ref in self._chats_cache:
            return ref
        try:
            uuid.UUID(ref)
            return ref
        except (ValueError, AttributeError):
            pass
        lower = ref.lower()
        for chat in self._chat_list:
            name = self._chat_name(chat).lower()
            if lower == name:
                return chat["id"]
        return None

    async def _resolve_ref(self, ref: str) -> str | None:
        cid = self.resolve_chat_ref(ref)
        if cid is not None:
            return cid
        try:
            await self.get_chats()
        except Exception:
            pass
        return self.resolve_chat_ref(ref)

    async def _auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def register(self, login: str, password: str) -> str:
        async with httpx.AsyncClient() as c:
            resp = await c.post(f"{self.base_url}/auth/register", json={"login": login, "password": password})
            if resp.status_code == 201:
                self.token = resp.json()["access_token"]
                return self.token
            raise RuntimeError(f"Register failed ({resp.status_code}): {resp.json().get('detail', '')}")

    async def login(self, login: str, password: str) -> str:
        async with httpx.AsyncClient() as c:
            resp = await c.post(f"{self.base_url}/auth/login", json={"login": login, "password": password})
            if resp.status_code == 200:
                self.token = resp.json()["access_token"]
                return self.token
            raise RuntimeError(f"Login failed ({resp.status_code}): {resp.json().get('detail', '')}")

    async def get_chats(self) -> list[dict]:
        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{self.base_url}/chats/", headers=await self._auth_header())
            if resp.status_code == 200:
                chats = resp.json()
                self._chat_list = chats
                for chat in chats:
                    self._cache_chat(chat)
                return chats
            raise RuntimeError(f"Failed to list chats ({resp.status_code})")

    async def get_chat(self, chat_id: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{self.base_url}/chats/{chat_id}", headers=await self._auth_header())
            if resp.status_code == 200:
                chat = resp.json()
                self._cache_chat(chat)
                return chat
            raise RuntimeError(f"Failed to get chat ({resp.status_code})")

    async def get_user_by_login(self, login: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{self.base_url}/users/by-login/{login}")
            if resp.status_code == 200:
                return resp.json()
            raise RuntimeError(f"User not found: {login}")

    async def search_users(self, q: str) -> list[dict]:
        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{self.base_url}/users/search", params={"q": q, "limit": 20})
            if resp.status_code == 200:
                return resp.json()
            raise RuntimeError(f"Search failed ({resp.status_code})")

    async def create_personal_chat(self, user_id: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self.base_url}/chats/personal/{user_id}",
                headers=await self._auth_header(),
            )
            if resp.status_code in (200, 201):
                chat = resp.json()
                self._cache_chat(chat)
                return chat
            raise RuntimeError(f"Failed to create personal chat ({resp.status_code}): {resp.json().get('detail', '')}")

    async def create_group_chat(self, name: str, participant_ids: list[str]) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self.base_url}/chats/group",
                json={"name": name, "participant_ids": participant_ids},
                headers=await self._auth_header(),
            )
            if resp.status_code == 201:
                chat = resp.json()
                self._cache_chat(chat)
                return chat
            raise RuntimeError(f"Failed to create group chat ({resp.status_code}): {resp.json().get('detail', '')}")

    async def remove_participant(self, chat_id: str, user_id: str) -> None:
        async with httpx.AsyncClient() as c:
            resp = await c.delete(
                f"{self.base_url}/chats/{chat_id}/participants/{user_id}",
                headers=await self._auth_header(),
            )
            if resp.status_code != 204:
                raise RuntimeError(f"Remove failed ({resp.status_code}): {resp.json().get('detail', '')}")

    async def add_participant(self, chat_id: str, user_id: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self.base_url}/chats/{chat_id}/participants",
                json={"user_ids": [user_id]},
                headers=await self._auth_header(),
            )
            if resp.status_code == 200:
                return resp.json()
            raise RuntimeError(f"Add participant failed ({resp.status_code}): {resp.json().get('detail', '')}")

    async def delete_chat(self, chat_id: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.delete(
                f"{self.base_url}/chats/{chat_id}",
                headers=await self._auth_header(),
            )
            if resp.status_code == 200:
                return resp.json()
            raise RuntimeError(f"Delete failed ({resp.status_code}): {resp.json().get('detail', '')}")

    async def search_messages_global(self, q: str) -> list[dict]:
        async with httpx.AsyncClient() as c:
            resp = await c.get(
                f"{self.base_url}/messages/search",
                params={"q": q},
                headers=await self._auth_header(),
            )
            if resp.status_code == 200:
                return resp.json()
            raise RuntimeError(f"Search messages failed ({resp.status_code}): {resp.json().get('detail', '')}")

    async def leave_chat(self, chat_id: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self.base_url}/chats/{chat_id}/leave",
                headers=await self._auth_header(),
            )
            if resp.status_code == 200:
                return resp.json()
            raise RuntimeError(f"Leave failed ({resp.status_code}): {resp.json().get('detail', '')}")

    async def send_message(self, chat_id: str, content: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self.base_url}/chats/{chat_id}/messages",
                json={"content": content},
                headers=await self._auth_header(),
            )
            if resp.status_code == 201:
                return resp.json()
            raise RuntimeError(f"Failed to send message ({resp.status_code}): {resp.json().get('detail', '')}")

    async def get_messages(self, chat_id: str, limit: int = 50) -> list[dict]:
        async with httpx.AsyncClient() as c:
            resp = await c.get(
                f"{self.base_url}/chats/{chat_id}/messages",
                params={"limit": limit},
                headers=await self._auth_header(),
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("items", [])
            raise RuntimeError(f"Failed to get messages ({resp.status_code})")

    async def ws_send(self, data: dict) -> None:
        await self._ws_queue.put(data)

    async def _ws_sender(self, ws) -> None:
        while not self._stop.is_set():
            try:
                data = await asyncio.wait_for(self._ws_queue.get(), timeout=1)
                await ws.send(json.dumps(data))
            except asyncio.TimeoutError:
                continue
            except websockets.ConnectionClosed:
                break

    async def _ws_receiver(self, ws) -> None:
        while not self._stop.is_set():
            try:
                msg = await ws.recv()
            except websockets.ConnectionClosed:
                return
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue
            t = data.get("type")

            if t == "message":
                d = data["data"]
                ts = datetime.fromisoformat(d["created_at"]).strftime("%H:%M:%S")
                sender = d.get("sender_login", "unknown")
                is_me = sender == self.login_name
                color = "ansigreen" if is_me else "ansiyellow"
                self._print(f"[{ts}] <{color}>{sender}</{color}>: {html.escape(d['content'])}")

            elif t == "joined":
                cid = data["chat_id"]
                self._subscribed_chats.add(cid)
                name = self._chat_display_name(cid)
                self._print(f"<i>Joined {name}</i>")

            elif t == "left":
                cid = data["chat_id"]
                self._subscribed_chats.discard(cid)
                name = self._chat_display_name(cid)
                self._print(f"<i>Left {name}</i>")

            elif t == "chat_deleted":
                cid = data["chat_id"]
                self._chats_cache.pop(cid, None)
                self._chat_list = [c for c in self._chat_list if c["id"] != cid]
                self._subscribed_chats.discard(cid)
                if self.current_chat_id == cid:
                    self.current_chat_id = None
                self._print(f"<i>Chat deleted</i>")

            elif t == "ping":
                pass

            elif t == "error":
                self._print(f"<ansired>WS error: {html.escape(data.get('detail', ''))}</ansired>")

    async def ws_receive_loop(self) -> None:
        while not self._stop.is_set():
            try:
                async with websockets.connect(f"{self.ws_url}?token={self.token}") as ws:
                    for cid in self._subscribed_chats:
                        await ws.send(json.dumps({"action": "join", "chat_id": cid}))

                    send_task = asyncio.create_task(self._ws_sender(ws))
                    recv_task = asyncio.create_task(self._ws_receiver(ws))
                    try:
                        done, pending = await asyncio.wait(
                            [send_task, recv_task],
                            return_when=asyncio.FIRST_EXCEPTION,
                        )
                        for task in pending:
                            task.cancel()
                        for task in done:
                            try:
                                task.result()
                            except (websockets.ConnectionClosed, asyncio.CancelledError):
                                pass
                    except asyncio.CancelledError:
                        for t in (send_task, recv_task):
                            if not t.done():
                                t.cancel()
                        raise
            except (websockets.ConnectionClosed, OSError) as e:
                if not self._stop.is_set():
                    self._print("<i>WS disconnected, reconnecting in 3s...</i>")
                    await asyncio.sleep(3)

    async def start_ws(self) -> None:
        self._stop.clear()
        self._ws_task = asyncio.create_task(self.ws_receive_loop())

    async def stop_ws(self) -> None:
        self._stop.set()
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

    def print_chat_list(self, chats: list[dict] | None = None) -> None:
        lst = chats if chats is not None else self._chat_list
        for i, c in enumerate(lst, 1):
            name = self._chat_name(c)
            if c["type"] == "personal":
                self._print(f"  {i}. <ansigreen>{name}</ansigreen>")
            else:
                members = self._format_member_list(c.get("members", []))
                self._print(f"  {i}. <ansicyan>{name}</ansicyan> ({members})")

    def print_history(self, chat_id: str, msgs: list[dict]) -> None:
        name = self._chat_display_name(chat_id)
        if not msgs:
            self._print(f"<i>No messages in {name}</i>")
            return
        self._print(f"<i>--- History of {name} ({len(msgs)} messages) ---</i>")
        for m in reversed(msgs):
            ts = datetime.fromisoformat(m["created_at"]).strftime("%H:%M:%S")
            sender = m.get("sender_login", "unknown")
            is_me = sender == self.login_name
            color = "ansigreen" if is_me else "ansiyellow"
            self._print(f"  [{ts}] <{color}>{sender}</{color}>: {html.escape(m['content'])}")


_HELP_AUTH = """
  /register <login> <pwd>  Register a new user and log in
  /login <login> <pwd>     Log in as existing user
  /help                    Show this help
  /exit                    Exit the program"""

_HELP_FULL = """
── Authentication ──────────────────────────
  /register <l> <p>        Register a new user
  /login <l> <p>           Log in as existing user
  /logout                  Log out and return to anonymous mode
  /exit                    Exit the program

── Chat Management ─────────────────────────
  /personal <login>        Create personal chat by login
  /group <name> <l1>...    Create group chat
  /invite <ref> <login>    Add participant to chat
  /kick <ref> <login>      Remove participant (admin only)
  /leave <ref>             Leave chat (remove yourself from participants)
  /delete <ref>            Delete chat (admin only)

── Navigation ──────────────────────────────
  /chats                   List your chats (numbered)
  /enter <ref> [N]         Enter chat + show last N messages
  /switch [ref]            Switch current chat (list if no ref)
  /back                    Go to main menu (keep subscriptions)

── Messages ────────────────────────────────
  /messages [N]            Show last N messages in current chat
  /search <query>          Search messages across all your chats
  <any text>               Send message to current chat

── Info ────────────────────────────────────
  /help                    Show this help
  /users <query>           Search users by login
  /members                 Show members of current chat
  /clear                   Clear terminal screen

Ref can be: number from /chats, login (for personal chats),
            or chat_id (UUID)."""


async def _reload(client: MessengerClient) -> None:
    try:
        chats = await client.get_chats()
        if chats:
            client._print("<b>Your chats:</b>")
            client.print_chat_list(chats)
        else:
            client._print("<i>No chats yet</i>")
    except Exception:
        pass


async def interactive_mode(client: MessengerClient) -> None:
    already_auth = client.authenticated

    if already_auth:
        client._print(f"<b>{client.login_name}</b> connected")
    else:
        client._print("Not logged in. Use <b>/register</b> or <b>/login</b>")

    if already_auth:
        await _reload(client)

    print("Type /help for commands\n")

    if already_auth:
        await client.start_ws()

    session = PromptSession(history=InMemoryHistory())

    try:
        with patch_stdout():
            while True:
                completer = WordCompleter(client._build_completer_words(), sentence=True)
                prompt = client._prompt()
                raw = await session.prompt_async(prompt, completer=completer)
                line = raw.strip()
                if not line:
                    continue

                parts = line.split()
                cmd = parts[0]

                if cmd in ("/quit", "/exit"):
                    break

                elif cmd == "/help":
                    print(_HELP_FULL if client.authenticated else _HELP_AUTH)

                elif cmd == "/register":
                    if len(parts) < 3:
                        print("Usage: /register <login> <password>")
                        continue
                    try:
                        await client.register(parts[1], parts[2])
                        was_auth = client.authenticated
                        client.login_name = parts[1]
                        if not was_auth:
                            await client.start_ws()
                        print_formatted_text(HTML(f"Registered and logged in as <ansigreen>{parts[1]}</ansigreen>"))
                        await _reload(client)
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

                elif cmd == "/login":
                    if len(parts) < 3:
                        print("Usage: /login <login> <password>")
                        continue
                    try:
                        await client.login(parts[1], parts[2])
                        was_auth = client.authenticated
                        client.login_name = parts[1]
                        if not was_auth:
                            await client.start_ws()
                        print_formatted_text(HTML(f"Logged in as <ansigreen>{parts[1]}</ansigreen>"))
                        await _reload(client)
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

                elif cmd == "/logout":
                    if not client.authenticated:
                        print("Not logged in.")
                    else:
                        await client.stop_ws()
                        client.token = None
                        client.login_name = None
                        client.current_chat_id = None
                        client._chats_cache.clear()
                        client._chat_list.clear()
                        client._chat_ids_by_login.clear()
                        client._subscribed_chats.clear()
                        print("Logged out")
                    continue

                elif not client.authenticated:
                    print("Please login first. Use <b>/register</b> or <b>/login</b>")
                    continue

                elif cmd == "/chats":
                    try:
                        chats = await client.get_chats()
                        if chats:
                            client._print("<b>Your chats:</b>")
                            client.print_chat_list(chats)
                        else:
                            client._print("<i>No chats</i>")
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

                elif cmd == "/back":
                    if not client.current_chat_id:
                        print("Already in main menu")
                    else:
                        client.current_chat_id = None
                        print("Back to main menu")

                elif cmd == "/clear":
                    print("\033[2J\033[H", end="")

                elif cmd == "/kick":
                    if len(parts) < 3:
                        print("Usage: /kick <ref> <login>")
                        continue
                    cid = await client._resolve_ref(parts[1])
                    if not cid:
                        print_formatted_text(HTML(f"<ansired>Chat not found: {parts[1]}</ansired>"))
                        continue
                    try:
                        user = await client.get_user_by_login(parts[2])
                        await client.remove_participant(cid, str(user["id"]))
                        print(f"Removed {parts[2]} from {client._chat_display_name(cid)}")
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

                elif cmd == "/invite":
                    if len(parts) < 3:
                        print("Usage: /invite <ref> <login>")
                        continue
                    cid = await client._resolve_ref(parts[1])
                    if not cid:
                        print_formatted_text(HTML(f"<ansired>Chat not found: {parts[1]}</ansired>"))
                        continue
                    try:
                        user = await client.get_user_by_login(parts[2])
                        await client.add_participant(cid, str(user["id"]))
                        print(f"Added {parts[2]} to {client._chat_display_name(cid)}")
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

                elif cmd == "/leave":
                    if len(parts) < 2:
                        print("Usage: /leave <ref>")
                        continue
                    cid = await client._resolve_ref(parts[1])
                    if not cid:
                        print_formatted_text(HTML(f"<ansired>Chat not found: {parts[1]}</ansired>"))
                        continue
                    if client.current_chat_id == cid:
                        client.current_chat_id = None
                    try:
                        result = await client.leave_chat(cid)
                        client._subscribed_chats.discard(cid)
                        client._chats_cache.pop(cid, None)
                        client._chat_list = [c for c in client._chat_list if c["id"] != cid]
                        if client.current_chat_id == cid:
                            client.current_chat_id = None
                        print(result.get("detail", f"Left {client._chat_display_name(cid)}"))
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

                elif cmd == "/delete":
                    if len(parts) < 2:
                        print("Usage: /delete <ref>")
                        continue
                    cid = await client._resolve_ref(parts[1])
                    if not cid:
                        print_formatted_text(HTML(f"<ansired>Chat not found: {parts[1]}</ansired>"))
                        continue
                    if client.current_chat_id == cid:
                        client.current_chat_id = None
                    try:
                        result = await client.delete_chat(cid)
                        client._subscribed_chats.discard(cid)
                        client._chats_cache.pop(cid, None)
                        client._chat_list = [c for c in client._chat_list if c["id"] != cid]
                        print(result.get("detail", f"Deleted {client._chat_display_name(cid)}"))
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

                elif cmd == "/enter":
                    limit = 20
                    if len(parts) >= 2:
                        ref = parts[1]
                        if len(parts) >= 3:
                            try:
                                limit = int(parts[2])
                            except ValueError:
                                pass
                    else:
                        ref = client.current_chat_id
                    if not ref:
                        print("Usage: /enter <ref> [N]")
                        continue
                    cid = await client._resolve_ref(ref)
                    if not cid:
                        print_formatted_text(HTML(f"<ansired>Chat not found: {ref}</ansired>"))
                        continue
                    if client.current_chat_id != cid:
                        client.current_chat_id = cid
                        await client.ws_send({"action": "join", "chat_id": cid})
                    name = client._chat_display_name(cid)
                    print_formatted_text(HTML(f"<b>=== {name} ===</b>"))
                    try:
                        msgs = await client.get_messages(cid, limit)
                        client.print_history(cid, msgs)
                    except Exception as e:
                        print(f"  <i>Could not load history: {e}</i>")

                elif cmd == "/switch":
                    if len(parts) < 2:
                        if not client._chat_list:
                            await client.get_chats()
                        subscribed = [c for c in client._chat_list if c["id"] in client._subscribed_chats]
                        if not subscribed:
                            print("No subscribed chats. Use /enter first.")
                        else:
                            print("Subscribed chats:")
                            for i, c in enumerate(subscribed, 1):
                                name = client._chat_name(c)
                                mark = f" <ansigreen>*</ansigreen>" if c["id"] == client.current_chat_id else ""
                                print_formatted_text(HTML(f"  {i}. {name}{mark}"))
                            print("Use /switch <number|name> to switch")
                        continue
                    cid = await client._resolve_ref(parts[1])
                    if not cid:
                        print_formatted_text(HTML(f"<ansired>Chat not found: {parts[1]}</ansired>"))
                        continue
                    if cid not in client._subscribed_chats:
                        await client.ws_send({"action": "join", "chat_id": cid})
                        client._subscribed_chats.add(cid)
                    client.current_chat_id = cid
                    name = client._chat_display_name(cid)
                    print(f"Switched to {name}")

                elif cmd == "/personal":
                    if len(parts) < 2:
                        print("Usage: /personal <login>")
                        continue
                    try:
                        user = await client.get_user_by_login(parts[1])
                        chat = await client.create_personal_chat(str(user["id"]))
                        cid = chat["id"]
                        client.current_chat_id = cid
                        await client.ws_send({"action": "join", "chat_id": cid})
                        client._subscribed_chats.add(cid)
                        name = client._chat_name(chat)
                        print_formatted_text(HTML(f"Chat with <ansigreen>{name}</ansigreen> ready"))
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

                elif cmd == "/group":
                    if len(parts) < 3:
                        print("Usage: /group <name> <login1> [login2 ...]")
                        continue
                    try:
                        user_ids = []
                        for name in parts[2:]:
                            user = await client.get_user_by_login(name)
                            user_ids.append(str(user["id"]))
                        chat = await client.create_group_chat(parts[1], user_ids)
                        cid = chat["id"]
                        client.current_chat_id = cid
                        await client.ws_send({"action": "join", "chat_id": cid})
                        client._subscribed_chats.add(cid)
                        print_formatted_text(HTML(f'Group <ansicyan>"{parts[1]}"</ansicyan> created ({len(user_ids)} members)'))
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

                elif cmd == "/users":
                    if len(parts) < 2:
                        print("Usage: /users <query>")
                        continue
                    try:
                        users = await client.search_users(parts[1])
                        for u in users:
                            print(f"  {u['id']}  {u['login']}")
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

                elif cmd == "/messages":
                    limit = 20
                    if len(parts) >= 2:
                        try:
                            limit = int(parts[1])
                        except ValueError:
                            print("Usage: /messages [N]")
                            continue
                    if not client.current_chat_id:
                        print("No current chat. Use /enter or /switch first.")
                        continue
                    try:
                        msgs = await client.get_messages(client.current_chat_id, limit)
                        client.print_history(client.current_chat_id, msgs)
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

                elif cmd == "/members":
                    if not client.current_chat_id:
                        print("No current chat.")
                        continue
                    try:
                        chat = await client.get_chat(client.current_chat_id)
                        for m in chat.get("members", []):
                            tag = " (you)" if m["login"] == client.login_name else ""
                            print(f"  {m['login']}{tag}")
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

                elif cmd == "/search":
                    if len(parts) < 2:
                        print("Usage: /search <query>")
                        continue
                    try:
                        results = await client.search_messages_global(parts[1])
                        if not results:
                            print("No results found")
                        else:
                            print(f"Search results ({len(results)}):")
                            for m in results:
                                ts = datetime.fromisoformat(m["created_at"]).strftime("%H:%M:%S")
                                sender = m.get("sender_login", "unknown")
                                print(f"  [{ts}] {sender}: {m['content']}")
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))

                elif cmd.startswith("/"):
                    print(f"Unknown command: {cmd}")

                elif client.current_chat_id:
                    try:
                        await client.send_message(client.current_chat_id, line)
                    except Exception as e:
                        print_formatted_text(HTML(f"<ansired>Error: {e}</ansired>"))
                else:
                    print("No current chat. Use /enter or /switch first.")
    finally:
        if client.authenticated:
            await client.stop_ws()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Messenger CLI Client")
    parser.add_argument("action", nargs="?", choices=["register", "login", "interactive"],
                        default="interactive")
    parser.add_argument("login_name", nargs="?")
    parser.add_argument("password", nargs="?")
    parser.add_argument("--host", default="http://localhost:8000")

    args = parser.parse_args()
    client = MessengerClient(args.host)

    if args.action == "register":
        if not args.login_name or not args.password:
            print("Usage: python client.py register <login> <password> [--host URL]")
            sys.exit(1)
        try:
            token = await client.register(args.login_name, args.password)
            print(f"Registered as {args.login_name}")
            print(f"Token: {token}")
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)
        return

    if args.action == "login":
        if not args.login_name or not args.password:
            print("Usage: python client.py login <login> <password> [--host URL]")
            sys.exit(1)
        try:
            token = await client.login(args.login_name, args.password)
            print(f"Logged in as {args.login_name}")
            print(f"Token: {token}")
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)
        return

    if args.action == "interactive":
        if args.login_name and args.password:
            try:
                await client.login(args.login_name, args.password)
                client.login_name = args.login_name
            except Exception as e:
                print(f"Login failed: {e}")
                sys.exit(1)
        await interactive_mode(client)


if __name__ == "__main__":
    asyncio.run(main())
