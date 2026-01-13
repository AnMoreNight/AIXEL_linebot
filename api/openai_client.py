"""
OpenAI API client
"""
import requests
import json
from typing import List, Dict, Any
from api.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL

def call_openai(messages: List[Dict[str, str]]) -> str:
    """Call OpenAI API"""
    if not OPENAI_API_KEY:
        return "（OPENAI_API_KEY が未設定です。環境変数に設定してください）"
    
    url = f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": 0.7
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if "choices" in data and len(data["choices"]) > 0:
            content = data["choices"][0].get("message", {}).get("content", "")
            return content.strip()
        return "（応答が空でした）"
    except requests.exceptions.RequestException as e:
        return f"（OpenAI API call failed: {e}）"
    except json.JSONDecodeError as e:
        return f"（OpenAI API response parse error: {e}）"
