import os
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

import httpx
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from pyrogram import Client
from pyrogram.handlers import MessageHandler
from pyrogram.errors import (
    BadRequest,
    Unauthorized,
    Flood,
    PeerIdInvalid,
    UserNotParticipant,
    ChannelPrivate,
)
from pyrogram import filters
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

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
MONITOR_CHAT_IDS = os.getenv("MONITOR_CHAT_IDS", "")
TRACK_EXPIRY_HOURS = int(os.getenv("TRACK_EXPIRY_HOURS", "24"))

if not all([API_ID, API_HASH, SESSION_STRING, API_KEY]):
    raise ValueError(
        "Missing required environment variables: API_ID, API_HASH, SESSION_STRING, API_KEY"
    )

monitor_chat_ids: List[int] = []
if MONITOR_CHAT_IDS:
    monitor_chat_ids = [int(cid.strip()) for cid in MONITOR_CHAT_IDS.split(",") if cid.strip()]

security = HTTPBearer()
app_client: Optional[Client] = None
my_user_id: Optional[int] = None

tracked_messages: Dict[int, List[Tuple[int, datetime]]] = defaultdict(list)


class SendMessageRequest(BaseModel):
    chat_id: str = Field(..., description="Chat ID or username (e.g., @username or numeric ID)")
    message: str = Field(..., min_length=1, max_length=4096, description="Message text to send")


class SendMessageResponse(BaseModel):
    success: bool
    message_id: Optional[int] = None
    chat_id: str
    error: Optional[str] = None


class ClickButtonRequest(BaseModel):
    chat_id: str = Field(..., description="Chat ID or username of the bot")
    message_id: int = Field(..., description="Message ID that contains the inline keyboard")
    button_text: Optional[str] = Field(None, description="Button text to click (partial match)")
    button_data: Optional[str] = Field(None, description="Button callback data (exact match)")



class ClickButtonResponse(BaseModel):
    success: bool
    chat_id: str
    message_id: int
    button_clicked: Optional[str] = None
    error: Optional[str] = None


class ButtonItem(BaseModel):
    text: str
    callback_data: Optional[str] = None
    url: Optional[str] = None


class GetButtonsResponse(BaseModel):
    success: bool
    chat_id: str
    message_id: int
    has_keyboard: bool
    buttons: List[List[ButtonItem]]
    callback_response: Optional[str] = None
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


class MediaInfo(BaseModel):
    type: str
    file_id: Optional[str] = None
    file_unique_id: Optional[str] = None
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[int] = None
    caption: Optional[str] = None


class MessageItem(BaseModel):
    message_id: int
    date: str
    text: Optional[str] = None
    from_user: Optional[FromUser] = None
    media: Optional[MediaInfo] = None


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


def extract_media_info(message) -> Optional[MediaInfo]:
    """Extract media information from a Pyrogram message."""
    if not message.media:
        return None
    
    media_type = None
    file_id = None
    file_unique_id = None
    file_name = None
    mime_type = None
    file_size = None
    width = None
    height = None
    duration = None
    
    # Handle different media types
    if message.photo:
        media_type = "photo"
        # Get the largest photo size
        photo = message.photo
        file_id = photo.file_id
        file_unique_id = photo.file_unique_id
        file_size = photo.file_size
        width = photo.width
        height = photo.height
    
    elif message.video:
        media_type = "video"
        video = message.video
        file_id = video.file_id
        file_unique_id = video.file_unique_id
        file_name = video.file_name
        mime_type = video.mime_type
        file_size = video.file_size
        width = video.width
        height = video.height
        duration = video.duration
    
    elif message.animation:
        media_type = "animation"  # GIF
        animation = message.animation
        file_id = animation.file_id
        file_unique_id = animation.file_unique_id
        file_name = animation.file_name
        mime_type = animation.mime_type
        file_size = animation.file_size
        width = animation.width
        height = animation.height
        duration = animation.duration
    
    elif message.document:
        media_type = "document"
        document = message.document
        file_id = document.file_id
        file_unique_id = document.file_unique_id
        file_name = document.file_name
        mime_type = document.mime_type
        file_size = document.file_size
    
    elif message.audio:
        media_type = "audio"
        audio = message.audio
        file_id = audio.file_id
        file_unique_id = audio.file_unique_id
        file_name = audio.file_name
        mime_type = audio.mime_type
        file_size = audio.file_size
        duration = audio.duration
    
    elif message.voice:
        media_type = "voice"
        voice = message.voice
        file_id = voice.file_id
        file_unique_id = voice.file_unique_id
        mime_type = voice.mime_type
        file_size = voice.file_size
        duration = voice.duration
    
    elif message.video_note:
        media_type = "video_note"
        video_note = message.video_note
        file_id = video_note.file_id
        file_unique_id = video_note.file_unique_id
        file_size = video_note.file_size
        width = video_note.width
        height = video_note.height
        duration = video_note.duration
    
    elif message.sticker:
        media_type = "sticker"
        sticker = message.sticker
        file_id = sticker.file_id
        file_unique_id = sticker.file_unique_id
        file_size = sticker.file_size
        width = sticker.width
        height = sticker.height
        mime_type = "image/webp" if sticker.is_animated or sticker.is_video else "image/webp"
    
    elif message.contact:
        media_type = "contact"
        contact = message.contact
        file_id = None  # Contacts don't have file_id
        file_name = contact.first_name
        if contact.last_name:
            file_name += f" {contact.last_name}"
        mime_type = "text/vcard"
    
    elif message.location:
        media_type = "location"
        location = message.location
        file_id = None  # Locations don't have file_id
        width = int(location.latitude * 1000000) if location.latitude else None
        height = int(location.longitude * 1000000) if location.longitude else None
    
    elif message.venue:
        media_type = "venue"
        venue = message.venue
        file_id = None
        file_name = venue.title
    
    elif message.poll:
        media_type = "poll"
        poll = message.poll
        file_id = poll.id
        file_name = poll.question
    
    elif message.dice:
        media_type = "dice"
        dice = message.dice
        file_id = None
        file_name = f"{dice.emoji} - Value: {dice.value}"
    
    elif message.game:
        media_type = "game"
        game = message.game
        file_id = None
        file_name = game.title
    
    elif message.web_page:
        media_type = "web_page"
        web_page = message.web_page
        file_id = None
        file_name = web_page.title
        mime_type = "text/html"
        if web_page.photo:
            width = web_page.photo.width
            height = web_page.photo.height
    
    if media_type:
        return MediaInfo(
            type=media_type,
            file_id=file_id,
            file_unique_id=file_unique_id,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
            width=width,
            height=height,
            duration=duration,
            caption=message.caption
        )
    
    return None


async def cleanup_expired_tracking():
    while True:
        await asyncio.sleep(3600)
        cutoff = datetime.now() - timedelta(hours=TRACK_EXPIRY_HOURS)
        for chat_id in list(tracked_messages.keys()):
            tracked_messages[chat_id] = [
                (mid, ts) for mid, ts in tracked_messages[chat_id] if ts > cutoff
            ]
            if not tracked_messages[chat_id]:
                del tracked_messages[chat_id]
        logger.info("Cleaned up expired message tracking")


async def send_webhook(payload: dict):
    if not WEBHOOK_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(WEBHOOK_URL, json=payload)
            logger.info(f"Webhook sent: {response.status_code}")
    except Exception as e:
        logger.error(f"Webhook error: {e}")


async def handle_incoming_message(client, message):
    global my_user_id
    
    if not WEBHOOK_URL:
        return
    
    chat_id = message.chat.id
    
    if monitor_chat_ids and chat_id not in monitor_chat_ids:
        return
    
    if not message.reply_to_message:
        return
    
    reply_to_id = message.reply_to_message.id
    reply_to_user_id = message.reply_to_message.from_user.id if message.reply_to_message.from_user else None
    
    is_reply_to_tracked = any(mid == reply_to_id for mid, ts in tracked_messages.get(chat_id, []))
    is_reply_to_me = reply_to_user_id == my_user_id
    
    if not (is_reply_to_tracked or is_reply_to_me):
        return
    
    payload = {
        "event": "reply_received",
        "timestamp": datetime.now().isoformat(),
        "chat": {
            "id": chat_id,
            "title": message.chat.title or message.chat.first_name or "Unknown",
            "type": str(message.chat.type).split(".")[-1].lower() if message.chat.type else "unknown"
        },
        "message": {
            "id": message.id,
            "text": message.text or message.caption,
            "date": message.date.isoformat() if message.date else ""
        },
        "from_user": {
            "id": message.from_user.id if message.from_user else None,
            "username": message.from_user.username if message.from_user else None,
            "first_name": message.from_user.first_name if message.from_user else None,
            "is_bot": message.from_user.is_bot if message.from_user else False
        },
        "reply_to_message": {
            "id": reply_to_id,
            "text": message.reply_to_message.text or message.reply_to_message.caption,
            "date": message.reply_to_message.date.isoformat() if message.reply_to_message.date else "",
            "from_user": {
                "id": reply_to_user_id,
                "username": message.reply_to_message.from_user.username if message.reply_to_message.from_user else None
            }
        }
    }
    
    logger.info(f"Reply detected in chat {chat_id}, forwarding to webhook")
    await send_webhook(payload)


def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    if credentials.credentials != API_KEY:
        logger.warning("Invalid API key attempt")
        raise HTTPException(status_code=401, detail="Invalid API key")
    return credentials.credentials


@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_client, my_user_id
    
    logger.info("Starting Pyrogram client...")
    app_client = Client(
        "telegram_api",
        api_id=int(API_ID),
        api_hash=API_HASH,
        session_string=SESSION_STRING,
        in_memory=True,
    )
    await app_client.start()
    
    me = await app_client.get_me()
    my_user_id = me.id
    logger.info(f"Logged in as {me.first_name} (ID: {my_user_id})")
    
    app_client.add_handler(MessageHandler(handle_incoming_message, filters.incoming))
    
    cleanup_task = asyncio.create_task(cleanup_expired_tracking())
    logger.info("Pyrogram client started successfully")
    
    yield
    logger.info("Stopping Pyrogram client...")
    if app_client:
        await app_client.stop()
    logger.info("Pyrogram client stopped")


app = FastAPI(
    title="Telegram Personal API",
    description="REST API untuk mengirim pesan Telegram menggunakan akun personal. By Mas Faiz Code.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/",
    redoc_url=None,
)


@app.get("/info")
async def info():
    return {
        "app_name": "Telegram Personal API By Mas Faiz Code",
        "version": "1.0.0",
        "status": "running",
        "description": "REST API untuk mengirim pesan Telegram menggunakan akun personal",
        "endpoints": {
            "GET /": "Interactive API documentation (Swagger)",
            "GET /info": "API information",
            "POST /send-message": "Send Telegram message",
            "GET /get-messages": "Fetch chat history with media support",
            "GET /download-media": "Download media file by file_id",
            "POST /click-button": "Click inline keyboard button",
            "GET /get-buttons": "Get inline keyboard buttons from a message",
            "GET /get-chats": "List all chats/groups",
            "GET /me": "Get connected account info"
        },
        "webhook": {
            "enabled": bool(WEBHOOK_URL),
            "monitored_chats": monitor_chat_ids or "all"
        },
        "authentication": "Bearer token required for all endpoints except /",
        "github": "https://github.com/masfaiz-code/telegram-personal-api"
    }


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
        original_chat_id = chat_id
        if chat_id.lstrip("-").isdigit():
            chat_id = int(chat_id)

        msg = await app_client.send_message(chat_id=chat_id, text=request.message)
        
        numeric_chat_id = msg.chat.id
        tracked_messages[numeric_chat_id].append((msg.id, datetime.now()))
        logger.info(f"Tracking message {msg.id} in chat {numeric_chat_id}")
        
        logger.info(f"Message sent successfully to {request.chat_id}")
        return SendMessageResponse(
            success=True,
            message_id=msg.id,
            chat_id=original_chat_id,
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


async def get_message_by_id(chat_id, message_id: int):
    try:
        message = await app_client.get_messages(chat_id, message_id)
        if message:
            return message
        return None
    except Exception as e:
        logger.warning(f"get_messages failed: {e}, falling back to get_chat_history")
        async for msg in app_client.get_chat_history(chat_id=chat_id, limit=20):
            if msg.id == message_id:
                return msg
        return None


@app.post(
    "/click-button",
    response_model=ClickButtonResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def click_button(
    request: ClickButtonRequest,
    api_key: str = Depends(verify_api_key),
):
    if not request.button_text and not request.button_data:
        raise HTTPException(
            status_code=400,
            detail="Either button_text or button_data must be provided"
        )
    
    try:
        chat_id = request.chat_id
        if chat_id.lstrip("-").isdigit():
            chat_id = int(chat_id)
        
        message = await get_message_by_id(chat_id, request.message_id)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        if not message.reply_markup:
            raise HTTPException(status_code=400, detail="Message has no inline keyboard")
        
        target_button = None
        for row in message.reply_markup.inline_keyboard:
            for button in row:
                btn_callback_data = button.callback_data
                if isinstance(btn_callback_data, bytes):
                    btn_callback_data = btn_callback_data.decode('utf-8')
                
                if request.button_text:
                    if request.button_text.lower() in button.text.lower():
                        target_button = button
                        target_callback_data = btn_callback_data
                        break
                elif request.button_data:
                    if btn_callback_data == request.button_data:
                        target_button = button
                        target_callback_data = btn_callback_data
                        break
            if target_button:
                break
        
        if not target_button:
            raise HTTPException(
                status_code=404,
                detail=f"Button not found: {request.button_text or request.button_data}"
            )
        
        callback_response = await app_client.request_callback_answer(
            chat_id=chat_id,
            message_id=request.message_id,
            callback_data=target_callback_data,
        )
        
        response_text = None
        if callback_response:
            response_text = callback_response.message or callback_response.url
        
        logger.info(f"Clicked button '{target_button.text}' in chat {request.chat_id}")
        
        return ClickButtonResponse(
            success=True,
            chat_id=request.chat_id,
            message_id=request.message_id,
            button_clicked=target_button.text,
            callback_response=response_text,
        )
    except HTTPException:
        raise
    except Flood as e:
        logger.error(f"Flood wait: {e.value} seconds")
        raise HTTPException(status_code=429, detail=f"Rate limited. Please wait {e.value} seconds")
    except Exception as e:
        logger.error(f"Error clicking button: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/get-buttons",
    response_model=GetButtonsResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def get_buttons(
    chat_id: str,
    message_id: int,
    api_key: str = Depends(verify_api_key),
):
    try:
        target_chat = chat_id
        if target_chat.lstrip("-").isdigit():
            target_chat = int(target_chat)
        
        message = await get_message_by_id(target_chat, message_id)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        if not message.reply_markup:
            return {
                "success": True,
                "chat_id": chat_id,
                "message_id": message_id,
                "has_keyboard": False,
                "buttons": [],
                "note": "No reply_markup found in this message"
            }
        
        if not hasattr(message.reply_markup, 'inline_keyboard'):
            return {
                "success": True,
                "chat_id": chat_id,
                "message_id": message_id,
                "has_keyboard": False,
                "buttons": [],
                "note": "Message has reply_markup but no inline_keyboard"
            }
        
        buttons = []
        for row_index, row in enumerate(message.reply_markup.inline_keyboard):
            for btn_index, button in enumerate(row):
                callback_data = button.callback_data
                if isinstance(callback_data, bytes):
                    callback_data = callback_data.decode('utf-8')
                
                buttons.append({
                    "row": row_index,
                    "column": btn_index,
                    "text": button.text,
                    "callback_data": callback_data,
                    "url": getattr(button, 'url', None)
                })
        
        logger.info(f"Fetched {len(buttons)} buttons from message {message_id} in chat {chat_id}")
        
        return {
            "success": True,
            "chat_id": chat_id,
            "message_id": message_id,
            "has_keyboard": True,
            "buttons": buttons,
            "total_buttons": len(buttons)
        }
    except HTTPException:
        raise
    except PeerIdInvalid:
        logger.error(f"Invalid chat_id: {chat_id}")
        raise HTTPException(status_code=404, detail="Invalid chat_id or user not found")
    except Exception as e:
        logger.error(f"Error fetching buttons: {e}")
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
            
            # Extract media information
            media_info = extract_media_info(msg)
            
            messages.append(MessageItem(
                message_id=msg.id,
                date=msg.date.isoformat() if msg.date else "",
                text=msg.text or msg.caption,
                from_user=from_user,
                media=media_info,
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


@app.get(
    "/download-media",
    responses={
        401: {"model": ErrorResponse},
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def download_media(
    file_id: str = Query(..., description="File ID of the media to download"),
    file_name: Optional[str] = Query(None, description="Original file name (e.g., bmg2026cowa.gif)"),
    mime_type: Optional[str] = Query(None, description="MIME type (e.g., image/gif, video/mp4)"),
    api_key: str = Depends(verify_api_key),
):
    """
    Download media file by file_id.
    Returns the file as a streaming response with appropriate content-type.
    
    Recommendation: Pass file_name and mime_type from get-messages response for correct file extension.
    """
    try:
        if not file_id:
            raise HTTPException(status_code=400, detail="file_id is required")
        
        # Download the file using Pyrogram
        downloaded_file = await app_client.download_media(file_id, in_memory=True)
        
        if not downloaded_file:
            raise HTTPException(status_code=404, detail="File not found or could not be downloaded")
        
        # Use provided mime_type or default
        content_type = mime_type if mime_type else "application/octet-stream"
        
        # Use provided file_name or generate from file_id
        if file_name:
            filename = file_name
        else:
            # Try to guess extension from mime_type
            ext = ".bin"
            mime_to_ext = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "image/webp": ".webp",
                "video/mp4": ".mp4",
                "video/avi": ".avi",
                "video/mov": ".mov",
                "audio/mpeg": ".mp3",
                "audio/ogg": ".ogg",
                "audio/wav": ".wav",
                "application/pdf": ".pdf",
                "application/zip": ".zip",
                "text/plain": ".txt",
            }
            if mime_type and mime_type in mime_to_ext:
                ext = mime_to_ext[mime_type]
            filename = f"file_{file_id[:20]}{ext}"
        
        logger.info(f"Downloading media file: {filename} (type: {content_type}, file_id: {file_id[:20]}...)")
        
        # Create streaming response
        return StreamingResponse(
            iter([downloaded_file.getvalue()]),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
        
    except HTTPException:
        raise
    except Flood as e:
        logger.error(f"Flood wait: {e.value} seconds")
        raise HTTPException(status_code=429, detail=f"Rate limited. Please wait {e.value} seconds")
    except Exception as e:
        logger.error(f"Error downloading media: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
