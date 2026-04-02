from fastapi import APIRouter
from datetime import datetime
from typing import List
import logging

from database import db
from models import ContactInfo, ContactInfoCreate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contacts", tags=["contacts"])


@router.post("/create", response_model=ContactInfo)
async def create_contact(contact_data: ContactInfoCreate):
    existing = await db.contacts.find_one({"userId": contact_data.userId})
    if existing:
        await db.contacts.update_one(
            {"_id": existing["_id"]},
            {"$set": {
                "userName": contact_data.userName,
                "phoneNumber": contact_data.phoneNumber,
                "updatedAt": datetime.utcnow()
            }}
        )
        existing['userName'] = contact_data.userName
        existing['phoneNumber'] = contact_data.phoneNumber
        return ContactInfo(
            id=str(existing['_id']),
            userId=existing['userId'],
            userName=existing['userName'],
            phoneNumber=existing['phoneNumber'],
            createdAt=existing['createdAt']
        )

    contact_doc = {
        "userId": contact_data.userId,
        "userName": contact_data.userName,
        "phoneNumber": contact_data.phoneNumber,
        "createdAt": datetime.utcnow()
    }
    result = await db.contacts.insert_one(contact_doc)
    contact_doc['_id'] = str(result.inserted_id)

    return ContactInfo(
        id=contact_doc['_id'],
        userId=contact_doc['userId'],
        userName=contact_doc['userName'],
        phoneNumber=contact_doc['phoneNumber'],
        createdAt=contact_doc['createdAt']
    )


@router.get("/all", response_model=List[ContactInfo])
async def get_all_contacts():
    contacts = await db.contacts.find().sort("userName", 1).to_list(100)
    return [ContactInfo(
        id=str(contact['_id']),
        userId=contact['userId'],
        userName=contact['userName'],
        phoneNumber=contact['phoneNumber'],
        createdAt=contact['createdAt']
    ) for contact in contacts]
