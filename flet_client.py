import asyncio
from datetime import datetime

import flet as ft

from client import MessengerClient

CLIENT = MessengerClient("http://localhost:8000")


class ChatApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.current_chat_id: str | None = None
        self._ws_task: asyncio.Task | None = None
        self._selected_tile: ft.ListTile | None = None

        self._login_field = ft.TextField(label="Login", width=300)
        self._pwd_field = ft.TextField(label="Password", password=True, width=300)
        self._error_text = ft.Text("", color=ft.Colors.RED, size=12)

        self._chat_list_view = ft.ListView(expand=True, spacing=2)
        self._msg_list_view = ft.ListView(expand=True, spacing=4, padding=10, auto_scroll=True)
        self._msg_input = ft.TextField(
            hint_text="Type a message...",
            expand=True,
            on_submit=lambda e: self._run_async(self._on_send(e)),
        )

    def _run_async(self, coro):
        asyncio.create_task(coro)

    # ── Screens ──────────────────────────────────────────────

    async def show_login(self):
        self.page.clean()
        self.page.padding = 40
        self.page.appbar = None

        title = ft.Text("Messenger", size=32, weight=ft.FontWeight.BOLD)
        subtitle = ft.Text("Sign in or create an account", size=14, color=ft.Colors.GREY)

        register_btn = ft.ElevatedButton("Register", on_click=lambda e: self._run_async(self._on_register(e)), width=140)
        login_btn = ft.FilledButton("Login", on_click=lambda e: self._run_async(self._on_login(e)), width=140)

        form = ft.Column(
            [
                title,
                subtitle,
                ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
                self._login_field,
                self._pwd_field,
                self._error_text,
                ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                ft.Row([register_btn, login_btn], alignment=ft.MainAxisAlignment.CENTER, spacing=20),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self.page.add(ft.Container(form, alignment=ft.Alignment.CENTER, expand=True))
        self.page.update()

    async def show_main(self):
        self.page.clean()
        self.page.padding = 0

        self.page.appbar = ft.AppBar(
            title=ft.Text(f"Messenger — {CLIENT.login_name}"),
            actions=[ft.TextButton("Logout", on_click=lambda e: self._run_async(self._on_logout(e)))],
            bgcolor=ft.Colors.BLUE_100,
        )

        new_chat_btn = ft.FloatingActionButton(
            icon=ft.Icons.ADD,
            on_click=lambda e: self._run_async(self._on_new_chat(e)),
            width=40,
            height=40,
        )
        left_panel = ft.Container(
            ft.Column(
                [
                    ft.Container(
                        ft.Text("Chats", size=18, weight=ft.FontWeight.BOLD),
                        padding=ft.Padding.only(left=12, top=16, bottom=8),
                    ),
                    ft.Container(self._chat_list_view, expand=True),
                    ft.Container(new_chat_btn, alignment=ft.Alignment.CENTER, padding=10),
                ],
                spacing=0,
            ),
            width=260,
            border=ft.Border.only(right=ft.BorderSide(1, ft.Colors.GREY_300)),
            bgcolor=ft.Colors.GREY_50,
        )

        right_panel = ft.Column(
            [
                self._msg_list_view,
                ft.Container(
                    ft.Row([self._msg_input, ft.IconButton(icon=ft.Icons.SEND, on_click=lambda e: self._run_async(self._on_send(e)))], spacing=8),
                    border=ft.Border.only(top=ft.BorderSide(1, ft.Colors.GREY_300)),
                    padding=10,
                ),
            ],
            spacing=0,
            expand=True,
        )

        self.page.add(ft.Row([left_panel, right_panel], spacing=0, expand=True))
        self.page.update()

        self._ws_task = asyncio.create_task(self._ws_listener())
        await CLIENT.start_ws()
        await self._load_chats()

    # ── Auth handlers ─────────────────────────────────────────

    async def _on_register(self, e):
        await self._auth_action("register")

    async def _on_login(self, e):
        await self._auth_action("login")

    async def _auth_action(self, action: str):
        login = self._login_field.value.strip()
        password = self._pwd_field.value.strip()

        if not login or not password:
            self._error_text.value = "Login and password are required"
            self.page.update()
            return

        self._error_text.value = ""
        self.page.update()

        try:
            if action == "register":
                await CLIENT.register(login, password)
                CLIENT.login_name = login
            else:
                await CLIENT.login(login, password)
                CLIENT.login_name = login
            await self.show_main()
        except Exception as ex:
            self._error_text.value = str(ex)
            self.page.update()

    async def _on_logout(self, e):
        if self._ws_task:
            self._ws_task.cancel()
            self._ws_task = None
        await CLIENT.stop_ws()
        CLIENT.token = None
        CLIENT.login_name = None
        CLIENT.current_chat_id = None
        CLIENT._chats_cache.clear()
        CLIENT._chat_list.clear()
        CLIENT._chat_ids_by_login.clear()
        CLIENT._subscribed_chats.clear()
        self.current_chat_id = None
        self._selected_tile = None
        self._chat_list_view.controls.clear()
        self._msg_list_view.controls.clear()
        await self.show_login()

    # ── Chat list ─────────────────────────────────────────────

    async def _load_chats(self):
        try:
            chats = await CLIENT.get_chats()
        except Exception:
            return
        self._chat_list_view.controls.clear()
        for chat in chats:
            name = CLIENT._chat_name(chat)
            cid = chat["id"]
            tile = ft.ListTile(title=ft.Text(name, size=14), data=cid)
            tile.on_click = lambda e, c=cid: self._run_async(self._on_chat_select(c, e.control))
            if cid == self.current_chat_id:
                tile.bgcolor = ft.Colors.BLUE_100
            self._chat_list_view.controls.append(tile)
        self.page.update()

    async def _on_chat_select(self, chat_id: str, tile: ft.ListTile):
        if self._selected_tile:
            self._selected_tile.bgcolor = None
        self._selected_tile = tile
        tile.bgcolor = ft.Colors.BLUE_100
        self.current_chat_id = chat_id
        CLIENT.current_chat_id = chat_id
        self.page.update()

        await CLIENT.ws_send({"action": "join", "chat_id": chat_id})

        self._msg_list_view.controls.clear()
        self._msg_list_view.controls.append(ft.ProgressRing(width=20, height=20))
        self.page.update()

        try:
            msgs = await CLIENT.get_messages(chat_id, limit=50)
            self._msg_list_view.controls.clear()
            for m in reversed(msgs):
                self._add_message_widget(m)
            self.page.update()
        except Exception as ex:
            self._msg_list_view.controls.clear()
            self._msg_list_view.controls.append(ft.Text(f"Error: {ex}", color=ft.Colors.RED))
            self.page.update()

    # ── Messages ─────────────────────────────────────────────

    def _add_message_widget(self, m: dict):
        is_me = m.get("sender_login") == CLIENT.login_name
        sender = m.get("sender_login", "unknown")
        ts = "..."
        try:
            ts = datetime.fromisoformat(m["created_at"]).strftime("%H:%M")
        except Exception:
            pass

        content = ft.Container(
            ft.Column(
                [
                    ft.Text(sender, size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_600),
                    ft.Text(m["content"], size=14),
                    ft.Text(ts, size=10, color=ft.Colors.GREY_400, text_align=ft.TextAlign.END),
                ],
                spacing=2,
            ),
            bgcolor=ft.Colors.BLUE_50 if is_me else ft.Colors.WHITE,
            border_radius=10,
            padding=10,
            width=400,
            margin=ft.Margin.only(left=100) if is_me else ft.Margin.only(right=100),
        )

        self._msg_list_view.controls.append(
            ft.Row(
                [content],
                alignment=ft.MainAxisAlignment.END if is_me else ft.MainAxisAlignment.START,
            )
        )

    async def _on_send(self, e):
        if not self.current_chat_id:
            return
        text = self._msg_input.value.strip()
        if not text:
            return
        self._msg_input.value = ""
        self.page.update()

        try:
            msg = await CLIENT.send_message(self.current_chat_id, text)
            self._add_message_widget(msg)
            self.page.update()
        except Exception:
            pass

    # ── New chat dialog ──────────────────────────────────────

    async def _on_new_chat(self, e):
        login_field = ft.TextField(label="Login", hint_text="Enter user login")

        async def create_chat(e):
            self.page.dialog.open = False
            self.page.update()
            login = login_field.value.strip()
            if not login:
                return
            try:
                user = await CLIENT.get_user_by_login(login)
                await CLIENT.create_personal_chat(str(user["id"]))
                await self._load_chats()
            except Exception:
                pass

        self.page.dialog = ft.AlertDialog(
            title=ft.Text("New Chat"),
            content=login_field,
            actions=[ft.TextButton("Create", on_click=lambda e: self._run_async(create_chat(e)))],
        )
        self.page.dialog.open = True
        self.page.update()

    # ── WebSocket listener ────────────────────────────────────

    async def _ws_listener(self):
        while True:
            try:
                data = await CLIENT._ws_queue.get()
                t = data.get("type")
                if t == "message":
                    d = data["data"]
                    if d.get("chat_id") == self.current_chat_id:
                        self._add_message_widget(d)
                        self.page.update()
                elif t in ("joined", "left"):
                    await self._load_chats()
            except asyncio.CancelledError:
                break
            except Exception:
                pass


async def main(page: ft.Page):
    page.title = "Messenger"
    page.theme_mode = ft.ThemeMode.LIGHT
    app = ChatApp(page)
    await app.show_login()


if __name__ == "__main__":
    ft.app(target=main)
