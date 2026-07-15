import time
import uuid


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        start_time = time.monotonic()

        scope["request_id"] = request_id
        scope["start_time"] = start_time

        await self.app(scope, receive, send)
