import os
import logging
from contextlib import asynccontextmanager
from typing import Optional, List
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from pyrogram import Client
from pyrogram.errors import (
    BadRequest,
    Unauthorized,
    Flood,
    PeerIdInvalid,
    UserNotParticipant,
    ChannelPrivate,
)
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
API_KEY = os.getenv("API_KEY")

if not all([API_ID, API_HASH, SESSION_STRING, API_KEY]):
    raise ValueError(
        "Missing required environment variables: API_ID, API_HASH, SESSION_STRING, API_KEY"
    )

security = HTTPBearer()
app_client: Optional[Client] = None


class SendMessageRequest(BaseModel):
    chat_id: str = Field(..., description="Chat ID or username (e.g., @username or numeric ID)")
    message: str = Field(..., min_length=1, max_length=4096, description="Message text to send")


class SendMessageResponse(BaseModel):
    success: bool
    message_id: Optional[int] = None
    chat_id: str
    error: Optional[str] = None


class FromUser(BaseModel):
    id: int
    username: Optional[str] = None
    first_name: str
    is_bot: bool = False


class MeResponse(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    phone_number: Optional[str] = None


class MessageItem(BaseModel):
    message_id: int
    date: str
    text: Optional[str] = None
    from_user: Optional[FromUser] = None


class GetMessagesResponse(BaseModel):
    success: bool
    chat_id: str
    messages: List[MessageItem]
    error: Optional[str] = None


class ChatItem(BaseModel):
    id: int
    title: str
    type: str
    username: Optional[str] = None


class GetChatsResponse(BaseModel):
    success: bool
    chats: List[ChatItem]
    error: Optional[str] = None


class ErrorResponse(BaseModel):
    detail: str


def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    if credentials.credentials != API_KEY:
        logger.warning("Invalid API key attempt")
        raise HTTPException(status_code=401, detail="Invalid API key")
    return credentials.credentials


@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_client
    logger.info("Starting Pyrogram client...")
    app_client = Client(
        "telegram_api",
        api_id=int(API_ID),
        api_hash=API_HASH,
        session_string=SESSION_STRING,
        in_memory=True,
    )
    await app_client.start()
    logger.info("Pyrogram client started successfully")
    yield
    logger.info("Stopping Pyrogram client...")
    if app_client:
        await app_client.stop()
    logger.info("Pyrogram client stopped")


app = FastAPI(
    title="Telegram Personal API",
    description="REST API for sending Telegram messages using personal account",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get(
    "/me",
    response_model=MeResponse,
    responses={401: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def get_me(api_key: str = Depends(verify_api_key)):
    try:
        me = await app_client.get_me()
        return MeResponse(
            id=me.id,
            first_name=me.first_name,
            last_name=me.last_name,
            username=me.username,
            phone_number=me.phone_number,
        )
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/send-message",
    response_model=SendMessageResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def send_message(
    request: SendMessageRequest,
    api_key: str = Depends(verify_api_key),
):
    try:
        chat_id = request.chat_id
        if chat_id.lstrip("-").isdigit():
            chat_id = int(chat_id)

        msg = await app_client.send_message(chat_id=chat_id, text=request.message)
        logger.info(f"Message sent successfully to {request.chat_id}")
        return SendMessageResponse(
            success=True,
            message_id=msg.id,
            chat_id=request.chat_id,
        )
    except PeerIdInvalid:
        logger.error(f"Invalid chat_id: {request.chat_id}")
        raise HTTPException(status_code=404, detail="Invalid chat_id or user not found")
    except UserNotParticipant:
        logger.error(f"Not a participant in chat: {request.chat_id}")
        raise HTTPException(status_code=403, detail="Not a participant in this chat")
    except ChannelPrivate:
        logger.error(f"Channel is private: {request.chat_id}")
        raise HTTPException(status_code=403, detail="Cannot access private channel")
    except Flood as e:
        logger.error(f"Flood wait: {e.value} seconds")
        raise HTTPException(
            status_code=429,
            detail=f"Rate limited. Please wait {e.value} seconds",
        )
    except BadRequest as e:
        logger.error(f"Bad request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Unauthorized as e:
        logger.error(f"Unauthorized: {e}")
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    except Exception as e:
        logger.error(f"Unexpected error sending message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/get-messages",
    response_model=GetMessagesResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def get_messages(
    chat_id: str,
    limit: int = 20,
    api_key: str = Depends(verify_api_key),
):
    try:
        target_chat = chat_id
        if target_chat.lstrip("-").isdigit():
            target_chat = int(target_chat)

        messages = []
        async for msg in app_client.get_chat_history(chat_id=target_chat, limit=limit):
            from_user = None
            if msg.from_user:
                from_user = FromUser(
                    id=msg.from_user.id,
                    username=msg.from_user.username,
                    first_name=msg.from_user.first_name or "",
                    is_bot=msg.from_user.is_bot or False,
                )
            messages.append(MessageItem(
                message_id=msg.id,
                date=msg.date.isoformat() if msg.date else "",
                text=msg.text or msg.caption,
                from_user=from_user,
            ))

        logger.info(f"Fetched {len(messages)} messages from {chat_id}")
        return GetMessagesResponse(
            success=True,
            chat_id=chat_id,
            messages=messages,
        )
    except PeerIdInvalid:
        logger.error(f"Invalid chat_id: {chat_id}")
        raise HTTPException(status_code=404, detail="Invalid chat_id or user not found")
    except ChannelPrivate:
        logger.error(f"Channel is private: {chat_id}")
        raise HTTPException(status_code=403, detail="Cannot access private channel")
    except Flood as e:
        logger.error(f"Flood wait: {e.value} seconds")
        raise HTTPException(status_code=429, detail=f"Rate limited. Please wait {e.value} seconds")
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/get-chats",
    response_model=GetChatsResponse,
    responses={
        401: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def get_chats(api_key: str = Depends(verify_api_key)):
    try:
        chats = []
        async for dialog in app_client.get_dialogs(limit=50):
            chat = dialog.chat
            chats.append(ChatItem(
                id=chat.id,
                title=chat.title or chat.first_name or "Unknown",
                type=str(chat.type).split(".")[-1].lower() if chat.type else "unknown",
                username=chat.username,
            ))

        logger.info(f"Fetched {len(chats)} chats")
        return GetChatsResponse(
            success=True,
            chats=chats,
        )
    except Flood as e:
        logger.error(f"Flood wait: {e.value} seconds")
        raise HTTPException(status_code=429, detail=f"Rate limited. Please wait {e.value} seconds")
    except Exception as e:
        logger.error(f"Error fetching chats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
