"""
Database operations using Google Sheets
"""
import json
import uuid
from typing import Dict, Any, List, Optional
import gspread
from google.oauth2.service_account import Credentials
from api.utils import now_iso
from api.config import MODE, GOOGLE_SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON

class Database:
    def __init__(self, sheet_id: str = None, service_account_json: str = None):
        self.sheet_id = sheet_id or GOOGLE_SHEET_ID
        self.service_account_json = service_account_json or GOOGLE_SERVICE_ACCOUNT_JSON
        
        if not self.sheet_id:
            raise ValueError("GOOGLE_SHEET_ID is required")
        if not self.service_account_json:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
        
        # Initialize Google Sheets client
        try:
            creds_dict = json.loads(self.service_account_json)
            creds = Credentials.from_service_account_info(creds_dict)
            scoped_creds = creds.with_scopes([
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ])
            self.gc = gspread.authorize(scoped_creds)
            self.spreadsheet = self.gc.open_by_key(self.sheet_id)
        except Exception as e:
            raise ValueError(f"Failed to initialize Google Sheets: {e}")
        
        self.init_sheets()
    
    def get_sheet(self, sheet_name: str):
        """Get or create sheet"""
        try:
            return self.spreadsheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            # Create sheet if it doesn't exist
            sheet = self.spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=20)
            self.init_sheet_headers(sheet_name)
            return sheet
    
    def init_sheets(self):
        """Initialize sheets with headers"""
        self.init_sheet_headers("Users")
        self.init_sheet_headers("Events")
        self.init_sheet_headers("Purchases")
        self.init_sheet_headers("AdminUsers")  # Spec 09: Management UI
        self.init_sheet_headers("Incidents")  # Spec 09: Management UI
        self.init_sheet_headers("AuditLogs")  # Spec 09: Management UI
        self.init_sheet_headers("Settings")  # Spec 09: Management UI
    
    def init_sheet_headers(self, sheet_name: str):
        """Initialize sheet headers"""
        sheet = self.get_sheet(sheet_name)
        
        if sheet_name == "Users":
            headers = ["user_id", "plan", "credits", "last_grant_yyyymm", "mode", 
                      "mode_started_at", "tmp_json", "last_diagnosis_json", "oneshot_experience_used", "created_at", "updated_at"]
        elif sheet_name == "Events":
            headers = ["event_id", "timestamp", "user_id", "channel", "type", "mode",
                      "is_observed", "text", "token_est", "meta_json"]
        elif sheet_name == "Purchases":
            headers = ["purchase_id", "user_id", "product_type", "pack", "amount_yen_ex_tax",
                      "tax", "amount_yen_in_tax", "credits", "status", "created_at", "updated_at"]
        elif sheet_name == "AdminUsers":
            headers = ["admin_id", "email", "password_hash", "role", "display_name", 
                      "created_at", "updated_at", "last_login_at"]
        elif sheet_name == "Incidents":
            headers = ["incident_id", "title", "description", "status", "severity",
                      "created_by", "assigned_to", "target_user_ids", "created_at", "updated_at", "resolved_at"]
        elif sheet_name == "AuditLogs":
            headers = ["audit_id", "admin_id", "action", "resource_type", "resource_id",
                      "details", "ip_address", "user_agent", "created_at"]
        elif sheet_name == "Settings":
            headers = ["setting_key", "setting_value", "description", "updated_at"]
        else:
            return
        
        # Set headers if sheet is empty
        if not sheet.get_all_values():
            sheet.append_row(headers)
    
    def get_or_create_user(self, user_id: str) -> Dict[str, Any]:
        """Get or create user"""
        sheet = self.get_sheet("Users")
        all_values = sheet.get_all_values()
        
        if not all_values:
            self.init_sheet_headers("Users")
            all_values = sheet.get_all_values()
        
        # Find user (skip header row)
        for i, row in enumerate(all_values[1:], start=2):
            if len(row) > 0 and row[0] == user_id:
                return self._row_to_user(row, i)
        
        # Create new user (Spec 01 - FREE gets initial grant)
        now = now_iso()
        from api.config import PLANS
        initial_grant = PLANS["FREE"].get("initialGrant", 5000)  # Spec 07: 5,000クレジット
        user = {
            "user_id": user_id,
            "plan": "FREE",
            "credits": initial_grant,  # Initial grant for FREE plan
            "last_grant_yyyymm": "INITIAL",  # Mark as initial grant
            "mode": MODE["IDLE"],
            "mode_started_at": now,
            "tmp_json": "{}",
            "last_diagnosis_json": "{}",  # Spec 01: Store last diagnosis for reference
            "oneshot_experience_used": False,  # Spec 04: One-shot experience flag
            "created_at": now,
            "updated_at": now
        }
        
        row = [
            user["user_id"], user["plan"], user["credits"], user["last_grant_yyyymm"],
            user["mode"], user["mode_started_at"], user["tmp_json"], user["last_diagnosis_json"],
            str(user["oneshot_experience_used"]), user["created_at"], user["updated_at"]
        ]
        sheet.append_row(row)
        
        # Log initial grant event
        self.log_event(
            user["user_id"], "system", "credit_change", user["mode"],
            False, f"initial_grant:{initial_grant}", initial_grant, {"plan": "FREE", "type": "initial"}
        )
        
        # Get the row index for the new user (after append, it's the last row)
        all_values = sheet.get_all_values()
        row_index = len(all_values)  # Last row is the new user
        user["_row_index"] = row_index
        return user
    
    def _row_to_user(self, row: List[str], row_index: int) -> Dict[str, Any]:
        """Convert sheet row to user dict"""
        # Handle legacy rows without oneshot_experience_used
        oneshot_used = False
        if len(row) > 8:
            oneshot_str = row[8].strip().lower()
            oneshot_used = oneshot_str == "true" or oneshot_str == "1"
        
        return {
            "_row_index": row_index,
            "user_id": row[0] if len(row) > 0 else "",
            "plan": row[1] if len(row) > 1 else "FREE",
            "credits": int(row[2]) if len(row) > 2 and row[2] else 0,
            "last_grant_yyyymm": row[3] if len(row) > 3 else "",
            "mode": row[4] if len(row) > 4 else MODE["IDLE"],
            "mode_started_at": row[5] if len(row) > 5 else "",
            "tmp_json": row[6] if len(row) > 6 else "{}",
            "last_diagnosis_json": row[7] if len(row) > 7 else "{}",
            "oneshot_experience_used": oneshot_used,  # Spec 04
            "created_at": row[9] if len(row) > 9 else "",
            "updated_at": row[10] if len(row) > 10 else ""
        }
    
    def save_user(self, user: Dict[str, Any]):
        """Save user data"""
        sheet = self.get_sheet("Users")
        row_index = user.get("_row_index")
        
        if not row_index:
            # Find user row
            all_values = sheet.get_all_values()
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and row[0] == user["user_id"]:
                    row_index = i
                    user["_row_index"] = i
                    break
        
        if not row_index:
            raise ValueError(f"User not found: {user['user_id']}")
        
        # Prepare row data
        updated_at = user.get("updated_at", now_iso())
        row_data = [
            user["user_id"],  # user_id (A)
            user.get("plan", "FREE"),  # plan (B)
            user.get("credits", 0),  # credits (C)
            user.get("last_grant_yyyymm", ""),  # last_grant_yyyymm (D)
            user.get("mode", MODE["IDLE"]),  # mode (E)
            user.get("mode_started_at", ""),  # mode_started_at (F)
            user.get("tmp_json", "{}"),  # tmp_json (G)
            user.get("last_diagnosis_json", "{}"),  # last_diagnosis_json (H) - Spec 01
            str(user.get("oneshot_experience_used", False)),  # oneshot_experience_used (I) - Spec 04
            user.get("created_at", ""),  # created_at (J)
            updated_at  # updated_at (K)
        ]
        
        # Update entire row at once
        sheet.update(f"A{row_index}:K{row_index}", [row_data])
    
    def log_event(self, user_id: str, channel: str, event_type: str, mode: str,
                  is_observed: bool, text: str = "", token_est: int = 0, meta: Dict = None):
        """Log event"""
        sheet = self.get_sheet("Events")
        
        event_id = str(uuid.uuid4())
        timestamp = now_iso()
        meta_json = json.dumps(meta or {})
        
        row = [
            event_id, timestamp, user_id, channel, event_type, mode,
            "true" if is_observed else "false", text or "", token_est, meta_json
        ]
        sheet.append_row(row)
        
        return event_id
    
    def get_observed_user_messages(self, user_id: str, limit: int = 10) -> List[str]:
        """Get observed user messages (for diagnosis)"""
        sheet = self.get_sheet("Events")
        all_values = sheet.get_all_values()
        
        if len(all_values) <= 1:
            return []
        
        messages = []
        # Iterate from bottom to top (most recent first)
        for row in reversed(all_values[1:]):
            if len(row) < 7:
                continue
            
            row_user_id = row[2] if len(row) > 2 else ""
            row_type = row[4] if len(row) > 4 else ""
            row_observed = row[6] if len(row) > 6 else ""
            row_text = row[7] if len(row) > 7 else ""
            
            if (row_user_id == user_id and 
                row_observed == "true" and 
                row_type == "user_message" and 
                row_text):
                messages.append(row_text)
                if len(messages) >= limit:
                    break
        
        # Reverse to get chronological order
        return list(reversed(messages))
    
    def log_purchase(self, user_id: str, product_type: str, pack: str,
                    amount_yen_ex_tax: int, tax: int, amount_yen_in_tax: int,
                    credits: int, status: str = "success"):
        """Log purchase"""
        sheet = self.get_sheet("Purchases")
        
        purchase_id = str(uuid.uuid4())
        now = now_iso()
        
        row = [
            purchase_id, user_id, product_type, pack, amount_yen_ex_tax,
            tax, amount_yen_in_tax, credits, status, now, now
        ]
        sheet.append_row(row)
        
        return purchase_id

# Global database instance
db = None

def init_database(sheet_id: str = None, service_account_json: str = None):
    """Initialize global database instance"""
    global db
    db = Database(sheet_id, service_account_json)
    return db

# Try to initialize if credentials are available
try:
    if GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON:
        db = Database()
except Exception:
    # Will be initialized later
    pass
