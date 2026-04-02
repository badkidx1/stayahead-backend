from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
import socketio
import logging
import bcrypt
from datetime import datetime

from database import db, client
from notifications import reschedule_all_shift_reminders

from routes.auth import router as auth_router
from routes.users import router as users_router
from routes.admin import router as admin_router
from routes.shifts import router as shifts_router
from routes.events import router as events_router
from routes.messages import router as messages_router
from routes.contacts import router as contacts_router
from routes.emergency import router as emergency_router
from routes.audit import router as audit_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Socket.IO server
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    logger=True,
    engineio_logger=True
)

# Create the main app
app = FastAPI()

# Global exception handler to always return JSON
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Server error. Please try again."}
    )

# Register all route modules
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(admin_router)
app.include_router(shifts_router)
app.include_router(events_router)
app.include_router(messages_router)
app.include_router(contacts_router)
app.include_router(emergency_router)
app.include_router(audit_router)

# Create combined ASGI app with Socket.IO
socket_app = socketio.ASGIApp(sio, app)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== SOCKET.IO EVENTS ==============
@sio.event
async def connect(sid, environ):
    logging.info(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    logging.info(f"Client disconnected: {sid}")

@sio.event
async def join_chat(sid, data):
    await sio.enter_room(sid, 'chat_room')
    logging.info(f"User {data.get('username')} joined chat room")

@sio.event
async def send_message(sid, data):
    await sio.emit('new_message', data, room='chat_room')

@sio.event
async def shift_assigned(sid, data):
    await sio.emit('shift_updated', data, room='chat_room')

@sio.event
async def event_created(sid, data):
    await sio.emit('event_notification', data, room='chat_room')


# ============== LIFECYCLE EVENTS ==============
@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


@app.on_event("startup")
async def create_initial_admin():
    admin_count = await db.users.count_documents({})
    if admin_count == 0:
        pin_hash = bcrypt.hashpw('123456'.encode('utf-8'), bcrypt.gensalt())

        admin_doc = {
            "username": "admin",
            "pinHash": pin_hash.decode('utf-8'),
            "role": "admin",
            "status": "approved",
            "pushToken": None,
            "publicKey": None,
            "createdAt": datetime.utcnow()
        }
        result = await db.users.insert_one(admin_doc)
        logger.info(f"Created initial admin user with ID: {result.inserted_id}")

        invite_doc = {
            "code": "WELCOME123",
            "isUsed": False,
            "createdBy": str(result.inserted_id),
            "usedBy": None,
            "createdAt": datetime.utcnow()
        }
        await db.inviteCodes.insert_one(invite_doc)
        logger.info("Created initial invite code: WELCOME123")
    else:
        # Ensure existing users have status field
        await db.users.update_many(
            {"status": {"$exists": False}},
            {"$set": {"status": "approved"}}
        )

        # Set default PIN for users without one
        users_without_pin = await db.users.find({"pinHash": {"$exists": False}}, {"_id": 1, "username": 1}).to_list(100)
        for u in users_without_pin:
            pin_hash = bcrypt.hashpw('123456'.encode('utf-8'), bcrypt.gensalt())
            await db.users.update_one(
                {"_id": u["_id"]},
                {"$set": {"pinHash": pin_hash.decode('utf-8')}}
            )
            logger.info(f"Set default PIN (123456) for user: {u['username']}")

    # Schedule reminders for upcoming shifts
    await reschedule_all_shift_reminders()
