"""
Admin API routes for Management UI
Includes authentication, RBAC middleware, and all admin endpoints
"""
import os
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from jose import jwt, JWTError
from passlib.context import CryptContext
from api.admin_db import AdminDatabase
from api.database import db
from api.utils import now_iso

router = APIRouter(prefix="/api/admin", tags=["admin"])

# ============================================================================
# Authentication & Authorization
# ============================================================================

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer token
security = HTTPBearer()

def hash_password(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password"""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode JWT access token"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

async def get_current_admin(credentials: HTTPAuthorizationCredentials = Security(security)) -> Dict[str, Any]:
    """Get current admin from JWT token"""
    token = credentials.credentials
    payload = decode_access_token(token)
    admin_id = payload.get("sub")
    if admin_id is None:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    return payload

# Role hierarchy (Spec 09)
ROLE_HIERARCHY = {
    "OWNER": ["OWNER", "INCIDENT_RESPONDER", "BILLING_ADMIN", "ANALYST", "AUDITOR_VIEWER"],
    "INCIDENT_RESPONDER": ["INCIDENT_RESPONDER"],
    "BILLING_ADMIN": ["BILLING_ADMIN"],
    "ANALYST": ["ANALYST", "AUDITOR_VIEWER"],
    "AUDITOR_VIEWER": ["AUDITOR_VIEWER"],
}

def require_roles(allowed_roles: List[str]):
    """Dependency to check if current admin has required role"""
    async def role_checker(current_admin: Dict[str, Any] = Depends(get_current_admin)):
        admin_role = current_admin.get("role", "")
        
        # Check if admin role has any of the allowed roles
        admin_allowed_roles = ROLE_HIERARCHY.get(admin_role, [])
        has_permission = any(role in admin_allowed_roles for role in allowed_roles)
        
        if not has_permission:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required roles: {', '.join(allowed_roles)}"
            )
        
        return current_admin
    
    return role_checker

# Predefined role checkers
require_owner = require_roles(["OWNER"])
require_incident_responder = require_roles(["OWNER", "INCIDENT_RESPONDER"])
require_billing_admin = require_roles(["OWNER", "BILLING_ADMIN"])
require_analyst = require_roles(["OWNER", "INCIDENT_RESPONDER", "ANALYST"])
require_auditor = require_roles(["OWNER", "AUDITOR_VIEWER"])

# ============================================================================
# Database Initialization
# ============================================================================

admin_db = None

def get_admin_db():
    """Get admin database instance"""
    global admin_db
    if admin_db is None and db is not None:
        admin_db = AdminDatabase(db)
    return admin_db

# ============================================================================
# Pydantic Models
# ============================================================================

class LoginRequest(BaseModel):
    email: str
    password: str

class SignupRequest(BaseModel):
    email: str
    password: str
    display_name: str
    role: str = "AUDITOR_VIEWER"  # Default to lowest privilege

class LoginResponse(BaseModel):
    user: Dict[str, Any]
    token: str

class UserLookupResponse(BaseModel):
    users: List[Dict[str, Any]]

class IncidentCreate(BaseModel):
    title: str
    description: str
    severity: str
    target_user_ids: Optional[str] = None

class SettingUpdate(BaseModel):
    value: str

# ============================================================================
# Auth Endpoints
# ============================================================================

@router.post("/auth/signup", response_model=LoginResponse)
async def signup(request: SignupRequest, req: Request):
    """Admin signup (first user becomes OWNER, others default to AUDITOR_VIEWER)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    # Check if user already exists
    existing = admin_db_instance.get_admin_user_by_email(request.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Check if this is the first admin user (becomes OWNER)
    all_admins = admin_db_instance.get_all_admin_users()
    if len(all_admins) == 0:
        role = "OWNER"  # First user is OWNER
    else:
        # After first user, all signups default to AUDITOR_VIEWER
        # Only OWNER can change roles later (via future admin management feature)
        role = "AUDITOR_VIEWER"
    
    # Create user
    password_hash = hash_password(request.password)
    admin_user = admin_db_instance.create_admin_user(
        email=request.email,
        password_hash=password_hash,
        role=role,
        display_name=request.display_name
    )
    
    # Create token
    token = create_access_token(data={"sub": admin_user["admin_id"], "role": admin_user["role"]})
    
    # Log audit
    admin_db_instance.log_audit(
        admin_user["admin_id"],
        "signup",
        "auth",
        f"Admin signed up: {admin_user['email']} (role: {role})",
        ip_address=req.client.host if req.client else None,
        user_agent=req.headers.get("user-agent")
    )
    
    # Return user without password hash
    user_response = {
        "admin_id": admin_user["admin_id"],
        "email": admin_user["email"],
        "role": admin_user["role"],
        "display_name": admin_user["display_name"],
        "created_at": admin_user["created_at"],
        "updated_at": admin_user["updated_at"],
        "last_login_at": None
    }
    
    return LoginResponse(user=user_response, token=token)

@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest, req: Request):
    """Admin login"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    admin_user = admin_db_instance.get_admin_user_by_email(request.email)
    if not admin_user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    if not verify_password(request.password, admin_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Update last login
    admin_db_instance.update_admin_last_login(admin_user["admin_id"])
    
    # Create token
    token = create_access_token(data={"sub": admin_user["admin_id"], "role": admin_user["role"]})
    
    # Log audit
    admin_db_instance.log_audit(
        admin_user["admin_id"],
        "login",
        "auth",
        f"Admin logged in: {admin_user['email']}",
        ip_address=req.client.host if req.client else None,
        user_agent=req.headers.get("user-agent")
    )
    
    # Return user without password hash
    user_response = {
        "admin_id": admin_user["admin_id"],
        "email": admin_user["email"],
        "role": admin_user["role"],
        "display_name": admin_user["display_name"],
        "created_at": admin_user["created_at"],
        "updated_at": admin_user["updated_at"],
        "last_login_at": now_iso()
    }
    
    return LoginResponse(user=user_response, token=token)

@router.post("/auth/logout")
async def logout(current_admin: Dict[str, Any] = Depends(get_current_admin)):
    """Admin logout"""
    admin_db_instance = get_admin_db()
    if admin_db_instance:
        admin_db_instance.log_audit(
            current_admin["sub"],
            "logout",
            "auth",
            "Admin logged out"
        )
    return {"message": "Logged out successfully"}

@router.get("/auth/me")
async def get_me(current_admin: Dict[str, Any] = Depends(get_current_admin)):
    """Get current admin user"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    admin_user = admin_db_instance.get_admin_user_by_id(current_admin["sub"])
    if not admin_user:
        raise HTTPException(status_code=404, detail="Admin user not found")
    
    return {
        "admin_id": admin_user["admin_id"],
        "email": admin_user["email"],
        "role": admin_user["role"],
        "display_name": admin_user["display_name"],
        "created_at": admin_user["created_at"],
        "updated_at": admin_user["updated_at"],
        "last_login_at": admin_user["last_login_at"]
    }

# ============================================================================
# Dashboard Endpoints
# ============================================================================

@router.get("/dashboard/stats")
async def get_dashboard_stats(current_admin: Dict[str, Any] = Depends(require_auditor)):
    """Get dashboard statistics (all authenticated admins)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    stats = admin_db_instance.get_dashboard_stats()
    return stats

# ============================================================================
# User Endpoints
# ============================================================================

@router.get("/users/lookup")
async def lookup_users(q: str, current_admin: Dict[str, Any] = Depends(require_analyst)):
    """Search users (OWNER, INCIDENT_RESPONDER, ANALYST)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    users = admin_db_instance.search_users(q, limit=50)
    return {"users": users}

@router.get("/users/{user_id}")
async def get_user(user_id: str, current_admin: Dict[str, Any] = Depends(require_analyst)):
    """Get user by ID (OWNER, INCIDENT_RESPONDER, ANALYST)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    user = admin_db_instance.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user

@router.get("/users/{user_id}/sessions")
async def get_user_sessions(user_id: str, limit: int = 50, 
                           current_admin: Dict[str, Any] = Depends(require_analyst)):
    """Get user sessions (OWNER, INCIDENT_RESPONDER, ANALYST)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    sessions = admin_db_instance.get_user_sessions(user_id, limit=limit)
    return {"sessions": sessions}

@router.get("/users/{user_id}/events")
async def get_user_events(user_id: str, limit: int = 100,
                         current_admin: Dict[str, Any] = Depends(require_analyst)):
    """Get user events (OWNER, INCIDENT_RESPONDER, ANALYST)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    events = admin_db_instance.get_user_events(user_id, limit=limit)
    return {"events": events}

# ============================================================================
# Session Endpoints
# ============================================================================

@router.get("/sessions/{session_id}")
async def get_session(session_id: str, current_admin: Dict[str, Any] = Depends(require_analyst)):
    """Get session by ID (OWNER, INCIDENT_RESPONDER, ANALYST)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    session = admin_db_instance.get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return session

@router.get("/sessions/{session_id}/events")
async def get_session_events(session_id: str, current_admin: Dict[str, Any] = Depends(require_analyst)):
    """Get session events (OWNER, INCIDENT_RESPONDER, ANALYST)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    session = admin_db_instance.get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"events": session.get("events", [])}

# ============================================================================
# Incident Endpoints
# ============================================================================

@router.get("/incidents")
async def list_incidents(status: Optional[str] = None,
                        current_admin: Dict[str, Any] = Depends(require_incident_responder)):
    """List incidents (OWNER, INCIDENT_RESPONDER)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    incidents = admin_db_instance.get_incidents(status=status)
    return {"incidents": incidents}

@router.post("/incidents")
async def create_incident(incident: IncidentCreate, req: Request,
                         current_admin: Dict[str, Any] = Depends(require_incident_responder)):
    """Create incident (OWNER, INCIDENT_RESPONDER)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    new_incident = admin_db_instance.create_incident(
        title=incident.title,
        description=incident.description,
        severity=incident.severity,
        created_by=current_admin["sub"],
        target_user_ids=incident.target_user_ids
    )
    
    # Log audit
    admin_db_instance.log_audit(
        current_admin["sub"],
        "create_incident",
        "incident",
        f"Created incident: {incident.title}",
        resource_id=new_incident["incident_id"],
        ip_address=req.client.host if req.client else None
    )
    
    return new_incident

@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str, current_admin: Dict[str, Any] = Depends(require_incident_responder)):
    """Get incident by ID (OWNER, INCIDENT_RESPONDER)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    incidents = admin_db_instance.get_incidents()
    incident = next((i for i in incidents if i["incident_id"] == incident_id), None)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    return incident

# ============================================================================
# Billing Endpoints
# ============================================================================

@router.get("/billing/credit-ledger")
async def get_credit_ledger(user_id: Optional[str] = None, limit: int = 100,
                           current_admin: Dict[str, Any] = Depends(require_billing_admin)):
    """Get credit ledger (OWNER, BILLING_ADMIN)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    ledger = admin_db_instance.get_credit_ledger(user_id=user_id, limit=limit)
    return {"ledger": ledger}

@router.get("/billing/purchases")
async def get_purchases(user_id: Optional[str] = None, limit: int = 100,
                       current_admin: Dict[str, Any] = Depends(require_billing_admin)):
    """Get purchases (OWNER, BILLING_ADMIN)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    purchases = admin_db_instance.get_purchases(user_id=user_id, limit=limit)
    return {"purchases": purchases}

# ============================================================================
# Audit Endpoints
# ============================================================================

@router.get("/audit")
async def get_audit_logs(limit: int = 100, offset: int = 0,
                        current_admin: Dict[str, Any] = Depends(require_auditor)):
    """Get audit logs (OWNER, AUDITOR_VIEWER)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    logs = admin_db_instance.get_audit_logs(limit=limit, offset=offset)
    return {"logs": logs}

# ============================================================================
# Settings Endpoints
# ============================================================================

@router.get("/settings")
async def get_settings(current_admin: Dict[str, Any] = Depends(require_owner)):
    """Get all settings (OWNER only)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    settings = admin_db_instance.get_settings()
    return {"settings": settings}

@router.put("/settings/{key}")
async def update_setting(key: str, setting: SettingUpdate, req: Request,
                        current_admin: Dict[str, Any] = Depends(require_owner)):
    """Update setting (OWNER only)"""
    admin_db_instance = get_admin_db()
    if not admin_db_instance:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    admin_db_instance.update_setting(key, setting.value)
    
    # Log audit
    admin_db_instance.log_audit(
        current_admin["sub"],
        "update_setting",
        "settings",
        f"Updated setting: {key}",
        resource_id=key,
        ip_address=req.client.host if req.client else None
    )
    
    return {"message": "Setting updated successfully"}
