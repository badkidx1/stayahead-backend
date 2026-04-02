import logging
import asyncio
from datetime import datetime, timedelta
from typing import List
from bson import ObjectId
import httpx

from database import db

logger = logging.getLogger(__name__)

# Store scheduled tasks in memory
scheduled_tasks = {}


async def send_push_notification(push_tokens: List[str], title: str, body: str, data: dict = None):
    """Send push notifications via Expo's push notification service"""
    if not push_tokens:
        return

    messages = []
    for token in push_tokens:
        if not token or not token.startswith('ExponentPushToken'):
            continue
        messages.append({
            'to': token,
            'sound': 'default',
            'title': title,
            'body': body,
            'data': data or {},
        })

    if not messages:
        return

    async with httpx.AsyncClient() as http_client:
        try:
            response = await http_client.post(
                'https://exp.host/--/api/v2/push/send',
                json=messages,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            logger.info(f"Sent {len(messages)} push notifications")
            return response.json()
        except Exception as e:
            logger.error(f"Failed to send push notifications: {e}")
            return None


async def notify_shift_assignment(user_ids: List[str], date: str, shift_type: str):
    """Notify users they've been assigned to a shift"""
    users = await db.users.find({'_id': {'$in': [ObjectId(uid) for uid in user_ids]}}).to_list(100)
    push_tokens = [u['pushToken'] for u in users if u.get('pushToken')]

    await send_push_notification(
        push_tokens,
        '\U0001f3cd\ufe0f Guard Duty Assigned',
        f'You have {shift_type} guard duty on {date}',
        {'type': 'shift_assigned', 'date': date}
    )


async def notify_all_members(title: str, body: str, data: dict = None):
    """Send notification to all approved members"""
    users = await db.users.find({"status": {"$ne": "pending"}}, {"pushToken": 1}).to_list(1000)
    push_tokens = [u['pushToken'] for u in users if u.get('pushToken')]
    await send_push_notification(push_tokens, title, body, data)


async def notify_emergency_alert(alert_data: dict):
    """Broadcast emergency alert to all members"""
    await notify_all_members(
        '\U0001f6a8 EMERGENCY ALERT',
        f"{alert_data['userName']} needs help! Location shared.",
        {'type': 'emergency', 'latitude': alert_data['latitude'], 'longitude': alert_data['longitude']}
    )


async def notify_admins(title: str, body: str, data: dict = None):
    """Send notification to all admins"""
    admins = await db.users.find({"role": "admin"}, {"pushToken": 1}).to_list(100)
    push_tokens = [u['pushToken'] for u in admins if u.get('pushToken')]
    await send_push_notification(push_tokens, title, body, data)


async def schedule_shift_reminders(shift_date: str, user_ids: List[str]):
    """Schedule reminder notifications for a shift"""
    try:
        shift_dt = datetime.strptime(shift_date, "%Y-%m-%d")
        day_start = shift_dt.replace(hour=7, minute=0, second=0)
        night_start = shift_dt.replace(hour=19, minute=0, second=0)
        now = datetime.utcnow()

        for i, user_id in enumerate(user_ids):
            if i == 0:
                shift_start = day_start
                shift_label = "Day Shift (7am-7pm)"
            elif i == 1:
                shift_start = night_start
                shift_label = "Night Shift (7pm-7am)"
            else:
                continue

            reminder_3h = shift_start - timedelta(hours=3)

            if reminder_3h > now:
                delay_3h = (reminder_3h - now).total_seconds()
                task_key = f"{shift_date}_{user_id}_3h"
                if task_key in scheduled_tasks:
                    scheduled_tasks[task_key].cancel()
                scheduled_tasks[task_key] = asyncio.get_event_loop().call_later(
                    delay_3h,
                    lambda uid=user_id, sl=shift_label, sd=shift_date: asyncio.ensure_future(
                        send_shift_reminder(uid, sl, sd, "3 hours")
                    )
                )
                logger.info(f"Scheduled 3h reminder for {user_id} on {shift_date} in {delay_3h:.0f}s")

            if shift_start > now:
                delay_start = (shift_start - now).total_seconds()
                task_key = f"{shift_date}_{user_id}_start"
                if task_key in scheduled_tasks:
                    scheduled_tasks[task_key].cancel()
                scheduled_tasks[task_key] = asyncio.get_event_loop().call_later(
                    delay_start,
                    lambda uid=user_id, sl=shift_label, sd=shift_date: asyncio.ensure_future(
                        send_shift_reminder(uid, sl, sd, "now")
                    )
                )
                logger.info(f"Scheduled start reminder for {user_id} on {shift_date} in {delay_start:.0f}s")
    except Exception as e:
        logger.error(f"Error scheduling shift reminders: {e}")


async def send_shift_reminder(user_id: str, shift_label: str, shift_date: str, timing: str):
    """Send a shift reminder notification to a specific user"""
    try:
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user or not user.get('pushToken'):
            return

        if timing == "now":
            title = "\U0001f3cd\ufe0f Your Shift Starts NOW"
            body = f"Your {shift_label} on {shift_date} is starting. Stay sharp!"
        else:
            title = "\U0001f3cd\ufe0f Shift Reminder"
            body = f"Your {shift_label} on {shift_date} starts in {timing}. Get ready!"

        await send_push_notification(
            [user['pushToken']],
            title,
            body,
            {'type': 'shift_reminder', 'date': shift_date}
        )
        logger.info(f"Sent {timing} reminder to {user.get('username', user_id)} for {shift_date}")
    except Exception as e:
        logger.error(f"Error sending shift reminder: {e}")


async def reschedule_all_shift_reminders():
    """On startup, schedule reminders for all future shifts"""
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        max_date = (datetime.utcnow() + timedelta(days=90)).strftime("%Y-%m-%d")
        future_shifts = await db.shifts.find(
            {"date": {"$gte": today, "$lte": max_date}},
            {"_id": 1, "date": 1, "assignedUserIds": 1}
        ).limit(200).to_list(200)
        for shift in future_shifts:
            if shift.get('assignedUserIds'):
                await schedule_shift_reminders(shift['date'], shift['assignedUserIds'])
        logger.info(f"Rescheduled reminders for {len(future_shifts)} upcoming shifts")
    except Exception as e:
        logger.error(f"Error rescheduling shift reminders: {e}")
