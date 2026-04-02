from fastapi import APIRouter, HTTPException
from bson import ObjectId
from datetime import datetime, timedelta
import secrets
import logging

from database import db
from models import InviteCodeCreate, InviteCode, UserApproval
from notifications import send_push_notification
from routes.audit import log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])

INVITE_EXPIRY_HOURS = 24


def serialize_doc(doc):
    if doc and '_id' in doc:
        doc['_id'] = str(doc['_id'])
    return doc


# ============== PENDING MEMBER MANAGEMENT ==============
@router.get("/pending-users")
async def get_pending_users(adminId: str):
    """Get all users awaiting approval"""
    admin = await db.users.find_one({"_id": ObjectId(adminId)})
    if not admin or admin['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Only admins can view pending users")

    pending = await db.users.find({"status": "pending"}).to_list(100)
    return [{
        "id": str(u['_id']),
        "username": u['username'],
        "createdAt": u['createdAt'].isoformat() if isinstance(u['createdAt'], datetime) else u['createdAt'],
    } for u in pending]


@router.post("/approve-user")
async def approve_user(data: UserApproval):
    """Approve a pending user"""
    admin = await db.users.find_one({"_id": ObjectId(data.adminId)})
    if not admin or admin['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Only admins can approve users")

    user = await db.users.find_one({"_id": ObjectId(data.userId)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.get('status') != 'pending':
        raise HTTPException(status_code=400, detail="User is not in pending status")

    await db.users.update_one(
        {"_id": ObjectId(data.userId)},
        {"$set": {"status": "approved"}}
    )

    if user.get('pushToken'):
        await send_push_notification(
            [user['pushToken']],
            '\u2705 Membership Approved',
            'Your account has been approved! You can now log in.',
            {'type': 'approval'}
        )

    logger.info(f"Admin {admin['username']} approved user {user['username']}")
    await log_event("approve_user", "admin", userId=data.adminId, username=admin['username'],
                    details=f"Approved {user['username']}")
    return {"success": True, "message": f"{user['username']} has been approved"}


@router.post("/reject-user")
async def reject_user(data: UserApproval):
    """Reject a pending user"""
    admin = await db.users.find_one({"_id": ObjectId(data.adminId)})
    if not admin or admin['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Only admins can reject users")

    user = await db.users.find_one({"_id": ObjectId(data.userId)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.users.update_one(
        {"_id": ObjectId(data.userId)},
        {"$set": {"status": "rejected"}}
    )

    logger.info(f"Admin {admin['username']} rejected user {user['username']}")
    await log_event("reject_user", "admin", userId=data.adminId, username=admin['username'],
                    details=f"Rejected {user['username']}")
    return {"success": True, "message": f"{user['username']} has been rejected"}


# ============== INVITE CODE MANAGEMENT ==============
@router.post("/invites/generate", response_model=InviteCode)
async def generate_invite(invite_data: InviteCodeCreate):
    user = await db.users.find_one({"_id": ObjectId(invite_data.createdBy)})
    if not user or user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Only admins can generate invite codes")

    code = secrets.token_urlsafe(8)
    now = datetime.utcnow()
    invite_doc = {
        "code": code,
        "isUsed": False,
        "createdBy": invite_data.createdBy,
        "usedBy": None,
        "createdAt": now,
        "expiresAt": now + timedelta(hours=INVITE_EXPIRY_HOURS),
    }
    result = await db.inviteCodes.insert_one(invite_doc)
    invite_doc['_id'] = str(result.inserted_id)

    await log_event("generate_invite", "admin", userId=invite_data.createdBy, username=user['username'],
                    details=f"Generated invite code: {code} (expires in {INVITE_EXPIRY_HOURS}h)")

    return InviteCode(
        id=invite_doc['_id'],
        code=invite_doc['code'],
        isUsed=invite_doc['isUsed'],
        createdBy=invite_doc['createdBy'],
        usedBy=invite_doc['usedBy'],
        createdAt=invite_doc['createdAt']
    )


@router.get("/invites/list")
async def list_invites(userId: str):
    user = await db.users.find_one({"_id": ObjectId(userId)})
    if not user or user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Only admins can view invite codes")

    invites = await db.inviteCodes.find().sort("createdAt", -1).to_list(100)
    result = []
    for invite in invites:
        doc = serialize_doc(invite)
        # Check expiration
        expires_at = invite.get('expiresAt')
        if expires_at and datetime.utcnow() > expires_at and not invite['isUsed']:
            doc['expired'] = True
        else:
            doc['expired'] = False
        if expires_at:
            doc['expiresAt'] = expires_at.isoformat()
        result.append(doc)
    return result
