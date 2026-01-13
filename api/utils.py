"""
Utility functions
"""
import json
import random
from datetime import datetime
from typing import List, Dict, Any, Optional

def now_iso() -> str:
    """Get current time in ISO format"""
    return datetime.utcnow().isoformat() + "Z"

def yyyymm() -> str:
    """Get current year-month in YYYYMM format"""
    now = datetime.now()
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

def is_command(text: str) -> bool:
    """Check if text is a command (exact match)"""
    from api.config import CMD
    return text in CMD.values()

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
