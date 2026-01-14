"""
Admin database operations
"""
import json
import uuid
from typing import Dict, Any, List, Optional
from api.database import Database
from api.utils import now_iso

# Import Database methods
from api.database import Database as BaseDatabase

class AdminDatabase:
    """Admin-specific database operations"""
    
    def __init__(self, db: Database):
        self.db = db
    
    def get_admin_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get admin user by email"""
        sheet = self.db.get_sheet("AdminUsers")
        all_values = sheet.get_all_values()
        
        if len(all_values) <= 1:
            return None
        
        for i, row in enumerate(all_values[1:], start=2):
            if len(row) > 1 and row[1] == email:  # email is at index 1
                return self._row_to_admin_user(row, i)
        
        return None
    
    def get_admin_user_by_id(self, admin_id: str) -> Optional[Dict[str, Any]]:
        """Get admin user by ID"""
        sheet = self.db.get_sheet("AdminUsers")
        all_values = sheet.get_all_values()
        
        if len(all_values) <= 1:
            return None
        
        for i, row in enumerate(all_values[1:], start=2):
            if len(row) > 0 and row[0] == admin_id:  # admin_id is at index 0
                return self._row_to_admin_user(row, i)
        
        return None
    
    def get_all_admin_users(self) -> List[Dict[str, Any]]:
        """Get all admin users"""
        sheet = self.db.get_sheet("AdminUsers")
        all_values = sheet.get_all_values()
        
        if len(all_values) <= 1:
            return []
        
        admins = []
        for i, row in enumerate(all_values[1:], start=2):
            if len(row) > 0:
                admins.append(self._row_to_admin_user(row, i))
        
        return admins
    
    def create_admin_user(self, email: str, password_hash: str, role: str, display_name: str) -> Dict[str, Any]:
        """Create new admin user"""
        sheet = self.db.get_sheet("AdminUsers")
        
        admin_id = str(uuid.uuid4())
        now = now_iso()
        
        admin_user = {
            "admin_id": admin_id,
            "email": email,
            "password_hash": password_hash,
            "role": role,
            "display_name": display_name,
            "created_at": now,
            "updated_at": now,
            "last_login_at": None
        }
        
        row = [
            admin_id, email, password_hash, role, display_name,
            now, now, ""
        ]
        sheet.append_row(row)
        
        admin_user["_row_index"] = len(sheet.get_all_values())
        return admin_user
    
    def update_admin_last_login(self, admin_id: str):
        """Update admin user's last login time"""
        sheet = self.db.get_sheet("AdminUsers")
        all_values = sheet.get_all_values()
        
        for i, row in enumerate(all_values[1:], start=2):
            if len(row) > 0 and row[0] == admin_id:
                # gspread update() requires list of lists format
                sheet.update(f"H{i}", [[now_iso()]])  # last_login_at is at column H
                break
    
    def _row_to_admin_user(self, row: List[str], row_index: int) -> Dict[str, Any]:
        """Convert sheet row to admin user dict"""
        return {
            "_row_index": row_index,
            "admin_id": row[0] if len(row) > 0 else "",
            "email": row[1] if len(row) > 1 else "",
            "password_hash": row[2] if len(row) > 2 else "",
            "role": row[3] if len(row) > 3 else "",
            "display_name": row[4] if len(row) > 4 else "",
            "created_at": row[5] if len(row) > 5 else "",
            "updated_at": row[6] if len(row) > 6 else "",
            "last_login_at": row[7] if len(row) > 7 else None
        }
    
    def get_all_users(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Get all users (for admin)"""
        sheet = self.db.get_sheet("Users")
        all_values = sheet.get_all_values()
        
        if len(all_values) <= 1:
            return []
        
        users = []
        for i, row in enumerate(all_values[1 + offset:1 + offset + limit], start=2 + offset):
            if len(row) > 0:
                users.append(self.db._row_to_user(row, i))
        
        return users
    
    def search_users(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Search users by user_id or other fields"""
        sheet = self.db.get_sheet("Users")
        all_values = sheet.get_all_values()
        
        if len(all_values) <= 1:
            return []
        
        query_lower = query.lower()
        results = []
        
        for i, row in enumerate(all_values[1:], start=2):
            if len(row) > 0:
                user_id = row[0] if len(row) > 0 else ""
                if query_lower in user_id.lower():
                    results.append(self.db._row_to_user(row, i))
                    if len(results) >= limit:
                        break
        
        return results
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        return self.db.get_or_create_user(user_id)
    
    def get_user_events(self, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get events for a user"""
        sheet = self.db.get_sheet("Events")
        all_values = sheet.get_all_values()
        
        if len(all_values) <= 1:
            return []
        
        events = []
        for row in reversed(all_values[1:]):
            if len(row) > 2 and row[2] == user_id:
                events.append({
                    "event_id": row[0] if len(row) > 0 else "",
                    "timestamp": row[1] if len(row) > 1 else "",
                    "user_id": row[2] if len(row) > 2 else "",
                    "channel": row[3] if len(row) > 3 else "",
                    "type": row[4] if len(row) > 4 else "",
                    "event_subtype": row[4] if len(row) > 4 else "",
                    "mode": row[5] if len(row) > 5 else "",
                    "is_observed_log": row[6] == "true" if len(row) > 6 else False,
                    "content": row[7] if len(row) > 7 else "",
                    "token_count": int(row[8]) if len(row) > 8 and row[8] else 0,
                    "meta_json": row[9] if len(row) > 9 else "{}"
                })
                if len(events) >= limit:
                    break
        
        return list(reversed(events))
    
    def get_user_sessions(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get sessions for a user (grouped by mode changes)"""
        events = self.get_user_events(user_id, limit=1000)
        
        # Group events into sessions based on mode changes
        sessions = []
        current_session = None
        
        for event in events:
            if current_session is None or event.get("mode") != current_session.get("mode"):
                # Start new session
                if current_session:
                    sessions.append(current_session)
                
                session_id = str(uuid.uuid4())
                current_session = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "started_at": event.get("timestamp", ""),
                    "ended_at": None,
                    "events": [event]
                }
            else:
                current_session["events"].append(event)
                current_session["ended_at"] = event.get("timestamp", "")
        
        if current_session:
            sessions.append(current_session)
        
        return sessions[:limit]
    
    def get_session_by_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID (need to search through all users)"""
        # This is inefficient but works for now
        # In production, you'd want a Sessions sheet
        sheet = self.db.get_sheet("Users")
        all_users = sheet.get_all_values()
        
        for row in all_users[1:]:
            if len(row) > 0:
                user_id = row[0]
                sessions = self.get_user_sessions(user_id, limit=1000)
                for session in sessions:
                    if session["session_id"] == session_id:
                        return session
        
        return None
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get dashboard statistics"""
        users_sheet = self.db.get_sheet("Users")
        events_sheet = self.db.get_sheet("Events")
        purchases_sheet = self.db.get_sheet("Purchases")
        
        all_users = users_sheet.get_all_values()
        all_events = events_sheet.get_all_values()
        all_purchases = purchases_sheet.get_all_values()
        
        total_users = max(0, len(all_users) - 1)  # Exclude header
        
        # Calculate active users (30 days) - simplified
        active_users_30d = total_users  # TODO: Filter by last activity
        
        # Calculate credits granted/consumed
        total_credits_granted = 0
        total_credits_consumed = 0
        
        for row in all_events[1:]:
            if len(row) > 4:
                event_type = row[4]
                meta_json = row[9] if len(row) > 9 else "{}"
                try:
                    meta = json.loads(meta_json)
                    if "reason" in meta:
                        if meta["reason"] == "monthly_grant" or meta["reason"] == "initial":
                            # Extract credit amount from text or meta
                            text = row[7] if len(row) > 7 else ""
                            if "grant" in text.lower():
                                # Try to extract number
                                import re
                                nums = re.findall(r'\d+', text)
                                if nums:
                                    total_credits_granted += int(nums[-1])
                        elif meta["reason"] == "diagnosis" or meta["reason"] == "training" or meta["reason"] == "ai_reply":
                            token_est = int(row[8]) if len(row) > 8 and row[8] else 0
                            total_credits_consumed += token_est
                except:
                    pass
        
        # Get open incidents
        incidents_sheet = self.db.get_sheet("Incidents")
        all_incidents = incidents_sheet.get_all_values()
        open_incidents = 0
        for row in all_incidents[1:]:
            if len(row) > 3:
                status = row[3]
                if status in ["open", "investigating"]:
                    open_incidents += 1
        
        # Recent events count (last 24 hours) - simplified
        recent_events_count = min(100, len(all_events) - 1)
        
        return {
            "total_users": total_users,
            "active_users_30d": active_users_30d,
            "total_credits_granted": total_credits_granted,
            "total_credits_consumed": total_credits_consumed,
            "open_incidents": open_incidents,
            "recent_events_count": recent_events_count
        }
    
    def get_credit_ledger(self, user_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get credit ledger entries"""
        events_sheet = self.db.get_sheet("Events")
        all_events = events_sheet.get_all_values()
        
        ledger = []
        balance = {}
        
        for row in all_events[1:]:
            if len(row) > 4:
                event_type = row[4]
                row_user_id = row[2] if len(row) > 2 else ""
                
                if user_id and row_user_id != user_id:
                    continue
                
                if event_type == "credit_change":
                    text = row[7] if len(row) > 7 else ""
                    meta_json = row[9] if len(row) > 9 else "{}"
                    
                    try:
                        meta = json.loads(meta_json)
                        amount = meta.get("amount", 0)
                        reason = meta.get("reason", "")
                        
                        if row_user_id not in balance:
                            # Get initial balance from user
                            user = self.get_user_by_id(row_user_id)
                            balance[row_user_id] = user.get("credits", 0) - amount
                        
                        balance_before = balance[row_user_id]
                        balance_after = balance_before + amount
                        balance[row_user_id] = balance_after
                        
                        transaction_type = "grant" if amount > 0 else "consume"
                        
                        ledger.append({
                            "ledger_id": row[0] if len(row) > 0 else str(uuid.uuid4()),
                            "user_id": row_user_id,
                            "transaction_type": transaction_type,
                            "amount": amount,
                            "balance_before": balance_before,
                            "balance_after": balance_after,
                            "reason": reason,
                            "meta_json": meta_json,
                            "created_at": row[1] if len(row) > 1 else ""
                        })
                    except:
                        pass
        
        # Reverse to get chronological order (newest first)
        return list(reversed(ledger[-limit:]))
    
    def get_purchases(self, user_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get purchase history"""
        sheet = self.db.get_sheet("Purchases")
        all_values = sheet.get_all_values()
        
        if len(all_values) <= 1:
            return []
        
        purchases = []
        for row in reversed(all_values[1:]):
            if len(row) > 1:
                row_user_id = row[1] if len(row) > 1 else ""
                if user_id and row_user_id != user_id:
                    continue
                
                purchases.append({
                    "purchase_id": row[0] if len(row) > 0 else "",
                    "user_id": row_user_id,
                    "product_type": row[2] if len(row) > 2 else "",
                    "pack": row[3] if len(row) > 3 else "",
                    "amount_yen_ex_tax": int(row[4]) if len(row) > 4 and row[4] else 0,
                    "tax": int(row[5]) if len(row) > 5 and row[5] else 0,
                    "amount_yen_in_tax": int(row[6]) if len(row) > 6 and row[6] else 0,
                    "credits": int(row[7]) if len(row) > 7 and row[7] else 0,
                    "status": row[8] if len(row) > 8 else "",
                    "created_at": row[9] if len(row) > 9 else "",
                    "updated_at": row[10] if len(row) > 10 else ""
                })
                if len(purchases) >= limit:
                    break
        
        return purchases
    
    def get_incidents(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get incidents"""
        sheet = self.db.get_sheet("Incidents")
        all_values = sheet.get_all_values()
        
        if len(all_values) <= 1:
            return []
        
        incidents = []
        for row in all_values[1:]:
            if len(row) > 3:
                row_status = row[3] if len(row) > 3 else ""
                if status and row_status != status:
                    continue
                
                incidents.append({
                    "incident_id": row[0] if len(row) > 0 else "",
                    "title": row[1] if len(row) > 1 else "",
                    "description": row[2] if len(row) > 2 else "",
                    "status": row_status,
                    "severity": row[4] if len(row) > 4 else "",
                    "created_by": row[5] if len(row) > 5 else "",
                    "assigned_to": row[6] if len(row) > 6 else "",
                    "target_user_ids": row[7] if len(row) > 7 else "",
                    "created_at": row[8] if len(row) > 8 else "",
                    "updated_at": row[9] if len(row) > 9 else "",
                    "resolved_at": row[10] if len(row) > 10 else ""
                })
        
        return incidents
    
    def create_incident(self, title: str, description: str, severity: str, created_by: str, 
                       target_user_ids: Optional[str] = None) -> Dict[str, Any]:
        """Create new incident"""
        sheet = self.db.get_sheet("Incidents")
        
        incident_id = str(uuid.uuid4())
        now = now_iso()
        
        row = [
            incident_id, title, description, "open", severity,
            created_by, "", target_user_ids or "", now, now, ""
        ]
        sheet.append_row(row)
        
        return {
            "incident_id": incident_id,
            "title": title,
            "description": description,
            "status": "open",
            "severity": severity,
            "created_by": created_by,
            "assigned_to": None,
            "target_user_ids": target_user_ids,
            "created_at": now,
            "updated_at": now,
            "resolved_at": None
        }
    
    def get_audit_logs(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Get audit logs"""
        sheet = self.db.get_sheet("AuditLogs")
        all_values = sheet.get_all_values()
        
        if len(all_values) <= 1:
            return []
        
        logs = []
        for row in all_values[1 + offset:1 + offset + limit]:
            if len(row) > 0:
                logs.append({
                    "audit_id": row[0] if len(row) > 0 else "",
                    "admin_id": row[1] if len(row) > 1 else "",
                    "action": row[2] if len(row) > 2 else "",
                    "resource_type": row[3] if len(row) > 3 else "",
                    "resource_id": row[4] if len(row) > 4 else "",
                    "details": row[5] if len(row) > 5 else "",
                    "ip_address": row[6] if len(row) > 6 else "",
                    "user_agent": row[7] if len(row) > 7 else "",
                    "created_at": row[8] if len(row) > 8 else ""
                })
        
        return logs
    
    def log_audit(self, admin_id: str, action: str, resource_type: str, 
                  details: str, resource_id: Optional[str] = None,
                  ip_address: Optional[str] = None, user_agent: Optional[str] = None):
        """Log audit event"""
        sheet = self.db.get_sheet("AuditLogs")
        
        audit_id = str(uuid.uuid4())
        now = now_iso()
        
        row = [
            audit_id, admin_id, action, resource_type, resource_id or "",
            details, ip_address or "", user_agent or "", now
        ]
        sheet.append_row(row)
        
        return audit_id
    
    def get_settings(self) -> List[Dict[str, Any]]:
        """Get all settings"""
        sheet = self.db.get_sheet("Settings")
        all_values = sheet.get_all_values()
        
        if len(all_values) <= 1:
            return []
        
        settings = []
        for row in all_values[1:]:
            if len(row) > 0:
                settings.append({
                    "setting_key": row[0] if len(row) > 0 else "",
                    "setting_value": row[1] if len(row) > 1 else "",
                    "description": row[2] if len(row) > 2 else "",
                    "updated_at": row[3] if len(row) > 3 else ""
                })
        
        return settings
    
    def update_setting(self, key: str, value: str):
        """Update setting"""
        sheet = self.db.get_sheet("Settings")
        all_values = sheet.get_all_values()
        
        # Find setting
        for i, row in enumerate(all_values[1:], start=2):
            if len(row) > 0 and row[0] == key:
                # gspread update() requires list of lists format
                sheet.update(f"B{i}", [[value]])  # setting_value
                sheet.update(f"D{i}", [[now_iso()]])  # updated_at
                return
        
        # Create new setting if not found
        now = now_iso()
        row = [key, value, "", now]
        sheet.append_row(row)
