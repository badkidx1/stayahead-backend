from fastapi import APIRouter, HTTPException
from bson import ObjectId
from datetime import datetime
import logging

from database import db
from models import ShiftCreate, Shift
from notifications import notify_shift_assignment, schedule_shift_reminders
from routes.audit import log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/shifts", tags=["shifts"])


def serialize_doc(doc):
    if doc and '_id' in doc:
        doc['_id'] = str(doc['_id'])
    return doc


@router.post("/create", response_model=Shift)
async def create_shift(shift_data: ShiftCreate):
    try:
        user = await db.users.find_one({"_id": ObjectId(shift_data.createdBy)})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid user ID: {str(e)}")
    
    if not user or user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Only admins can create shifts")

    existing_shift = await db.shifts.find_one({"date": shift_data.date})
    if existing_shift:
        await db.shifts.update_one(
            {"_id": existing_shift["_id"]},
            {"$set": {
                "assignedUserIds": shift_data.assignedUserIds,
                "externalNames": shift_data.externalNames or [],
                "notes": shift_data.notes,
                "updatedAt": datetime.utcnow()
            }}
        )
        existing_shift['assignedUserIds'] = shift_data.assignedUserIds
        existing_shift['externalNames'] = shift_data.externalNames or []
        existing_shift['notes'] = shift_data.notes

        # Resolve usernames for log
        assigned_names = []
        for uid in shift_data.assignedUserIds:
            u = await db.users.find_one({"_id": ObjectId(uid)}, {"username": 1})
            assigned_names.append(u['username'] if u else uid)
        # Add external names to log
        assigned_names.extend(shift_data.externalNames or [])

        await log_event("edit_shift", "roster", userId=shift_data.createdBy, username=user['username'],
                        details=f"Updated shift {shift_data.date}: {', '.join(assigned_names)}")

        return Shift(
            id=str(existing_shift['_id']),
            date=existing_shift['date'],
            assignedUserIds=existing_shift['assignedUserIds'],
            externalNames=existing_shift.get('externalNames', []),
            notes=existing_shift['notes'],
            createdBy=existing_shift['createdBy'],
            createdAt=existing_shift['createdAt']
        )

    shift_doc = {
        "date": shift_data.date,
        "assignedUserIds": shift_data.assignedUserIds,
        "externalNames": shift_data.externalNames or [],
        "notes": shift_data.notes,
        "createdBy": shift_data.createdBy,
        "createdAt": datetime.utcnow()
    }
    result = await db.shifts.insert_one(shift_doc)
    shift_doc['_id'] = str(result.inserted_id)

    if shift_data.assignedUserIds:
        shift_types = ["Day Shift (7am-7pm)", "Night Shift (7pm-7am)"]
        for i, user_id in enumerate(shift_data.assignedUserIds):
            shift_type = shift_types[i] if i < len(shift_types) else "Shift"
            await notify_shift_assignment([user_id], shift_data.date, shift_type)
        await schedule_shift_reminders(shift_data.date, shift_data.assignedUserIds)

    # Log new shift creation
    assigned_names = []
    for uid in shift_data.assignedUserIds:
        u = await db.users.find_one({"_id": ObjectId(uid)}, {"username": 1})
        assigned_names.append(u['username'] if u else uid)
    # Add external names to log
    assigned_names.extend(shift_data.externalNames or [])
    await log_event("create_shift", "roster", userId=shift_data.createdBy, username=user['username'],
                    details=f"Created shift {shift_data.date}: {', '.join(assigned_names)}")

    return Shift(
        id=shift_doc['_id'],
        date=shift_doc['date'],
        assignedUserIds=shift_doc['assignedUserIds'],
        externalNames=shift_doc.get('externalNames', []),
        notes=shift_doc['notes'],
        createdBy=shift_doc['createdBy'],
        createdAt=shift_doc['createdAt']
    )


@router.get("/all")
async def get_all_shifts():
    shifts = await db.shifts.find().sort("date", -1).limit(200).to_list(200)
    return [Shift(
        id=str(shift['_id']),
        date=shift['date'],
        assignedUserIds=shift['assignedUserIds'],
        externalNames=shift.get('externalNames', []),
        notes=shift.get('notes', ''),
        createdBy=shift['createdBy'],
        createdAt=shift['createdAt']
    ) for shift in shifts]


@router.get("/month")
async def get_shifts_by_month(year: int, month: int):
    start_date = f"{year}-{month:02d}-01"
    if month == 12:
        end_date = f"{year+1}-01-01"
    else:
        end_date = f"{year}-{month+1:02d}-01"

    shifts = await db.shifts.find({
        "date": {"$gte": start_date, "$lt": end_date}
    }).to_list(100)

    return [serialize_doc(shift) for shift in shifts]


@router.delete("/{shift_id}")
async def delete_shift(shift_id: str, userId: str):
    user = await db.users.find_one({"_id": ObjectId(userId)})
    if not user or user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Only admins can delete shifts")

    shift = await db.shifts.find_one({"_id": ObjectId(shift_id)})
    result = await db.shifts.delete_one({"_id": ObjectId(shift_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Shift not found")

    await log_event("delete_shift", "roster", userId=userId, username=user['username'],
                    details=f"Deleted shift {shift['date'] if shift else shift_id}")
    return {"success": True}
