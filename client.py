import argparse
import asyncio
import json
import sys
from datetime import datetime

import httpx
import websockets

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"


class MessengerClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
        self.token: str | None = None
        self.login_name: str | None = None
        self.current_chat_id: str | None = None
        self._chats_cache: dict[str, dict] = {}
        self._ws_queue: asyncio.Queue = asyncio.Queue()
        self._subscribed_chats: set[str] = set()
        self._stop = asyncio.Event()
        self._ws_task: asyncio.Task | None = None

    def _prompt(self) -> str:
        ctx = self.login_name or ""
        if self.current_chat_id:
            cc = self.current_chat_id
            if cc in self._chats_cache:
                c = self._chats_cache[cc]
                ctx += "@" + self._resolve_chat_name(c, short=True)
            else:
                ctx += "@" + cc[:12]
        return f"{BOLD}{ctx}{RESET} > " if ctx else "> "

    def _print(self, text: str, end: str = "\n") -> None:
        print(text, end=end, flush=True)

    def _prompted_print(self, text: str) -> None:
        prompt = self._prompt()
        print(f"\r{text}\n{prompt}", end="", flush=True)

    @staticmethod
    def _resolve_chat_name(chat: dict, short: bool = False) -> str:
        if chat["type"] == "personal":
            members = chat.get("members", [])
            me = next((m for m in members if m.get("_me")), None)
            others = [m["login"] for m in members if not m.get("_me")]
            name = others[0] if others else "personal"
        else:
            name = chat.get("name", "Unnamed")
        if short and len(name) > 20:
            name = name[:17] + "..."
        return name

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
                for chat in chats:
                    for m in chat.get("members", []):
                        m["_me"] = m["login"] == self.login_name
                    self._chats_cache[chat["id"]] = chat
                return chats
            raise RuntimeError(f"Failed to list chats ({resp.status_code})")

    async def get_chat(self, chat_id: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{self.base_url}/chats/{chat_id}", headers=await self._auth_header())
            if resp.status_code == 200:
                chat = resp.json()
                for m in chat.get("members", []):
                    m["_me"] = m["login"] == self.login_name
                self._chats_cache[chat["id"]] = chat
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
                for m in chat.get("members", []):
                    m["_me"] = m["login"] == self.login_name
                self._chats_cache[chat["id"]] = chat
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
                for m in chat.get("members", []):
                    m["_me"] = m["login"] == self.login_name
                self._chats_cache[chat["id"]] = chat
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
                self._prompted_print(f"[{ts}] {color}{sender}{RESET}: {d['content']}")

            elif t == "joined":
                cid = data["chat_id"]
                self._subscribed_chats.add(cid)
                self._prompted_print(f"{CYAN}Joined chat {cid[:12]}{RESET}")

            elif t == "left":
                cid = data["chat_id"]
                self._subscribed_chats.discard(cid)
                self._prompted_print(f"{CYAN}Left chat {cid[:12]}{RESET}")

            elif t == "ping":
                pass

            elif t == "error":
                self._prompted_print(f"{YELLOW}WS error: {data.get('detail', '')}{RESET}")

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
                    self._prompted_print(f"{YELLOW}WS disconnected ({e}), reconnecting in 3s...{RESET}")
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


async def interactive_mode(client: MessengerClient) -> None:
    print(f"{BOLD}{client.login_name}{RESET} connected")
    chats = await client.get_chats()
    if chats:
        for c in chats:
            name = client._resolve_chat_name(c)
            print(f"  {c['id'][:12]}  {name}")
    else:
        print("  No chats yet")

    print("Type /help for commands\n")

    await client.start_ws()

    try:
        while True:
            prompt = client._prompt()
            line = await asyncio.to_thread(lambda: input(prompt))
            if not line:
                continue

            parts = line.split()
            cmd = parts[0]

            if cmd == "/quit":
                break

            elif cmd == "/help":
                print("""
  /help                    Show this help
  /chats                   List your chats
  /join <chat_id>          Join chat (subscribe + set current)
  /leave <chat_id>         Leave chat (unsubscribe)
  /personal <login>        Create personal chat by login
  /group <name> <id1>...   Create group chat
  /create_user <l> <p>     Register a new user
  /users <query>           Search users by login
  /messages [N]            Show last N messages in current chat
  /members                 Show members of current chat
  /quit                    Exit
  <any text>               Send message to current chat""")

            elif cmd == "/chats":
                try:
                    chats = await client.get_chats()
                    for c in chats:
                        name = client._resolve_chat_name(c)
                        print(f"  {c['id'][:12]}  {name}")
                except Exception as e:
                    print(f"Error: {e}")

            elif cmd == "/join":
                if len(parts) < 2:
                    print("Usage: /join <chat_id>")
                    continue
                cid = parts[1]
                client.current_chat_id = cid
                await client.ws_send({"action": "join", "chat_id": cid})
                print(f"Joining chat {cid[:12]}")

            elif cmd == "/leave":
                if len(parts) < 2:
                    print("Usage: /leave <chat_id>")
                    continue
                cid = parts[1]
                if client.current_chat_id == cid:
                    client.current_chat_id = None
                await client.ws_send({"action": "leave", "chat_id": cid})
                print(f"Leaving chat {cid[:12]}")

            elif cmd == "/create_user":
                if len(parts) < 3:
                    print("Usage: /create_user <login> <password>")
                    continue
                mc = MessengerClient(client.base_url)
                try:
                    await mc.register(parts[1], parts[2])
                    print(f"User {parts[1]} created")
                except Exception as e:
                    print(f"Error: {e}")

            elif cmd == "/personal":
                if len(parts) < 2:
                    print("Usage: /personal <login>")
                    continue
                try:
                    user = await client.get_user_by_login(parts[1])
                    chat = await client.create_personal_chat(str(user["id"]))
                    name = client._resolve_chat_name(chat)
                    print(f"Personal chat {chat['id'][:12]} ({name})")
                except Exception as e:
                    print(f"Error: {e}")

            elif cmd == "/group":
                if len(parts) < 3:
                    print("Usage: /group <name> <user_id1> [user_id2 ...]")
                    continue
                try:
                    chat = await client.create_group_chat(parts[1], parts[2:])
                    print(f"Group chat {chat['id'][:12]} created")
                except Exception as e:
                    print(f"Error: {e}")

            elif cmd == "/users":
                if len(parts) < 2:
                    print("Usage: /users <query>")
                    continue
                try:
                    users = await client.search_users(parts[1])
                    for u in users:
                        print(f"  {u['id']}  {u['login']}")
                except Exception as e:
                    print(f"Error: {e}")

            elif cmd == "/messages":
                limit = 20
                if len(parts) >= 2:
                    try:
                        limit = int(parts[1])
                    except ValueError:
                        print("Usage: /messages [N]")
                        continue
                if not client.current_chat_id:
                    print("No current chat. Use /join <chat_id> first.")
                    continue
                try:
                    msgs = await client.get_messages(client.current_chat_id, limit)
                    for m in reversed(msgs):
                        ts = datetime.fromisoformat(m["created_at"]).strftime("%H:%M:%S")
                        sender = m.get("sender_login", "unknown")
                        is_me = sender == client.login_name
                        color = GREEN if is_me else YELLOW
                        print(f"  [{ts}] {color}{sender}{RESET}: {m['content']}")
                except Exception as e:
                    print(f"Error: {e}")

            elif cmd == "/members":
                if not client.current_chat_id:
                    print("No current chat.")
                    continue
                try:
                    chat = await client.get_chat(client.current_chat_id)
                    for m in chat.get("members", []):
                        tag = " (you)" if m.get("_me") else ""
                        print(f"  {m['login']}{tag}")
                except Exception as e:
                    print(f"Error: {e}")

            elif cmd.startswith("/"):
                print(f"Unknown command: {cmd}")

            elif client.current_chat_id:
                try:
                    await client.send_message(client.current_chat_id, line)
                except Exception as e:
                    print(f"Error: {e}")
            else:
                print("No current chat. Use /join <chat_id> to select a chat.")
    finally:
        await client.stop_ws()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Messenger CLI Client")
    parser.add_argument("action", choices=["register", "login", "interactive"])
    parser.add_argument("login_name", nargs="?")
    parser.add_argument("password", nargs="?")
    parser.add_argument("--host", default="http://localhost:8000")

    args = parser.parse_args()
    client = MessengerClient(args.host)

    if args.action in ("register", "login"):
        if not args.login_name or not args.password:
            print(f"Usage: python client.py {args.action} <login> <password> [--host URL]")
            sys.exit(1)
        try:
            fn = client.register if args.action == "register" else client.login
            token = await fn(args.login_name, args.password)
            print(f"{args.action.capitalize()}d as {args.login_name}")
            print(f"Token: {token}")
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)

    if args.action == "interactive":
        if not args.login_name or not args.password:
            print("Usage: python client.py interactive <login> <password> [--host URL]")
            sys.exit(1)
        try:
            await client.login(args.login_name, args.password)
            client.login_name = args.login_name
            await interactive_mode(client)
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
