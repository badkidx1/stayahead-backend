from fastapi import APIRouter
from datetime import datetime
from typing import List
import secrets
import logging

from database import db
from models import Message, MessageCreate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("/chat-key")
async def get_chat_key():
    """Get the shared chat encryption key (creates one if it doesn't exist)"""
    settings = await db.settings.find_one({"key": "chatEncryptionKey"})
    if not settings:
        # Generate a new shared key
        chat_key = secrets.token_hex(32)
        await db.settings.insert_one({
            "key": "chatEncryptionKey",
            "value": chat_key,
            "createdAt": datetime.utcnow()
        })
        return {"chatKey": chat_key}
    return {"chatKey": settings["value"]}


@router.get("/all", response_model=List[Message])
async def get_all_messages():
    messages = await db.messages.find().sort("timestamp", -1).limit(100).to_list(100)
    messages.reverse()  # Show oldest first
    return [Message(
        id=str(msg['_id']),
        encryptedContent=msg['encryptedContent'],
        senderId=msg['senderId'],
        senderName=msg['senderName'],
        timestamp=msg['timestamp'],
        iv=msg['iv']
    ) for msg in messages]


@router.post("/send", response_model=Message)
async def send_message(message_data: MessageCreate):
    message_doc = {
        "encryptedContent": message_data.encryptedContent,
        "senderId": message_data.senderId,
        "senderName": message_data.senderName,
        "timestamp": datetime.utcnow(),
        "iv": message_data.iv
    }
    result = await db.messages.insert_one(message_doc)
    message_doc['_id'] = str(result.inserted_id)

    return Message(
        id=message_doc['_id'],
        encryptedContent=message_doc['encryptedContent'],
        senderId=message_doc['senderId'],
        senderName=message_doc['senderName'],
        timestamp=message_doc['timestamp'],
        iv=message_doc['iv']
    )
