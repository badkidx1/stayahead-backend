from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


# ============== AUTH MODELS ==============
class UserCreate(BaseModel):
    username: str
    inviteCode: str
    pin: str

class UserLogin(BaseModel):
    username: str
    pin: str

class SetPinRequest(BaseModel):
    userId: str
    newPin: str

class ResetPinRequest(BaseModel):
    userId: str
    adminId: str

class User(BaseModel):
    id: str
    username: str
    role: str
    status: Optional[str] = "approved"
    pushToken: Optional[str] = None
    publicKey: Optional[str] = None
    createdAt: datetime


# ============== INVITE MODELS ==============
class InviteCodeCreate(BaseModel):
    createdBy: str

class InviteCode(BaseModel):
    id: str
    code: str
    isUsed: bool
    createdBy: str
    usedBy: Optional[str] = None
    createdAt: datetime


# ============== SHIFT MODELS ==============
class ShiftCreate(BaseModel):
    date: str
    assignedUserIds: List[str]
    externalNames: Optional[List[str]] = []  # Names of non-app members
    notes: Optional[str] = ""
    createdBy: str

class Shift(BaseModel):
    id: str
    date: str
    assignedUserIds: List[str]
    externalNames: Optional[List[str]] = []  # Names of non-app members
    notes: Optional[str] = ""
    createdBy: str
    createdAt: datetime


# ============== EVENT MODELS ==============
class EventCreate(BaseModel):
    title: str
    description: str
    date: str
    createdBy: str

class Event(BaseModel):
    id: str
    title: str
    description: str
    date: str
    createdBy: str
    createdAt: datetime


# ============== MESSAGE MODELS ==============
class Message(BaseModel):
    id: str
    encryptedContent: str
    senderId: str
    senderName: str
    timestamp: datetime
    iv: str

class MessageCreate(BaseModel):
    encryptedContent: str
    senderId: str
    senderName: str
    iv: str


# ============== CONTACT MODELS ==============
class ContactInfo(BaseModel):
    id: str
    userId: str
    userName: str
    phoneNumber: str
    createdAt: datetime

class ContactInfoCreate(BaseModel):
    userId: str
    userName: str
    phoneNumber: str


# ============== EMERGENCY MODELS ==============
class EmergencyAlert(BaseModel):
    id: str
    userId: str
    userName: str
    latitude: float
    longitude: float
    timestamp: datetime
    acknowledgments: Optional[List[dict]] = []  # List of {userId, userName, timestamp}

class EmergencyAlertCreate(BaseModel):
    userId: str
    userName: str
    latitude: float
    longitude: float

class EmergencyAcknowledge(BaseModel):
    alertId: str
    userId: str
    userName: str


# ============== MISC MODELS ==============
class PushTokenUpdate(BaseModel):
    userId: str
    pushToken: str

class NotificationSend(BaseModel):
    userIds: List[str]
    title: str
    body: str
    data: Optional[dict] = {}

class ProfilePictureUpdate(BaseModel):
    userId: str
    imageBase64: str

class UserApproval(BaseModel):
    userId: str
    adminId: str
