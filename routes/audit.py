from fastapi import APIRouter
from datetime import datetime
from typing import Optional
import logging

from database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/audit", tags=["audit"])


async def log_event(
    action: str,
    category: str,
    userId: Optional[str] = None,
    username: Optional[str] = None,
    details: Optional[str] = None,
    ip: Optional[str] = None,
    success: bool = True,
):
    """Write an audit log entry to the database"""
    try:
        doc = {
            "action": action,
            "category": category,
            "userId": userId,
            "username": username,
            "details": details,
            "ip": ip,
            "success": success,
            "timestamp": datetime.utcnow(),
        }
        await db.audit_logs.insert_one(doc)
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")


@router.get("/logs")
async def get_audit_logs(adminId: str, category: Optional[str] = None, limit: int = 100):
    """Get audit logs (admin only)"""
    from bson import ObjectId

    admin = await db.users.find_one({"_id": ObjectId(adminId)}, {"role": 1})
    if not admin or admin.get("role") != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Only admins can view logs")

    query = {}
    if category:
        query["category"] = category

    logs = await db.audit_logs.find(query).sort("timestamp", -1).limit(limit).to_list(limit)

    return [{
        "id": str(log["_id"]),
        "action": log["action"],
        "category": log["category"],
        "userId": log.get("userId"),
        "username": log.get("username"),
        "details": log.get("details"),
        "success": log.get("success", True),
        "timestamp": log["timestamp"].isoformat() if isinstance(log["timestamp"], datetime) else log["timestamp"],
    } for log in logs]
