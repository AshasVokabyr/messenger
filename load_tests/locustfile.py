from locust import HttpUser, between, task


class MessengerUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def health(self):
        self.client.get("/health")
