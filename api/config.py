"""
AIXEL Configuration
Constants and configuration from GAS version
"""
import os
from typing import Dict, Any

# Plans configuration (Spec 02, Spec 07 - corrected)
PLANS = {
    "FREE": {"monthlyGrant": 0, "initialGrant": 5000, "trainingAllowed": [1, 2], "label": "FREE"},
    "STANDARD": {"monthlyGrant": 65000, "initialGrant": 0, "trainingAllowed": "ALL", "label": "STANDARD"},
    "PRO": {"monthlyGrant": 130000, "initialGrant": 0, "trainingAllowed": "ALL", "label": "PRO"}
}

# Credit packs (tax excluded)
CREDIT_PACKS = {
    "S": {"yenExTax": 2000, "credits": 50000},
    "M": {"yenExTax": 5000, "credits": 125000},
    "L": {"yenExTax": 10000, "credits": 250000}
}

# Tax rate (Japan: 10%)
TAX_RATE = 0.10

# Commands (exact match only - Spec 02, Spec 09)
CMD = {
    "DIAG": "診断",
    "TRAIN": "トレーニング",
    "EXPLAIN": "能力解説",
    "CREDIT": "クレジット",
    "CHANGE": "変更",
    "BUY": "購入",
    "HELP1": "説明",
    "HELP2": "使い方",
    "HELP3": "ヘルプ",
    "SUPPORT": "サポート",
    "INQUIRY": "問い合わせ"
}

# Modes
MODE = {
    "IDLE": "idle",
    "DIAGNOSIS": "diagnosis",
    "TRAINING": "training",
    "ABILITY_EXPLAIN": "ability_explain",
    "HELP": "help",
    "PLAN_CHANGE": "plan_change",
    "BUY_FLOW": "buy_flow"
}

# 11 Abilities
ABILITIES = [
    {"id": 1, "key": "abstract", "name": "抽象化能力"},
    {"id": 2, "key": "decompose", "name": "分解能力"},
    {"id": 3, "key": "specify", "name": "仕様言語化能力"},
    {"id": 4, "key": "context", "name": "文脈保持能力"},
    {"id": 5, "key": "question", "name": "問い生成能力"},
    {"id": 6, "key": "hypothesis", "name": "仮説構築能力"},
    {"id": 7, "key": "pause", "name": "思考の一時停止能力"},
    {"id": 8, "key": "metacog", "name": "メタ認知能力"},
    {"id": 9, "key": "discard", "name": "捨てる能力"},
    {"id": 10, "key": "criteria", "name": "判断基準保持能力"},
    {"id": 11, "key": "reuse", "name": "再利用設計能力"}
]

# LINE max splits
MAX_LINE_SPLITS = int(os.getenv("MAX_LINE_SPLITS", "6"))

# OpenAI settings
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

# LINE settings
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")

# Google Sheets settings
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

# Timezone settings
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tokyo")
