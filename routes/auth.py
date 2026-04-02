from fastapi import APIRouter, HTTPException, Request
from bson import ObjectId
from datetime import datetime, timedelta
import bcrypt
import secrets
import logging

from database import db
from models import UserCreate, UserLogin, SetPinRequest, ResetPinRequest
from notifications import notify_admins
from routes.audit import log_event
from auth_jwt import create_token, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# Lockout settings
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 30


@router.post("/register")
async def register(user_data: UserCreate, request: Request):
    existing_user = await db.users.find_one({"username": user_data.username})
    if existing_user:
        await log_event("register_failed", "auth", username=user_data.username,
                        details="Username already exists", ip=request.client.host, success=False)
        raise HTTPException(status_code=400, detail="Username already exists")

    invite = await db.inviteCodes.find_one({"code": user_data.inviteCode, "isUsed": False})
    if not invite:
        await log_event("register_failed", "auth", username=user_data.username,
                        details="Invalid invite code", ip=request.client.host, success=False)
        raise HTTPException(status_code=400, detail="Invalid or already used invite code")

    # Check invite code expiration (24 hours)
    if invite.get('expiresAt') and datetime.utcnow() > invite['expiresAt']:
        await log_event("register_failed", "auth", username=user_data.username,
                        details="Expired invite code", ip=request.client.host, success=False)
        raise HTTPException(status_code=400, detail="Invite code has expired")

    if not user_data.pin.isdigit() or len(user_data.pin) != 6:
        raise HTTPException(status_code=400, detail="PIN must be exactly 6 digits")

    pin_hash = bcrypt.hashpw(user_data.pin.encode('utf-8'), bcrypt.gensalt())

    user_doc = {
        "username": user_data.username,
        "pinHash": pin_hash.decode('utf-8'),
        "role": "member",
        "status": "pending",
        "pushToken": None,
        "publicKey": None,
        "failedAttempts": 0,
        "lockoutUntil": None,
        "createdAt": datetime.utcnow()
    }
    result = await db.users.insert_one(user_doc)
    user_doc['_id'] = str(result.inserted_id)

    await db.inviteCodes.update_one(
        {"_id": invite["_id"]},
        {"$set": {"isUsed": True, "usedBy": user_doc['_id']}}
    )

    await notify_admins(
        "\U0001f464 New Member Request",
        f"{user_data.username} has registered and is awaiting approval.",
        {"type": "pending_member", "userId": user_doc['_id']}
    )

    await log_event("register", "auth", userId=user_doc['_id'], username=user_data.username,
                    details="New member registered (pending approval)", ip=request.client.host)

    return {
        "id": user_doc['_id'],
        "username": user_doc['username'],
        "role": user_doc['role'],
        "status": user_doc['status'],
        "message": "Registration submitted. Waiting for admin approval."
    }


@router.post("/login")
async def login(user_data: UserLogin, request: Request):
    user = await db.users.find_one({"username": user_data.username})
    if not user:
        await log_event("login_failed", "auth", username=user_data.username,
                        details="User not found", ip=request.client.host, success=False)
        raise HTTPException(status_code=404, detail="User not found")

    # Check lockout
    lockout_until = user.get('lockoutUntil')
    if lockout_until and datetime.utcnow() < lockout_until:
        remaining = int((lockout_until - datetime.utcnow()).total_seconds() / 60) + 1
        await log_event("login_blocked", "auth", userId=str(user['_id']), username=user_data.username,
                        details=f"Account locked ({remaining} min remaining)", ip=request.client.host, success=False)
        raise HTTPException(status_code=429, detail=f"Account locked. Try again in {remaining} minutes.")

    # Check approval status
    status = user.get('status', 'approved')
    if status == 'pending':
        await log_event("login_blocked", "auth", userId=str(user['_id']), username=user_data.username,
                        details="Account pending approval", ip=request.client.host, success=False)
        raise HTTPException(status_code=403, detail="Your account is pending admin approval. Please wait.")
    if status == 'rejected':
        await log_event("login_blocked", "auth", userId=str(user['_id']), username=user_data.username,
                        details="Account rejected", ip=request.client.host, success=False)
        raise HTTPException(status_code=403, detail="Your account has been rejected. Contact an admin.")

    if not user.get('pinHash'):
        raise HTTPException(status_code=400, detail="User has no PIN set")

    # Verify PIN
    if not bcrypt.checkpw(user_data.pin.encode('utf-8'), user['pinHash'].encode('utf-8')):
        # Increment failed attempts
        failed = user.get('failedAttempts', 0) + 1
        update = {"$set": {"failedAttempts": failed}}

        if failed >= MAX_FAILED_ATTEMPTS:
            lockout_time = datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            update["$set"]["lockoutUntil"] = lockout_time
            detail_msg = f"Incorrect PIN ({failed}/{MAX_FAILED_ATTEMPTS}). Account locked for {LOCKOUT_DURATION_MINUTES} minutes."
            await log_event("login_locked", "auth", userId=str(user['_id']), username=user_data.username,
                            details=f"Account locked after {failed} failed attempts", ip=request.client.host, success=False)
        else:
            remaining = MAX_FAILED_ATTEMPTS - failed
            detail_msg = f"Incorrect PIN. {remaining} attempts remaining."

        await db.users.update_one({"_id": user["_id"]}, update)
        await log_event("login_failed", "auth", userId=str(user['_id']), username=user_data.username,
                        details=f"Incorrect PIN (attempt {failed})", ip=request.client.host, success=False)
        raise HTTPException(status_code=401, detail=detail_msg)

    # Successful login - reset failed attempts and generate JWT
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"failedAttempts": 0, "lockoutUntil": None}}
    )

    token = create_token(str(user['_id']), user['username'], user['role'])

    await log_event("login", "auth", userId=str(user['_id']), username=user['username'],
                    details="Successful login", ip=request.client.host)

    return {
        "id": str(user['_id']),
        "username": user['username'],
        "role": user['role'],
        "status": user.get('status', 'approved'),
        "token": token,
        "pushToken": user.get('pushToken'),
        "publicKey": user.get('publicKey'),
        "createdAt": user['createdAt'].isoformat() if isinstance(user['createdAt'], datetime) else user['createdAt'],
    }


@router.post("/change-pin")
async def change_pin(data: SetPinRequest, request: Request):
    if not data.newPin.isdigit() or len(data.newPin) != 6:
        raise HTTPException(status_code=400, detail="PIN must be exactly 6 digits")

    pin_hash = bcrypt.hashpw(data.newPin.encode('utf-8'), bcrypt.gensalt())

    result = await db.users.update_one(
        {"_id": ObjectId(data.userId)},
        {"$set": {"pinHash": pin_hash.decode('utf-8')}}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    await log_event("change_pin", "auth", userId=data.userId,
                    details="PIN changed", ip=request.client.host)

    return {"success": True, "message": "PIN changed successfully"}


@router.post("/reset-pin")
async def reset_pin(data: ResetPinRequest, request: Request):
    admin = await db.users.find_one({"_id": ObjectId(data.adminId)})
    if not admin or admin['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Only admins can reset PINs")

    user = await db.users.find_one({"_id": ObjectId(data.userId)}, {"username": 1})

    temp_pin = str(secrets.randbelow(1000000)).zfill(6)
    pin_hash = bcrypt.hashpw(temp_pin.encode('utf-8'), bcrypt.gensalt())

    # Reset PIN and clear any lockout
    result = await db.users.update_one(
        {"_id": ObjectId(data.userId)},
        {"$set": {"pinHash": pin_hash.decode('utf-8'), "failedAttempts": 0, "lockoutUntil": None}}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    target_name = user['username'] if user else data.userId
    await log_event("reset_pin", "admin", userId=data.adminId, username=admin['username'],
                    details=f"Reset PIN for {target_name}", ip=request.client.host)

    return {"success": True, "tempPin": temp_pin, "message": "PIN reset. Give this temporary PIN to the user."}
