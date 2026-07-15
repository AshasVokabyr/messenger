import random
import uuid

from locust import HttpUser, between, task

REGISTERED: list[dict] = []


class MessengerUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        login = f"load_{uuid.uuid4().hex[:12]}"
        password = "test123"

        resp = self.client.post(
            "/auth/register",
            json={"login": login, "password": password},
            name="/auth/register",
        )
        if resp.status_code == 201:
            self.token = resp.json()["access_token"]
        else:
            resp = self.client.post(
                "/auth/login",
                json={"login": login, "password": password},
                name="/auth/login",
            )
            if resp.status_code == 200:
                self.token = resp.json()["access_token"]
            else:
                self.token = None
                return

        self.login = login
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.my_chats: list[str] = []

        resp = self.client.get(
            f"/users/by-login/{login}",
            headers=self.headers,
            name="/users/by-login/[login]",
        )
        if resp.status_code == 200:
            self.user_id = resp.json()["id"]
            REGISTERED.append({"login": login, "user_id": self.user_id})

    @task(7)
    def send_message(self):
        if not self.token or not self.my_chats:
            return
        chat_id = random.choice(self.my_chats)
        content = f"loadtest_{uuid.uuid4().hex[:16]}"
        self.client.post(
            f"/chats/{chat_id}/messages",
            json={"content": content},
            headers=self.headers,
            name="/chats/[chat_id]/messages [POST]",
        )

    @task(2)
    def get_history(self):
        if not self.token or not self.my_chats:
            return
        chat_id = random.choice(self.my_chats)
        self.client.get(
            f"/chats/{chat_id}/messages?limit=20",
            headers=self.headers,
            name="/chats/[chat_id]/messages [GET]",
        )

    @task(1)
    def create_chat(self):
        if not self.token or len(REGISTERED) < 2:
            return
        others = [u for u in REGISTERED if u["login"] != self.login]
        if not others:
            return
        target = random.choice(others)
        resp = self.client.post(
            f"/chats/personal/{target['user_id']}",
            headers=self.headers,
            name="/chats/personal/[user_id]",
        )
        if resp.status_code in (200, 201):
            cid = resp.json()["id"]
            if cid not in self.my_chats:
                self.my_chats.append(cid)
