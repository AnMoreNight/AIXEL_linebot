"""
Training system implementation (Spec 02, Spec 06)
"""
from typing import Dict, Any, List, Optional
from api.config import ABILITIES, PLANS, MODE
from api.database import db
from api.openai_client import call_openai
from api.utils import now_iso, safe_json

# Training type definitions (Spec 06 - simplified structure for now)
# Each ability has 10 types, but we'll implement a framework that can generate them
TRAINING_TYPES = {
    "abstract": {
        1: {
            "name": "共通点抽出型",
            "challenge": "具体例を3つ挙げて、共通点を1つにまとめてください（「要するに」で1文）。",
            "observation_point": "3つが同カテゴリでなくても共通構造を取れているか / 「特徴の羅列」ではなく「仕組み」として言えているか"
        },
        2: {
            "name": "目的→再利用原理変換型",
            "challenge": "この目的を、他の場面でも使える「原理」として言い換えてください（『〜すると〜になりやすい』の形で1文）。",
            "observation_point": "目的が特定行動ではなく判断原理に変換されているか / 状況が変わっても使える抽象度になっているか"
        }
        # Add more types as needed...
    },
    "decompose": {
        1: {
            "name": "ゴール逆算分解型",
            "challenge": "このゴールを達成するために必要な要素を、逆算で5つに分解してください。",
            "observation_point": "ゴールから逆方向に分けているか / 抜けている前提条件がないか"
        }
        # Add more types as needed...
    }
    # Add other abilities as needed...
}

def get_training_challenge(ability_id: int, training_type: int = 1) -> Optional[Dict[str, Any]]:
    """Get training challenge for ability and type"""
    ability = next((a for a in ABILITIES if a["id"] == ability_id), None)
    if not ability:
        return None
    
    ability_key = ability["key"]
    types = TRAINING_TYPES.get(ability_key, {})
    challenge_def = types.get(training_type)
    
    if not challenge_def:
        # Generate a basic challenge if type not defined
        challenge_def = {
            "name": f"型{training_type}",
            "challenge": f"【{ability['name']}の練習】\n\nこの能力を使う場面を想定して、具体的な課題を提示してください。",
            "observation_point": "能力の観測ポイントが満たされているか"
        }
    
    return {
        "ability_id": ability_id,
        "ability_name": ability["name"],
        "type": training_type,
        "challenge": challenge_def["challenge"],
        "observation_point": challenge_def.get("observation_point", "")
    }

def generate_training_feedback(
    user_input: str,
    challenge: str,
    ability_id: int,
    plan: str,
    previous_state: Optional[str] = None
) -> str:
    """Generate training feedback (Spec 02, Spec 05 - differential base from training start)"""
    ability = next((a for a in ABILITIES if a["id"] == ability_id), None)
    if not ability:
        return "能力が見つかりませんでした。"
    
    # Plan-based granularity (Spec 02, Spec 05)
    tier = "PRO" if plan == "PRO" else ("STANDARD" if plan == "STANDARD" else "FREE")
    
    system_prompt = "\n".join([
        "You are AIXEL's training feedback generator. Provide feedback on the user's training input.",
        "",
        "Core principles:",
        "- Do NOT evaluate as success/failure",
        "- Do NOT use evaluation words (good/bad, correct/incorrect)",
        "- Focus on factual observation of what thinking operations were used",
        "- Provide differential feedback: what changed from before training started",
        "- No commands, no assertions, no growth language",
        "",
        f"Ability: {ability['name']}",
        f"Challenge: {challenge}",
        "",
        "Feedback granularity by plan:",
        "- FREE: Observe one fact only, short language",
        "- STANDARD: Observed facts + supplementary explanation",
        "- PRO: Observed facts + structural explanation (reuse perspective)",
        "",
        "Output format:",
        "1. What thinking operations were observed (factual)",
        "2. What changed from before training (differential)",
        "3. One awareness point for daily use (1 line)"
    ])
    
    user_prompt = "\n".join([
        f"ユーザーの入力：",
        user_input,
        "",
        "上記の入力について、観測した事実と差分をフィードバックしてください。"
    ])
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    feedback = call_openai(messages)
    
    if not feedback:
        # Fallback
        if tier == "FREE":
            feedback = "観測した事実：入力がありました。"
        elif tier == "STANDARD":
            feedback = "観測した事実：入力がありました。\n補足：この能力を使う場面を意識できています。"
        else:
            feedback = "観測した事実：入力がありました。\n構造説明：この能力の構造を理解するための視点が含まれています。"
    
    return feedback

def handle_training_step(user: Dict[str, Any], text: str) -> str:
    """Handle training mode step (Spec 02, Spec 06)"""
    tmp = safe_json(user.get("tmp_json", "{}"))
    step = tmp.get("step", "ask_ability")
    plan = user.get("plan", "FREE")
    
    # Step 1: Ask ability
    if step == "ask_ability":
        try:
            n = int(text.strip())
            if n < 1 or n > 11:
                return "1〜11 の番号を入力してください。"
        except ValueError:
            return "1〜11 の番号を入力してください。"
        
        # Check plan restrictions (Spec 02)
        if plan == "FREE" and n not in PLANS["FREE"]["trainingAllowed"]:
            return "\n".join([
                "現在のプラン（FREE）では、トレーニング対象は以下のみです：",
                "1 抽象化能力 / 2 分解能力",
                "",
                "他の能力をトレーニングしたい場合：『変更』で STANDARD / PRO を選択できます。",
                "（トレーニングは任意です。無理に誘導はしません）"
            ])
        
        # Get training challenge
        challenge_def = get_training_challenge(n, 1)  # Start with type 1
        if not challenge_def:
            return "トレーニング課題の取得に失敗しました。"
        
        # Update state
        import json
        tmp["step"] = "challenge"
        tmp["ability_id"] = n
        tmp["training_type"] = 1
        tmp["q_count"] = 0
        tmp["attempt"] = 0
        user["tmp_json"] = json.dumps(tmp, ensure_ascii=False)
        user["updated_at"] = now_iso()
        db.save_user(user)
        
        # Not observed (Spec 02)
        db.log_event(
            user["user_id"], "system", "user_message", MODE["TRAINING"],
            False, text, 0, {"excluded": True, "training_ability": n}
        )
        
        # Return challenge
        return "\n".join([
            f"【トレーニング：{challenge_def['ability_name']}】",
            "",
            "能力の簡単な説明：",
            f"{challenge_def['ability_name']}は、{get_ability_simple_explanation(n)}",
            "",
            "課題：",
            challenge_def["challenge"],
            "",
            "回答を入力してください（質問は最大4回まで可能です）。"
        ])
    
    # Step 2: Handle challenge input
    elif step == "challenge":
        ability_id = tmp.get("ability_id")
        q_count = tmp.get("q_count", 0)
        
        # Check if it's a question (Spec 02)
        is_question = "？" in text or "?" in text or any(kw in text for kw in ["質問", "確認", "教えて", "どういう", "意味"])
        
        if is_question and q_count < 4:
            # Answer question (Spec 02)
            import json
            tmp["q_count"] = q_count + 1
            user["tmp_json"] = json.dumps(tmp, ensure_ascii=False)
            user["updated_at"] = now_iso()
            db.save_user(user)
            
            # Generate question answer
            challenge_def = get_training_challenge(ability_id, tmp.get("training_type", 1))
            if challenge_def:
                answer = f"課題について：{challenge_def['challenge']}\n\n観測ポイント：{challenge_def.get('observation_point', '')}"
            else:
                answer = "課題について質問を受け付けました。回答を入力してください。"
            
            return answer
        
        elif is_question and q_count >= 4:
            # Reset challenge (Spec 02)
            import json
            tmp["training_type"] = (tmp.get("training_type", 1) % 10) + 1  # Cycle through types
            tmp["q_count"] = 0
            tmp["step"] = "challenge"
            user["tmp_json"] = json.dumps(tmp, ensure_ascii=False)
            user["updated_at"] = now_iso()
            db.save_user(user)
            
            challenge_def = get_training_challenge(ability_id, tmp["training_type"])
            if challenge_def:
                return "\n".join([
                    "質問回数が上限に達したため、別設計の課題に切り替えます。",
                    "",
                    "【新しい課題】",
                    challenge_def["challenge"]
                ])
        
        # Process user input
        challenge_def = get_training_challenge(ability_id, tmp.get("training_type", 1))
        if not challenge_def:
            return "状態エラーが発生しました。"
        
        # Generate feedback (Spec 02, Spec 05)
        feedback = generate_training_feedback(
            text,
            challenge_def["challenge"],
            ability_id,
            plan,
            None  # Previous state (would be from before training start)
        )
        
        # Consume credits (Spec 09)
        cost = 500 if plan == "FREE" else (700 if plan == "STANDARD" else 1000)
        if user.get("credits", 0) >= cost:
            user["credits"] = max(0, user["credits"] - cost)
            db.log_event(
                user["user_id"], "system", "credit_change", user["mode"],
                False, f"training_consume:{cost}", cost, {"reason": "training", "ability": ability_id}
            )
        else:
            # Not enough credits - return to idle (Spec 02)
            user["mode"] = MODE["IDLE"]
            user["tmp_json"] = "{}"
            user["updated_at"] = now_iso()
            db.save_user(user)
            return "\n".join([
                "トレーニングを実行するにはクレジットが不足しています。",
                f"必要：約{cost}クレジット、現在：{user.get('credits', 0)}クレジット",
                "",
                "Idle（通常モード）に戻りました。"
            ])
        
        # Final state: Return to idle with awareness point
        awareness_point = get_awareness_point(ability_id, plan)
        
        import json
        user["mode"] = MODE["IDLE"]
        user["mode_started_at"] = now_iso()
        user["tmp_json"] = "{}"
        user["updated_at"] = now_iso()
        db.save_user(user)
        
        db.log_event(
            user["user_id"], "system", "training_complete", MODE["IDLE"],
            False, f"training:{ability_id}", 0, {"ability": ability_id}
        )
        
        return "\n".join([
            "【フィードバック】",
            feedback,
            "",
            "日常で意識するポイント：",
            awareness_point,
            "",
            "（トレーニング終了。Idle（通常モード）に戻りました）"
        ])
    
    # Invalid state
    user["mode"] = MODE["IDLE"]
    user["tmp_json"] = "{}"
    user["updated_at"] = now_iso()
    db.save_user(user)
    return "状態が不整合だったため、通常モードに戻しました。"

def get_ability_simple_explanation(ability_id: int) -> str:
    """Get simple explanation for ability (小学生でもわかる言葉 - Spec 02)"""
    explanations = {
        1: "個別の話から共通ルール（本質）を抜き出して、別の場面でも使える形にする力です。",
        2: "大きい課題を「作業できる粒度」まで切り分け、順番と依存関係を作る力です。",
        3: "曖昧な要求を、条件・禁止・例外として文章化する力です。",
        4: "会話・設計の前提、決定事項、制約を保持し、矛盾なく積み上げる力です。",
        5: "次に必要な情報を得るために、良い質問を作る力です。",
        6: "不確実な状況で、原因・解決策の仮説を立て、検証可能にする力です。",
        7: "結論を急がず、判断保留・情報不足を認め、探索フェーズを設ける力です。",
        8: "自分の思考の癖・前提・感情の影響を「対象化」して扱う力です。",
        9: "不要な案・機能・論点を切り捨ててシンプルにする力です。",
        10: "意思決定の評価軸（思想・制約・ゴール）を保持し、ブレずに選ぶ力です。",
        11: "一度作った思考・仕様・成果を、次回以降も使える形（テンプレ・ルール）にする力です。"
    }
    return explanations.get(ability_id, "思考能力の一つです。")

def get_awareness_point(ability_id: int, plan: str) -> str:
    """Get awareness point for daily use (Spec 02)"""
    points = {
        1: "具体例から共通点を見つける意識",
        2: "大きな課題を小さく分ける意識",
        3: "曖昧な言葉を明確にする意識",
        4: "前提を確認する意識",
        5: "質問を作る意識",
        6: "仮説を立てる意識",
        7: "判断を保留する意識",
        8: "自分の思考を俯瞰する意識",
        9: "不要なものを捨てる意識",
        10: "判断基準を固定する意識",
        11: "再利用できる形にする意識"
    }
    return points.get(ability_id, "この能力を使う意識")
