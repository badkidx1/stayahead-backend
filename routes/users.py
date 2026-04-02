from fastapi import APIRouter, HTTPException
from bson import ObjectId
from datetime import datetime
import base64
import logging

from database import db
from models import PushTokenUpdate, ProfilePictureUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/all")
async def get_all_users():
    users = await db.users.find(
        {"status": {"$ne": "pending"}},
        {"_id": 1, "username": 1, "role": 1, "status": 1, "pushToken": 1, "publicKey": 1, "createdAt": 1, "profilePicture": 1}
    ).to_list(100)
    result = []
    for user in users:
        user_data = {
            "id": str(user['_id']),
            "username": user['username'],
            "role": user['role'],
            "status": user.get('status', 'approved'),
            "pushToken": user.get('pushToken'),
            "publicKey": user.get('publicKey'),
            "createdAt": user['createdAt'].isoformat() if isinstance(user['createdAt'], datetime) else user['createdAt'],
            "hasProfilePicture": bool(user.get('profilePicture')),
        }
        result.append(user_data)
    return result


@router.post("/push-token")
async def update_push_token(data: PushTokenUpdate):
    result = await db.users.update_one(
        {"_id": ObjectId(data.userId)},
        {"$set": {"pushToken": data.pushToken}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True}


@router.post("/make-admin")
async def make_admin(userId: str, requesterId: str):
    requester = await db.users.find_one({"_id": ObjectId(requesterId)})
    if not requester or requester['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Only admins can promote users")

    result = await db.users.update_one(
        {"_id": ObjectId(userId)},
        {"$set": {"role": "admin"}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"success": True}


@router.post("/profile-picture")
async def upload_profile_picture(data: ProfilePictureUpdate):
    """Upload a profile picture as base64"""
    if data.imageBase64:
        try:
            img_data = base64.b64decode(data.imageBase64)
            if len(img_data) > 2 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="Image too large. Max 2MB.")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid image data")

    result = await db.users.update_one(
        {"_id": ObjectId(data.userId)},
        {"$set": {"profilePicture": data.imageBase64 if data.imageBase64 else None}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    return {"success": True, "message": "Profile picture updated"}


@router.get("/{user_id}/profile-picture")
async def get_profile_picture(user_id: str):
    """Get a user's profile picture"""
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    picture = user.get('profilePicture')
    if not picture:
        return {"hasImage": False, "imageBase64": None}

    return {"hasImage": True, "imageBase64": picture}
