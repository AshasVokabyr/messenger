import argparse
import asyncio
import json
import sys
from datetime import datetime

import httpx
import websockets


class MessengerClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None
        self.current_chat_id: str | None = None

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
            resp = await c.get(
                f"{self.base_url}/chats/",
                headers={"Authorization": f"Bearer {self.token}"},
            )
            if resp.status_code == 200:
                return resp.json()
            raise RuntimeError(f"Failed to list chats ({resp.status_code})")

    async def create_personal_chat(self, user_id: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self.base_url}/chats/personal/{user_id}",
                headers={"Authorization": f"Bearer {self.token}"},
            )
            if resp.status_code in (200, 201):
                return resp.json()
            raise RuntimeError(f"Failed to create personal chat ({resp.status_code}): {resp.json().get('detail', '')}")

    async def create_group_chat(self, name: str, participant_ids: list[str]) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self.base_url}/chats/group",
                json={"name": name, "participant_ids": participant_ids},
                headers={"Authorization": f"Bearer {self.token}"},
            )
            if resp.status_code == 201:
                return resp.json()
            raise RuntimeError(f"Failed to create group chat ({resp.status_code}): {resp.json().get('detail', '')}")

    async def send_message(self, chat_id: str, content: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self.base_url}/chats/{chat_id}/messages",
                json={"content": content},
                headers={"Authorization": f"Bearer {self.token}"},
            )
            if resp.status_code == 201:
                return resp.json()
            raise RuntimeError(f"Failed to send message ({resp.status_code}): {resp.json().get('detail', '')}")

    def _format_chat(self, chat: dict) -> str:
        members = ", ".join(m["login"] for m in chat.get("members", []))
        if chat["type"] == "personal":
            return f"{chat['id'][:8]}  {members}"
        return f"{chat['id'][:8]}  {chat.get('name', 'Unnamed')} ({members})"

    def _print(self, text: str) -> None:
        print(text, flush=True)


async def receive_loop(ws_url: str, token: str, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with websockets.connect(f"{ws_url}?token={token}") as ws:
                while not stop.is_set():
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if data.get("type") == "message":
                        msg_data = data["data"]
                        ts = datetime.fromisoformat(msg_data["created_at"]).strftime("%H:%M:%S")
                        print(f"\r[{ts}] {msg_data.get('sender_login', 'unknown')}: {msg_data['content']}")
                        print("> ", end="", flush=True)
                    elif data.get("type") == "joined":
                        print(f"\rJoined chat {data['chat_id'][:8]}")
                        print("> ", end="", flush=True)
                    elif data.get("type") == "left":
                        print(f"\rLeft chat {data['chat_id'][:8]}")
                        print("> ", end="", flush=True)
        except websockets.ConnectionClosed:
            if not stop.is_set():
                await asyncio.sleep(2)
        except Exception as e:
            if not stop.is_set():
                print(f"\rWebSocket error: {e}")
                print("> ", end="", flush=True)
                await asyncio.sleep(5)


async def interactive_mode(client: MessengerClient) -> None:
    print(f"Connected as {client.login_name}")
    chats = await client.get_chats()
    if chats:
        for c in chats:
            client._print(f"  {client._format_chat(c)}")
    else:
        client._print("  No chats yet")

    client._print("Type /help for commands")
    client._print("")

    ws_host = client.base_url.replace("http://", "ws://").replace("https://", "wss://")
    stop_event = asyncio.Event()
    ws_task = asyncio.create_task(receive_loop(f"{ws_host}/ws", client.token, stop_event))

    try:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            if line == "/quit":
                break
            elif line == "/help":
                client._print("""
  /help                    Show this help
  /chats                   List your chats
  /join <chat_id>          Subscribe to chat (sets as current)
  /leave <chat_id>         Unsubscribe from chat
  /create_user <l> <p>     Register a new user
  /personal <user_id>      Create personal chat
  /group <name> <id1> ...  Create group chat
  /quit                    Exit
  <any text>               Send message to current chat""")
            elif line == "/chats":
                try:
                    chats = await client.get_chats()
                    for c in chats:
                        client._print(f"  {client._format_chat(c)}")
                except Exception as e:
                    client._print(f"Error: {e}")
            elif line.startswith("/join "):
                args = line.split(maxsplit=1)
                if len(args) < 2:
                    client._print("Usage: /join <chat_id>")
                    continue
                cid = args[1]
                client.current_chat_id = cid
                client._print(f"Current chat set to {cid[:8]}")
            elif line.startswith("/leave "):
                args = line.split(maxsplit=1)
                if len(args) < 2:
                    client._print("Usage: /leave <chat_id>")
                    continue
                client._print(f"To unsubscribe, reconnect without joining chat {args[1][:8]}")
            elif line.startswith("/create_user "):
                parts = line.split()
                if len(parts) < 3:
                    client._print("Usage: /create_user <login> <password>")
                    continue
                mc = MessengerClient(client.base_url)
                try:
                    await mc.register(parts[1], parts[2])
                    client._print(f"User {parts[1]} created (token: {mc.token[:16]}...)")
                except Exception as e:
                    client._print(f"Error: {e}")
            elif line.startswith("/personal "):
                parts = line.split()
                if len(parts) < 2:
                    client._print("Usage: /personal <user_id>")
                    continue
                try:
                    chat = await client.create_personal_chat(parts[1])
                    client._print(f"Personal chat {chat['id']}")
                except Exception as e:
                    client._print(f"Error: {e}")
            elif line.startswith("/group "):
                parts = line.split()
                if len(parts) < 3:
                    client._print("Usage: /group <name> <user_id1> [user_id2 ...]")
                    continue
                name = parts[1]
                ids = parts[2:]
                try:
                    chat = await client.create_group_chat(name, ids)
                    client._print(f"Group chat {chat['id']} created")
                except Exception as e:
                    client._print(f"Error: {e}")
            elif line.startswith("/"):
                client._print(f"Unknown command: {line}")
            elif client.current_chat_id:
                try:
                    await client.send_message(client.current_chat_id, line)
                except Exception as e:
                    client._print(f"Error: {e}")
            else:
                client._print("No current chat. Use /join <chat_id> to select a chat.")
    finally:
        stop_event.set()
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass


async def main() -> None:
    parser = argparse.ArgumentParser(description="Messenger CLI Client")
    parser.add_argument("action", choices=["register", "login", "interactive"],
                        help="register a new user, login, or interactive mode")
    parser.add_argument("login_name", nargs="?", help="login")
    parser.add_argument("password", nargs="?", help="password")
    parser.add_argument("--host", default="http://localhost:8000", help="server URL")

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
