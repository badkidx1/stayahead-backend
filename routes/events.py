from fastapi import APIRouter, HTTPException
from bson import ObjectId
from datetime import datetime
from typing import List
import logging

from database import db
from models import EventCreate, Event
from notifications import notify_all_members

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/events", tags=["events"])


@router.post("/create", response_model=Event)
async def create_event(event_data: EventCreate):
    user = await db.users.find_one({"_id": ObjectId(event_data.createdBy)})
    if not user or user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Only admins can create events")

    event_doc = {
        "title": event_data.title,
        "description": event_data.description,
        "date": event_data.date,
        "createdBy": event_data.createdBy,
        "createdAt": datetime.utcnow()
    }
    result = await db.events.insert_one(event_doc)
    event_doc['_id'] = str(result.inserted_id)

    await notify_all_members(
        f"\U0001f4e2 New Event: {event_data.title}",
        f"{event_data.description} - {event_data.date}",
        {'type': 'event', 'eventId': event_doc['_id']}
    )

    return Event(
        id=event_doc['_id'],
        title=event_doc['title'],
        description=event_doc['description'],
        date=event_doc['date'],
        createdBy=event_doc['createdBy'],
        createdAt=event_doc['createdAt']
    )


@router.get("/all", response_model=List[Event])
async def get_all_events():
    events = await db.events.find().sort("date", -1).to_list(100)
    return [Event(
        id=str(event['_id']),
        title=event['title'],
        description=event['description'],
        date=event['date'],
        createdBy=event['createdBy'],
        createdAt=event['createdAt']
    ) for event in events]


@router.delete("/{event_id}")
async def delete_event(event_id: str, userId: str):
    user = await db.users.find_one({"_id": ObjectId(userId)})
    if not user or user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Only admins can delete events")

    result = await db.events.delete_one({"_id": ObjectId(event_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"success": True}
