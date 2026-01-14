"""
Utility functions
"""
import json
import random
from datetime import datetime
from typing import List, Dict, Any, Optional
import pytz
from api.config import TIMEZONE

# Get timezone object
_tz = pytz.timezone(TIMEZONE)

def now_iso() -> str:
    """Get current time in ISO format without timezone offset (Asia/Tokyo timezone)"""
    now = datetime.now(_tz)
    # Convert to Asia/Tokyo timezone but format without offset
    return now.strftime("%Y-%m-%dT%H:%M:%S")

def yyyymm() -> str:
    """Get current year-month in YYYYMM format (Asia/Tokyo timezone)"""
    now = datetime.now(_tz)
    return f"{now.year}{now.month:02d}"

def safe_json(s: str) -> Dict[str, Any]:
    """Safely parse JSON string"""
    try:
        return json.loads(s or "{}")
    except:
        return {}

def estimate_tokens(text: str) -> int:
    """Estimate token count (rough estimate: chars/4 for Japanese)"""
    if not text:
        return 1
    return max(1, (len(text) + 3) // 4)

def normalize_command(text: str) -> str:
    """Normalize command text for exact matching (Spec 08)
    - Remove leading/trailing whitespace
    - Remove newlines and invisible characters
    - Keep full-width/half-width distinction
    """
    if not text:
        return ""
    # Remove whitespace, newlines, and invisible chars
    normalized = "".join(c for c in text if c.isprintable() and not c.isspace())
    return normalized

def is_command(text: str) -> bool:
    """Check if text is a command (exact match with normalization - Spec 08)"""
    from api.config import CMD
    normalized = normalize_command(text)
    return normalized in CMD.values()

def match_command(text: str) -> Optional[str]:
    """Match normalized command text to command value"""
    from api.config import CMD
    normalized = normalize_command(text)
    for cmd_key, cmd_value in CMD.items():
        if normalized == cmd_value:
            return cmd_key
    return None

def random_choice(arr: List[Any]) -> Any:
    """Random choice from array"""
    return arr[random.randint(0, len(arr) - 1)] if arr else None

def split_for_line(text: str, max_splits: int) -> List[str]:
    """Split text for LINE (max 4500 chars per message)"""
    MAX = 4500
    if not text:
        return [""]
    if len(text) <= MAX:
        return [text]
    
    chunks = []
    s = text
    while len(s) > 0 and len(chunks) < max_splits:
        chunks.append(s[:MAX])
        s = s[MAX:]
    if len(s) > 0:
        chunks.append("（以下略：分割上限に達しました）")
    return chunks
