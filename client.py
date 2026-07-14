import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime

import httpx
import websockets

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import DynamicCompleter, WordCompleter
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"
RED = "\033[91m"


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

    def _prompt(self) -> str:
        ctx = self.login_name or ""
        if self.current_chat_id:
            name = self._chat_display_name(self.current_chat_id)
            ctx += "@" + name
        return f"{BOLD}{ctx}{RESET} > " if ctx else "> "

    def _print(self, text: str, end: str = "\n") -> None:
        print(text, end=end, flush=True)

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
        if chat["type"] == "personal" and self.login_name:
            others = [m["login"] for m in chat.get("members", []) if m["login"] != self.login_name]
            for ol in others:
                self._chat_ids_by_login[ol] = cid

    def _build_completer_words(self) -> list[str]:
        words = [
            "/help", "/chats", "/join", "/leave", "/enter", "/switch",
            "/personal", "/group", "/register", "/login", "/users",
            "/messages", "/members", "/quit",
        ]
        words.extend(self._chat_ids_by_login.keys())
        for i in range(len(self._chat_list)):
            words.append(str(i + 1))
        return sorted(set(words))

    def resolve_chat_ref(self, ref: str) -> str | None:
        if not ref:
            return None
        if ref == self.login_name:
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
            msg = await ws.recv()
            data = json.loads(msg)
            t = data.get("type")

            if t == "message":
                d = data["data"]
                ts = datetime.fromisoformat(d["created_at"]).strftime("%H:%M:%S")
                sender = d.get("sender_login", "unknown")
                is_me = sender == self.login_name
                color = GREEN if is_me else YELLOW
                self._print(f"[{ts}] {color}{sender}{RESET}: {d['content']}")

            elif t == "joined":
                cid = data["chat_id"]
                self._subscribed_chats.add(cid)
                name = self._chat_display_name(cid)
                self._print(f"{DIM}Joined {name}{RESET}")

            elif t == "left":
                cid = data["chat_id"]
                self._subscribed_chats.discard(cid)
                name = self._chat_display_name(cid)
                self._print(f"{DIM}Left {name}{RESET}")

            elif t == "ping":
                pass

            elif t == "error":
                self._print(f"{RED}WS error: {data.get('detail', '')}{RESET}")

    async def ws_receive_loop(self) -> None:
        while not self._stop.is_set():
            try:
                async with websockets.connect(f"{self.ws_url}?token={self.token}") as ws:
                    for cid in self._subscribed_chats:
                        await ws.send(json.dumps({"action": "join", "chat_id": cid}))

                    send_task = asyncio.create_task(self._ws_sender(ws))
                    recv_task = asyncio.create_task(self._ws_receiver(ws))
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
            except (websockets.ConnectionClosed, OSError) as e:
                if not self._stop.is_set():
                    self._print(f"{DIM}WS disconnected, reconnecting in 3s...{RESET}")
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
                self._print(f"  {i}. {GREEN}{name}{RESET}")
            else:
                members = self._format_member_list(c.get("members", []))
                self._print(f"  {i}. {CYAN}{name}{RESET} ({members})")

    def print_history(self, chat_id: str, msgs: list[dict]) -> None:
        name = self._chat_display_name(chat_id)
        if not msgs:
            self._print(f"{DIM}No messages in {name}{RESET}")
            return
        self._print(f"{DIM}--- History of {name} ({len(msgs)} messages) ---{RESET}")
        for m in reversed(msgs):
            ts = datetime.fromisoformat(m["created_at"]).strftime("%H:%M:%S")
            sender = m.get("sender_login", "unknown")
            is_me = sender == self.login_name
            color = GREEN if is_me else YELLOW
            self._print(f"  [{ts}] {color}{sender}{RESET}: {m['content']}")


_HELP_AUTH = """
  /register <login> <pwd>  Register a new user and log in
  /login <login> <pwd>     Log in as existing user
  /quit                    Exit"""

_HELP_FULL = """
  /help                    Show this help
  /chats                   List your chats (numbered)
  /join <ref>              Subscribe to chat + set as current
  /leave <ref>             Unsubscribe from chat
  /enter <ref> [N]         Join + show last N messages
  /switch [ref]            Switch current chat (list if no ref)
  /personal <login>        Create personal chat by login
  /group <name> <id1>...   Create group chat
  /register <l> <p>        Register a new user
  /login <l> <p>           Log in as existing user
  /users <query>           Search users by login
  /messages [N]            Show last N messages in current chat
  /members                 Show members of current chat
  /quit                    Exit
  <any text>               Send message to current chat

Ref can be: number from /chats, login (for personal chats),
            or chat_id (UUID)."""


async def _reload(client: MessengerClient) -> None:
    """Refresh state after login / register."""
    try:
        chats = await client.get_chats()
        if chats:
            print(f"Your chats:")
            client.print_chat_list(chats)
        else:
            print("  No chats yet")
    except Exception:
        pass


async def interactive_mode(client: MessengerClient) -> None:
    already_auth = client.authenticated

    if already_auth:
        print(f"{BOLD}{client.login_name}{RESET} connected")
    else:
        print(f"Not logged in. Use {BOLD}/register{RESET} or {BOLD}/login{RESET}")

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

                if cmd in ("/quit",):
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
                        await _reload(client)
                        print(f"Registered and logged in as {GREEN}{parts[1]}{RESET}")
                    except Exception as e:
                        print(f"{RED}Error: {e}{RESET}")

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
                        await _reload(client)
                        print(f"Logged in as {GREEN}{parts[1]}{RESET}")
                    except Exception as e:
                        print(f"{RED}Error: {e}{RESET}")

                elif not client.authenticated:
                    print(f"Please login first. Use {BOLD}/register{RESET} or {BOLD}/login{RESET}")
                    continue

                elif cmd == "/chats":
                    try:
                        chats = await client.get_chats()
                        if chats:
                            client.print_chat_list(chats)
                        else:
                            print("  No chats")
                    except Exception as e:
                        print(f"{RED}Error: {e}{RESET}")

                elif cmd == "/join":
                    if len(parts) < 2:
                        print("Usage: /join <ref>")
                        continue
                    cid = client.resolve_chat_ref(parts[1])
                    if not cid:
                        print(f"{RED}Chat not found: {parts[1]}{RESET}")
                        continue
                    client.current_chat_id = cid
                    await client.ws_send({"action": "join", "chat_id": cid})
                    name = client._chat_display_name(cid)
                    print(f"Joined {name}")

                elif cmd == "/leave":
                    if len(parts) < 2:
                        print("Usage: /leave <ref>")
                        continue
                    cid = client.resolve_chat_ref(parts[1])
                    if not cid:
                        print(f"{RED}Chat not found: {parts[1]}{RESET}")
                        continue
                    if client.current_chat_id == cid:
                        client.current_chat_id = None
                    await client.ws_send({"action": "leave", "chat_id": cid})
                    name = client._chat_display_name(cid)
                    print(f"Left {name}")

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
                    cid = client.resolve_chat_ref(ref)
                    if not cid:
                        print(f"{RED}Chat not found: {ref}{RESET}")
                        continue
                    if client.current_chat_id != cid:
                        client.current_chat_id = cid
                        await client.ws_send({"action": "join", "chat_id": cid})
                    name = client._chat_display_name(cid)
                    print(f"{BOLD}=== {name} ==={RESET}")
                    try:
                        msgs = await client.get_messages(cid, limit)
                        client.print_history(cid, msgs)
                    except Exception as e:
                        print(f"  {DIM}Could not load history: {e}{RESET}")

                elif cmd == "/switch":
                    if len(parts) < 2:
                        subscribed = [c for c in client._chat_list if c["id"] in client._subscribed_chats]
                        if not subscribed:
                            print("No subscribed chats. Use /join or /enter first.")
                        else:
                            print("Subscribed chats:")
                            for i, c in enumerate(subscribed, 1):
                                name = client._chat_name(c)
                                mark = f" {GREEN}*{RESET}" if c["id"] == client.current_chat_id else ""
                                print(f"  {i}. {name}{mark}")
                            print("Use /switch <number|name> to switch")
                        continue
                    cid = client.resolve_chat_ref(parts[1])
                    if not cid:
                        print(f"{RED}Chat not found: {parts[1]}{RESET}")
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
                        name = client._chat_name(chat)
                        print(f"Chat with {GREEN}{name}{RESET} ready")
                    except Exception as e:
                        print(f"{RED}Error: {e}{RESET}")

                elif cmd == "/group":
                    if len(parts) < 3:
                        print("Usage: /group <name> <user_id1> [user_id2 ...]")
                        continue
                    try:
                        chat = await client.create_group_chat(parts[1], parts[2:])
                        print(f'Group {CYAN}"{parts[1]}"{RESET} created ({len(parts) - 2} members)')
                    except Exception as e:
                        print(f"{RED}Error: {e}{RESET}")

                elif cmd == "/users":
                    if len(parts) < 2:
                        print("Usage: /users <query>")
                        continue
                    try:
                        users = await client.search_users(parts[1])
                        for u in users:
                            print(f"  {u['login']}")
                    except Exception as e:
                        print(f"{RED}Error: {e}{RESET}")

                elif cmd == "/messages":
                    limit = 20
                    if len(parts) >= 2:
                        try:
                            limit = int(parts[1])
                        except ValueError:
                            print("Usage: /messages [N]")
                            continue
                    if not client.current_chat_id:
                        print("No current chat. Use /join, /enter, or /switch first.")
                        continue
                    try:
                        msgs = await client.get_messages(client.current_chat_id, limit)
                        client.print_history(client.current_chat_id, msgs)
                    except Exception as e:
                        print(f"{RED}Error: {e}{RESET}")

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
                        print(f"{RED}Error: {e}{RESET}")

                elif cmd.startswith("/"):
                    print(f"Unknown command: {cmd}")

                elif client.current_chat_id:
                    try:
                        await client.send_message(client.current_chat_id, line)
                    except Exception as e:
                        print(f"{RED}Error: {e}{RESET}")
                else:
                    print("No current chat. Use /join, /enter, or /switch first.")
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
