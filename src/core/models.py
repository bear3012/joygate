# src/joygate/core/models.py
from enum import Enum

class PresenceStatus(str, Enum):
    IN_FENCE = "IN_FENCE"
    OUT_FENCE = "OUT_FENCE"
    UNKNOWN = "UNKNOWN"

class RevokeState(str, Enum):
    NONE = "NONE"
    REVOKE_OBSERVE = "REVOKE_OBSERVE"
    REVOKED = "REVOKED"

class PlugConfirmationState(str, Enum):
    CONFIRMED = "CONFIRMED"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"

class ChargerState(str, Enum):
    FREE = "FREE"
    OCCUPIED = "OCCUPIED"
    UNKNOWN_OCCUPANCY = "UNKNOWN_OCCUPANCY"

class PlugWindowState(str, Enum):
    RUNNING = "RUNNING"
    SUSPENDED = "SUSPENDED"

class TruthInputSource(str, Enum):
    SIMULATOR = "SIMULATOR"
    OCPP = "OCPP"
    THIRD_PARTY_API = "THIRD_PARTY_API"
    QR_SCAN = "QR_SCAN"
    VISION = "VISION"
