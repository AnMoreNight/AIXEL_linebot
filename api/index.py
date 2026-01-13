"""
AIXEL LINE Bot - Main Application
Converted from Google Apps Script
"""
import os
import logging
from fastapi import FastAPI, Request, Header, HTTPException
from dotenv import load_dotenv
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent

from api.config import (
    LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, CMD, MODE, PLANS, MAX_LINE_SPLITS, CREDIT_PACKS, TAX_RATE
)
from api.database import db, init_database
from api.utils import is_command, match_command, normalize_command, estimate_tokens, split_for_line, now_iso
from api.handlers import (
    ensure_monthly_grant, help_content, credit_status_text, ability_list_text,
    ability_explain_content, run_diagnosis, run_normal_chat
)
from api.training import handle_training_step
from api.config import GOOGLE_SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON

load_dotenv()

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise RuntimeError("Missing LINE credentials in environment variables.")

# Initialize database if not already initialized
if db is None:
    if not GOOGLE_SHEET_ID or not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("Missing Google Sheets credentials. Set GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON.")
    init_database()

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    global db
    if db is None:
        if not GOOGLE_SHEET_ID or not GOOGLE_SERVICE_ACCOUNT_JSON:
            logging.warning("Google Sheets credentials not set. Database operations will fail.")
        else:
            try:
                db = init_database()
                logging.info("Database initialized successfully")
            except Exception as e:
                logging.error(f"Failed to initialize database: {e}")

@app.get("/")
async def health():
    return {"status": "ok"}

@app.post("/api/callback")
async def callback(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    body_str = body.decode("utf-8")

    try:
        handler.handle(body_str, x_line_signature)
    except InvalidSignatureError as e:
        logging.error(f"Signature error: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logging.error(f"Webhook handle error: {e}")
        raise HTTPException(status_code=401, detail=str(e))
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    """Handle incoming message"""
    user_id = event.source.user_id
    message_text = (event.message.text or "").strip()
    
    # Get or create user
    user = db.get_or_create_user(user_id)
    
    # Monthly grant
    ensure_monthly_grant(user)
    
    # Normalize command for matching (Spec 08)
    normalized_text = normalize_command(message_text)
    
    # Log command (not observed - Spec 02)
    if is_command(message_text):
        db.log_event(user_id, "line", "command", user["mode"], False, message_text, 0, {})
    
    # Route by mode
    reply = route_by_mode(user, message_text, "line")
    
    # Log AI response
    is_observed = (user["mode"] == MODE["IDLE"])
    db.log_event(
        user_id, "line", "ai_message", user["mode"],
        is_observed, reply, estimate_tokens(reply), {}
    )
    
    # Consume credits (Spec 09 - different costs for different operations)
    # Note: Diagnosis and training handle their own credit consumption
    if user["mode"] not in [MODE["DIAGNOSIS"], MODE["TRAINING"]]:
        cost = estimate_tokens(reply)
        if user.get("credits", 0) > 0:
            user["credits"] = max(0, user["credits"] - cost)
            user["updated_at"] = now_iso()
            db.save_user(user)
            db.log_event(
                user_id, "system", "credit_change", user["mode"],
                False, f"consume:{cost}", cost, {"reason": "ai_reply"}
            )
    
    # Reply to LINE
    try:
        chunks = split_for_line(reply, MAX_LINE_SPLITS)
        messages = [TextMessage(text=chunk) for chunk in chunks]
        
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=messages
                )
            )
    except Exception as e:
        logging.error(f"LINE reply error: {e}")

@handler.add(FollowEvent)
def handle_follow(event: FollowEvent):
    """Handle when user adds bot as friend"""
    user_id = event.source.user_id
    
    # Get or create user (will create with FREE plan)
    user = db.get_or_create_user(user_id)
    
    # Send welcome message
    welcome = "AIXELへようこそ！\n\n" + help_content()
    
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=welcome)]
                )
            )
    except Exception as e:
        logging.error(f"LINE reply error: {e}")

def route_by_mode(user: dict, text: str, channel: str) -> str:
    """Route message by user mode"""
    text = text.strip()
    
    # Credit depletion check (Spec 02)
    # Commands that work even with 0 credits
    cmd_key = match_command(text)
    allow_when_zero_commands = [
        "CREDIT", "CHANGE", "BUY", "HELP1", "HELP2", "HELP3",
        "DIAG", "TRAIN", "EXPLAIN", "SUPPORT", "INQUIRY"
    ]
    
    if user.get("credits", 0) <= 0 and cmd_key not in allow_when_zero_commands and user["mode"] == MODE["IDLE"]:
        return "\n".join([
            "現在の残クレジットは 0クレジット です。",
            "会話は止めませんが、追加のAI応答を生成できない状態です。",
            "選択肢：",
            "・追加購入：『購入』",
            "・プラン変更：『変更』",
            "・残量確認：『クレジット』"
        ])
    
    # Route by mode
    if user["mode"] == MODE["PLAN_CHANGE"]:
        return handle_plan_change(user, text)
    elif user["mode"] == MODE["BUY_FLOW"]:
        return handle_buy_flow(user, text)
    elif user["mode"] == MODE["ABILITY_EXPLAIN"]:
        return handle_ability_explain(user, text)
    elif user["mode"] == MODE["TRAINING"]:
        return handle_training(user, text)
    else:  # IDLE or default
        return handle_idle(user, text)

def handle_idle(user: dict, text: str) -> str:
    """Handle idle mode"""
    from api.utils import safe_json, normalize_command, match_command
    
    normalized = normalize_command(text)
    cmd_key = match_command(text)
    
    # Support command (Spec 09)
    if cmd_key in ["SUPPORT", "INQUIRY"]:
        user["mode"] = MODE["IDLE"]
        user["mode_started_at"] = now_iso()
        user["updated_at"] = now_iso()
        db.save_user(user)
        return "\n".join([
            "【サポート・問い合わせ】",
            "",
            "AIXELのサポートはメール対応のみです。",
            "",
            "サポート用メールアドレス：",
            "aixel@bilo-g.com",
            "",
            "問い合わせ可能な内容の例：",
            "・動作不具合",
            "・課金・クレジットに関する問題",
            "・利用上の技術的質問",
            "",
            "【注意事項】",
            "・個人情報・決済情報を本文に直接記載しないこと",
            "・返信までに時間がかかる場合があること",
            "",
            "（診断結果・能力評価への意見・修正対応は行いません）"
        ])
    
    # Help
    if cmd_key in ["HELP1", "HELP2", "HELP3"]:
        user["mode"] = MODE["IDLE"]
        user["mode_started_at"] = now_iso()
        user["updated_at"] = now_iso()
        db.save_user(user)
        return help_content()
    
    # Credit status
    if cmd_key == "CREDIT":
        return credit_status_text(user)
    
    # Plan change
    if cmd_key == "CHANGE":
        user["mode"] = MODE["PLAN_CHANGE"]
        user["mode_started_at"] = now_iso()
        user["tmp_json"] = '{"step":"ask_plan"}'
        user["updated_at"] = now_iso()
        db.save_user(user)
        
        db.log_event(user["user_id"], "system", "mode_change", user["mode"], False, "enter_plan_change", 0, {})
        return "\n".join([
            "プラン変更を行います。",
            "希望プランを完全一致で入力してください：",
            "FREE / STANDARD / PRO",
            "",
            "（料金：STANDARD 月額：4,000円（税抜）／PRO 月額：14,000円（税抜））"
        ])
    
    # Buy credits
    if cmd_key == "BUY":
        user["mode"] = MODE["BUY_FLOW"]
        user["mode_started_at"] = now_iso()
        user["tmp_json"] = '{"step":"ask_pack"}'
        user["updated_at"] = now_iso()
        db.save_user(user)
        
        db.log_event(user["user_id"], "system", "mode_change", user["mode"], False, "enter_buy_flow", 0, {})
        return "\n".join([
            "追加クレジット購入（税抜）を行います。希望パックを完全一致で入力してください：",
            "S / M / L",
            "",
            f"S：{CREDIT_PACKS['S']['yenExTax']:,}円（税抜）→ {CREDIT_PACKS['S']['credits']:,}クレジット",
            f"M：{CREDIT_PACKS['M']['yenExTax']:,}円（税抜）→ {CREDIT_PACKS['M']['credits']:,}クレジット",
            f"L：{CREDIT_PACKS['L']['yenExTax']:,}円（税抜）→ {CREDIT_PACKS['L']['credits']:,}クレジット",
            "",
            "（βでは外部決済連携は未接続想定のため、ここでは(購入完了)としてクレジット付与まで実行します。後で外部決済に差し替え可能です）"
        ])
    
    # Ability explain
    if cmd_key == "EXPLAIN":
        user["mode"] = MODE["ABILITY_EXPLAIN"]
        user["mode_started_at"] = now_iso()
        user["tmp_json"] = '{"step":"ask_ability"}'
        user["updated_at"] = now_iso()
        db.save_user(user)
        
        db.log_event(user["user_id"], "system", "mode_change", user["mode"], False, "enter_ability_explain", 0, {})
        return ability_list_text("能力解説を開始します。見たい能力の番号を入力してください：")
    
    # Training
    if cmd_key == "TRAIN":
        user["mode"] = MODE["TRAINING"]
        user["mode_started_at"] = now_iso()
        user["tmp_json"] = '{"step":"ask_ability","qCount":0,"chosen":null,"challenge":null,"attempt":0}'
        user["updated_at"] = now_iso()
        db.save_user(user)
        
        db.log_event(user["user_id"], "system", "mode_change", user["mode"], False, "enter_training", 0, {})
        return ability_list_text("トレーニングを開始します。鍛えたい能力の番号を入力してください：")
    
    # Diagnosis
    if cmd_key == "DIAG":
        return run_diagnosis(user)
    
    # Normal chat (observed - commands excluded)
    # Commands are already logged above, so only log non-commands here
    if not is_command(text):
        db.log_event(
            user["user_id"], "system", "user_message", MODE["IDLE"],
            True, text, estimate_tokens(text), {"channel": "any"}
        )
    return run_normal_chat(user, text)

def handle_plan_change(user: dict, text: str) -> str:
    """Handle plan change mode"""
    from api.utils import safe_json
    
    tmp = safe_json(user.get("tmp_json", "{}"))
    if tmp.get("step") != "ask_plan":
        user["mode"] = MODE["IDLE"]
        user["updated_at"] = now_iso()
        db.save_user(user)
        return "状態が不整合だったため、通常モードに戻しました。"
    
    plan = text.strip().upper()
    if plan not in PLANS:
        return "入力が一致しませんでした。FREE / STANDARD / PRO のいずれかを完全一致で入力してください。"
    
    user["plan"] = plan
    user["mode"] = MODE["IDLE"]
    user["mode_started_at"] = now_iso()
    user["tmp_json"] = "{}"
    user["updated_at"] = now_iso()
    db.save_user(user)
    
    db.log_event(user["user_id"], "system", "billing", user["mode"], False, f"plan_change:{plan}", 0, {})
    return "\n".join([
        f"プランを {plan} に変更しました。",
        credit_status_text(user),
        "（診断の質・深さ・内容はプラン差を設けません。トレーニング/能力解説は提供範囲や粒度が変わります）"
    ])

def handle_buy_flow(user: dict, text: str) -> str:
    """Handle buy flow mode"""
    from api.utils import safe_json
    
    tmp = safe_json(user.get("tmp_json", "{}"))
    if tmp.get("step") != "ask_pack":
        user["mode"] = MODE["IDLE"]
        user["updated_at"] = now_iso()
        db.save_user(user)
        return "状態が不整合だったため、通常モードに戻しました。"
    
    pack = text.strip().upper()
    if pack not in CREDIT_PACKS:
        return "入力が一致しませんでした。S / M / L のいずれかを完全一致で入力してください。"
    
    p = CREDIT_PACKS[pack]
    tax = int(p["yenExTax"] * TAX_RATE)
    yen_in_tax = p["yenExTax"] + tax
    
    # Log purchase
    db.log_purchase(
        user["user_id"], "credit_pack", pack,
        p["yenExTax"], tax, yen_in_tax, p["credits"], "success"
    )
    
    # Grant credits
    user["credits"] = (user.get("credits", 0) or 0) + p["credits"]
    user["mode"] = MODE["IDLE"]
    user["mode_started_at"] = now_iso()
    user["tmp_json"] = "{}"
    user["updated_at"] = now_iso()
    db.save_user(user)
    
    db.log_event(
        user["user_id"], "system", "credit_change", user["mode"],
        False, f"purchase_grant:{pack}:{p['credits']}", p["credits"], {}
    )
    
    return "\n".join([
        "購入が完了しました（β：即時付与）。",
        f"{pack}：{p['yenExTax']:,}円（税抜）／{yen_in_tax:,}円（税込） → {p['credits']:,}クレジット 付与",
        credit_status_text(user)
    ])

def handle_ability_explain(user: dict, text: str) -> str:
    """Handle ability explain mode"""
    from api.utils import safe_json
    
    tmp = safe_json(user.get("tmp_json", "{}"))
    if tmp.get("step") != "ask_ability":
        user["mode"] = MODE["IDLE"]
        user["updated_at"] = now_iso()
        db.save_user(user)
        return "状態が不整合だったため、通常モードに戻しました。"
    
    try:
        n = int(text.strip())
        if n < 1 or n > 11:
            return "1〜11 の番号を入力してください。"
    except ValueError:
        return "1〜11 の番号を入力してください。"
    
    # Not observed
    db.log_event(
        user["user_id"], "system", "user_message", MODE["ABILITY_EXPLAIN"],
        False, text, estimate_tokens(text), {"excluded": True}
    )
    
    msg = ability_explain_content(n, user.get("plan", "FREE"))
    
    # Return to idle
    user["mode"] = MODE["IDLE"]
    user["mode_started_at"] = now_iso()
    user["tmp_json"] = "{}"
    user["updated_at"] = now_iso()
    db.save_user(user)
    
    return msg + "\n\n（能力解説はここまで。続けて通常会話OKです）"

def handle_training(user: dict, text: str) -> str:
    """Handle training mode (Spec 02, Spec 06)"""
    # Training input is NOT observed (Spec 02)
    db.log_event(
        user["user_id"], "system", "user_message", MODE["TRAINING"],
        False, text, 0, {"excluded": True, "training": True}
    )
    
    return handle_training_step(user, text)
