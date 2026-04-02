from fastapi import APIRouter
from datetime import datetime
import logging
from bson import ObjectId

from database import db
from models import EmergencyAlert, EmergencyAlertCreate, EmergencyAcknowledge
from notifications import notify_emergency_alert

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/emergency", tags=["emergency"])


def serialize_doc(doc):
    if doc and '_id' in doc:
        doc['_id'] = str(doc['_id'])
    return doc


@router.post("/alert", response_model=EmergencyAlert)
async def create_emergency_alert(alert_data: EmergencyAlertCreate):
    alert_doc = {
        "userId": alert_data.userId,
        "userName": alert_data.userName,
        "latitude": alert_data.latitude,
        "longitude": alert_data.longitude,
        "timestamp": datetime.utcnow(),
        "acknowledgments": []  # Track who has seen/acknowledged the alert
    }
    result = await db.emergencyAlerts.insert_one(alert_doc)
    alert_doc['_id'] = str(result.inserted_id)

    await notify_emergency_alert(alert_doc)

    return EmergencyAlert(
        id=alert_doc['_id'],
        userId=alert_doc['userId'],
        userName=alert_doc['userName'],
        latitude=alert_doc['latitude'],
        longitude=alert_doc['longitude'],
        timestamp=alert_doc['timestamp'],
        acknowledgments=[]
    )


@router.post("/acknowledge")
async def acknowledge_alert(ack_data: EmergencyAcknowledge):
    """Member acknowledges they've seen the emergency alert"""
    alert = await db.emergencyAlerts.find_one({"_id": ObjectId(ack_data.alertId)})
    
    if not alert:
        return {"success": False, "message": "Alert not found"}
    
    # Check if user already acknowledged
    existing_acks = alert.get('acknowledgments', [])
    already_acked = any(a['userId'] == ack_data.userId for a in existing_acks)
    
    if already_acked:
        return {"success": True, "message": "Already acknowledged"}
    
    # Add acknowledgment
    ack_entry = {
        "userId": ack_data.userId,
        "userName": ack_data.userName,
        "timestamp": datetime.utcnow()
    }
    
    await db.emergencyAlerts.update_one(
        {"_id": ObjectId(ack_data.alertId)},
        {"$push": {"acknowledgments": ack_entry}}
    )
    
    logger.info(f"{ack_data.userName} acknowledged emergency alert {ack_data.alertId}")
    
    return {"success": True, "message": "Acknowledged"}


@router.get("/alert/{alert_id}/acknowledgments")
async def get_alert_acknowledgments(alert_id: str):
    """Get list of who has acknowledged an alert"""
    alert = await db.emergencyAlerts.find_one({"_id": ObjectId(alert_id)})
    
    if not alert:
        return {"acknowledgments": [], "total_users": 0}
    
    # Get total approved users count
    total_users = await db.users.count_documents({"status": "approved"})
    
    # Get all approved users for comparison
    all_users = await db.users.find({"status": "approved"}, {"_id": 1, "username": 1}).to_list(100)
    
    acks = alert.get('acknowledgments', [])
    acked_user_ids = [a['userId'] for a in acks]
    
    # Find who hasn't acknowledged
    not_acknowledged = [
        {"userId": str(u['_id']), "userName": u['username']}
        for u in all_users 
        if str(u['_id']) not in acked_user_ids and str(u['_id']) != alert.get('userId')  # Exclude sender
    ]
    
    return {
        "acknowledgments": acks,
        "acknowledged_count": len(acks),
        "not_acknowledged": not_acknowledged,
        "not_acknowledged_count": len(not_acknowledged),
        "total_users": total_users - 1  # Exclude sender
    }


@router.get("/recent")
async def get_recent_alerts():
    alerts = await db.emergencyAlerts.find().sort("timestamp", -1).limit(10).to_list(10)
    return [serialize_doc(alert) for alert in alerts]
