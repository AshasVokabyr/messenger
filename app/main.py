from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.auth.router import router as auth_router
from app.chats.router import router as chats_router
from app.config import settings
from app.kafka.consumer import start_consumer, stop_consumer
from app.kafka.producer import close_producer
from app.logging_config import configure_logging
from app.messages.router import router as messages_router
from app.websocket.router import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await start_consumer()
    yield
    await close_producer()
    await stop_consumer()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(chats_router)
app.include_router(messages_router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})
