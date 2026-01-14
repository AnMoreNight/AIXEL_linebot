"""
Command handlers and business logic
"""
import json
from typing import Dict, Any, List
from api.config import (
    PLANS, CREDIT_PACKS, TAX_RATE, CMD, MODE, ABILITIES
)
from api.utils import (
    now_iso, yyyymm, safe_json, estimate_tokens, random_choice
)
from api.database import db
from api.openai_client import call_openai

def ensure_monthly_grant(user: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure monthly grant is given if not yet this month (Spec 01 - v0.7正式仕様)
    FREE: Initial 10,000 credits only (once at registration)
    STANDARD/PRO: Monthly grants
    """
    plan = user.get("plan", "FREE")
    plan_config = PLANS.get(plan, PLANS["FREE"])
    
    # FREE plan: Initial grant only (once)
    if plan == "FREE":
        # Check if initial grant was given
        if user.get("credits", 0) == 0 and not user.get("last_grant_yyyymm"):
            amount = plan_config.get("initialGrant", 5000)  # Spec 07: 5,000クレジット
            user["credits"] = amount
            user["last_grant_yyyymm"] = "INITIAL"  # Mark as initial grant
            user["updated_at"] = now_iso()
            db.save_user(user)
            
            db.log_event(
                user["user_id"], "system", "credit_change", user["mode"],
                False, f"initial_grant:{amount}", amount, {"plan": plan, "type": "initial"}
            )
            return {"granted": True, "amount": amount, "type": "initial"}
        return {"granted": False, "amount": 0, "type": "none"}
    
    # STANDARD/PRO: Monthly grants
    ym = yyyymm()
    if user.get("last_grant_yyyymm") == ym:
        return {"granted": False, "amount": 0, "type": "none"}
    
    amount = plan_config.get("monthlyGrant", 0)
    if amount > 0:
        user["credits"] = (user.get("credits", 0) or 0) + amount
        user["last_grant_yyyymm"] = ym
        user["updated_at"] = now_iso()
        db.save_user(user)
        
        db.log_event(
            user["user_id"], "system", "credit_change", user["mode"],
            False, f"monthly_grant:{amount}", amount, {"ym": ym, "plan": plan, "type": "monthly"}
        )
        return {"granted": True, "amount": amount, "type": "monthly"}
    
    return {"granted": False, "amount": 0, "type": "none"}

def ability_explain_content(ability_id: int, plan: str) -> str:
    """Generate ability explanation content (Spec 08 - v0.8確定版: 4-block structure)"""
    ability = next((a for a in ABILITIES if a["id"] == ability_id), None)
    if not ability:
        return "不明な能力です。"
    
    # Plan-based granularity (Spec 08 - 6)
    tier = "PRO" if plan == "PRO" else ("STANDARD" if plan == "STANDARD" else "FREE")
    
    # Ability definitions for explanation (Spec 08 - 5: 4-block structure)
    # Spec 08 - 5-①: 小学生でもわかる言葉、抽象論・専門用語禁止
    defs = {
        "abstract": {
            "def": "具体例から「共通点」を見つけて、別の場面でも使える形にする力です。",
            "effect": "AIに汎用プロンプト設計、再利用テンプレの作成、戦略の型化をさせるのに効きます。",
            "change": "この能力が使われると、AIは「今回だけの答え」ではなく「次回も使える型」で応答します。",
            "timing": ["AIにお願いするとき", "何かを決めなければいけないとき", "複数の話をまとめたいとき"],
            "prompts": [
                "この状況を「パターン」として抽象化して。再利用できる形にして。"
            ]
        },
        "decompose": {
            "def": "大きい目標を、小さな作業に分けて、順番を作る力です。",
            "effect": "AIに実装タスク分割、仕様分割、障害切り分けをさせる時に効きます。",
            "change": "この能力が使われると、AIは「全部まとめて」ではなく「1つずつ順番に」応答します。",
            "timing": ["AIにお願いするとき", "何かを決めなければいけないとき", "やることが多すぎる時"],
            "prompts": [
                "このゴールを最小タスクに分解して、依存関係付きで並べて。"
            ]
        },
        "specify": {
            "def": "曖昧な言葉を、AIが迷わない「条件・禁止・例外」として書く力です。",
            "effect": "AIに仕様書化、受け渡し、テスト観点化をさせる時に効きます。",
            "change": "この能力が使われると、AIは「いい感じに」ではなく「具体的に」応答します。",
            "timing": ["AIにお願いするとき", "何かを決めなければいけないとき", "指示を出すとき"],
            "prompts": [
                "この要件を「定義／入出力／例外／禁止」で仕様化して。"
            ]
        },
        "context": {
            "def": "会話や設計の「前提・決まったこと・制約」を忘れずに、矛盾なく進める力です。",
            "effect": "AIに長期プロジェクトの破綻防止、統合仕様の維持をさせる時に効きます。",
            "change": "この能力が使われると、AIは「前の話を忘れて」ではなく「前の前提を覚えて」応答します。",
            "timing": ["AIにお願いするとき", "何かを決めなければいけないとき", "質問をするとき"],
            "prompts": [
                "いまの提案が既決事項と矛盾する箇所を検出して。"
            ]
        },
        "question": {
            "def": "次に必要な情報を得るために、良い質問を作る力です。",
            "effect": "AIに要件定義、ユーザー調査、設計レビューをさせる時に効きます。",
            "change": "この能力が使われると、AIは「足りない情報を推測して」ではなく「必要な情報を聞いて」応答します。",
            "timing": ["AIに質問するとき", "何かを決めなければいけないとき", "指示を出すとき"],
            "prompts": [
                "この要件を確定するために必要な質問を5つ作って。"
            ]
        },
        "hypothesis": {
            "def": "原因や解決策の「仮説」を立てて、確認できる形にする力です。",
            "effect": "AIにバグ原因推定、集客改善、施策検証をさせる時に効きます。",
            "change": "この能力が使われると、AIは「これが原因だ」と決めつけず「原因候補を複数出して」応答します。",
            "timing": ["AIに質問するとき", "何かを決めなければいけないとき", "判断が必要なとき"],
            "prompts": [
                "起きている問題の原因仮説を3つ出し、検証方法も付けて。"
            ]
        },
        "pause": {
            "def": "結論を急がず、判断を保留して、情報を集める時間を作る力です。",
            "effect": "AIに仕様凍結判断、優先順位付け、リスク低減をさせる時に効きます。",
            "change": "この能力が使われると、AIは「とりあえず決める」ではなく「判断を保留して情報を集める」応答をします。",
            "timing": ["AIに質問するとき", "何かを決めなければいけないとき", "判断が必要なとき"],
            "prompts": [
                "今は決めるには情報不足。追加で必要な情報と集め方を出して。"
            ]
        },
        "metacog": {
            "def": "自分の「考え方の癖・前提・感情の影響」を外から見て、扱う力です。",
            "effect": "AIに意思決定の質改善、共進化、学習設計をさせる時に効きます。",
            "change": "この能力が使われると、AIは「あなたの意見」ではなく「あなたの思考パターン」を対象にして応答します。",
            "timing": ["AIに質問するとき", "何かを決めなければいけないとき", "判断が必要なとき"],
            "prompts": [
                "いまの私の前提・バイアス候補を列挙して。"
            ]
        },
        "discard": {
            "def": "不要な案・機能・論点を切り捨てて、シンプルにする力です。",
            "effect": "AIにMVP設計、仕様凍結、工数削減をさせる時に効きます。",
            "change": "この能力が使われると、AIは「全部やる」ではなく「最小限で成立させる」応答をします。",
            "timing": ["AIにお願いするとき", "何かを決めなければいけないとき", "指示を出すとき"],
            "prompts": [
                "この機能群を「捨てる前提」でMVPに落として。"
            ]
        },
        "criteria": {
            "def": "判断の「基準（何を優先するか）」を固定して、ブレずに選ぶ力です。",
            "effect": "AIに仕様一貫性、ブランド一貫性、価格設計をさせる時に効きます。",
            "change": "この能力が使われると、AIは「その場の気分で」ではなく「固定した基準で」応答します。",
            "timing": ["AIに質問するとき", "何かを決めなければいけないとき", "判断が必要なとき"],
            "prompts": [
                "判断基準を3つに固定して、以後それで評価して。"
            ]
        },
        "reuse": {
            "def": "一度作った思考・仕様・成果を、次回も使える形にする力です。",
            "effect": "AIに社内運用、SOP、教育コンテンツ化をさせる時に効きます。",
            "change": "この能力が使われると、AIは「今回限り」ではなく「次回も使える形」で応答します。",
            "timing": ["AIにお願いするとき", "何かを決めなければいけないとき", "指示を出すとき"],
            "prompts": [
                "この結論を再利用できるチェックリストにして。"
            ]
        }
    }
    
    ability_def = defs.get(ability["key"], {
        "def": "思考能力の一つです。",
        "effect": "",
        "change": "AIの応答が変わります。",
        "timing": [],
        "prompts": []
    })
    
    # Plan-based granularity (Spec 08 - 6)
    tier = "PRO" if plan == "PRO" else ("STANDARD" if plan == "STANDARD" else "FREE")
    
    # Spec 08 - 5: 4-block structure (固定)
    lines = []
    
    # ① この能力は何をする力か（定義）
    # Spec 08 - 5-①: 小学生でもわかる言葉、抽象論・専門用語禁止、「考える力」など曖昧語禁止
    lines.append("① この能力は何をする力か")
    if tier == "FREE":
        # FREE: 1-2 sentences
        lines.append(ability_def["def"])
    elif tier == "STANDARD":
        # STANDARD: 2-4 sentences
        lines.append(ability_def["def"])
        if ability_def.get("effect"):
            lines.append("")
            lines.append(f"（{ability_def['effect']}）")
    else:  # PRO
        # PRO: 4-6 sentences, structure/reuse perspective
        lines.append(ability_def["def"])
        if ability_def.get("effect"):
            lines.append("")
            lines.append(f"（{ability_def['effect']}）")
            lines.append("")
            lines.append("この能力は、AIに渡す入力の設計精度を上げる方向で効きます。")
    
    # ② どんな場面で使われるか（具体例）
    # Spec 08 - 5-②: 日常・仕事・AI利用の混在OK、最低2例、判断・質問・指示と結びつける
    lines.append("")
    lines.append("② どんな場面で使われるか")
    timing_examples = ability_def.get("timing", [])
    if timing_examples:
        if tier == "FREE":
            # FREE: Simple examples, 1-2 sentences (Spec 08 - 6)
            if len(timing_examples) >= 1:
                lines.append(f"・{timing_examples[0]}")
            if len(timing_examples) >= 2:
                lines.append(f"・{timing_examples[1]}")
        elif tier == "STANDARD":
            # STANDARD: 2-4 sentences, "why" supplement (Spec 08 - 6)
            for i, t in enumerate(timing_examples[:2]):
                lines.append(f"・{t}")
            if len(timing_examples) >= 3:
                lines.append(f"・{timing_examples[2]}")
        else:  # PRO
            # PRO: 4-6 sentences, structure/reuse perspective, relationship with other abilities (Spec 08 - 6)
            for t in timing_examples:
                lines.append(f"・{t}")
    else:
        lines.append("・思考を要する場面")
        lines.append("・AIを使う場面")
    
    # ③ AIを使うとき、何が変わるか
    # Spec 08 - 5-③: 「こう使える」ではなく「こう変わる」、成長・上達・レベル表現禁止、Before/After構造OK
    lines.append("")
    lines.append("③ AIを使うとき、何が変わるか")
    change_text = ability_def.get("change", "")
    if not change_text and ability_def.get("effect"):
        # Generate change text from effect if not explicitly defined
        change_text = f"この能力が使われると、{ability_def['effect']}"
    
    if tier == "FREE":
        # FREE: 1-2 sentences
        if change_text:
            lines.append(change_text.split("。")[0] + "。")
        else:
            lines.append("AIの応答が意図に近づきます。")
    elif tier == "STANDARD":
        # STANDARD: 2-4 sentences, AI perspective included
        if change_text:
            lines.append(change_text)
        else:
            lines.append("AIの応答が意図に近づきます。")
            lines.append("AIは推測せずに判断できるようになります。")
    else:  # PRO
        # PRO: 4-6 sentences, structure/reuse perspective
        if change_text:
            lines.append(change_text)
            lines.append("")
            lines.append("AIは入力の構造を理解し、再利用可能な形で応答します。")
        else:
            lines.append("AIの応答が意図に近づきます。")
            lines.append("AIは推測せずに判断できるようになります。")
            lines.append("")
            lines.append("入力の構造が明確になることで、AIは再利用可能な形で応答します。")
    
    # ④ 例（プロンプト例・質問例）
    # Spec 08 - 5-④: 必ず1例、正解例ではない、あくまで「一例」
    lines.append("")
    lines.append("④ 例")
    prompts = ability_def.get("prompts", [])
    if prompts:
        # Always show at least 1 example (Spec 08 - 5-④: 必ず1例)
        example = prompts[0]
        lines.append(f"例：")
        lines.append(f"{example}")
    else:
        # Fallback example
        lines.append("例：")
        lines.append(f"この能力を使う場面での入力例")
    
    # Spec 08 - 7: Prohibited items check (no right/wrong, growth, evaluation, commands, scores, ranks)
    # Spec 08 - 8: Tone rules (explicit subjects, short sentences, no jargon, no condescending tone)
    # These are enforced in the content generation above
    
    return "\n".join(lines)

def help_content() -> str:
    """Help content (Spec 02 - 5)"""
    return "\n".join([
        "AIXELは「答えを出すAI」ではありません。",
        "あなたのAI使用を観測し、思考フォームを診断し、改善の選択肢を提示するパーソナルトレーナー型AIです。",
        "",
        "【普段】",
        "通常会話はできます（内部では観測ログを溜めます）。",
        "自動で診断や指摘はしません。",
        "",
        "【診断】",
        "実行したいタイミングで、コマンド『診断』と入力してください。",
        "直近ログ（最大10件）を対象に診断を実行します。",
        "",
        "【トレーニング】",
        "コマンド『トレーニング』→能力番号で開始します。",
        "11能力一覧を表示し、番号で選択してください。",
        "開始後は完了まで誘導します。",
        "トレーニングで得た気づきを直後にIdle（通常モード）で実践するのが有効です。",
        "",
        "【能力解説】",
        "コマンド『能力解説』→能力番号で各能力の説明を表示します。",
        "11能力一覧を表示し、番号で選択してください。",
        "",
        "【クレジット】",
        "1クレジット＝1トークン。すべてのAI応答で消費されます。",
        "原価：0.006円／クレジット",
        "無制限・使い放題は採用しません。",
        "残量確認：『クレジット』",
        "追加購入：『購入』",
        "プラン変更：『変更』",
        "枯渇時は選択肢（購入／変更）を提示します。",
        "",
        "【推奨利用】",
        "質問・作業・設計など「思考を要する入力」",
        "",
        "【非推奨】",
        "雑談のみを延々と行う使い方（診断価値が出にくい）",
        "",
        "【説明の再確認】",
        "『説明』『使い方』『ヘルプ』でこの内容を再表示できます。"
    ])

def credit_status_text(user: Dict[str, Any]) -> str:
    """Generate credit status text (Spec 07 - corrected)"""
    plan = user.get("plan", "FREE")
    plan_config = PLANS.get(plan, PLANS["FREE"])
    
    lines = [
        f"プラン：{plan}",
        f"残クレジット：{user.get('credits', 0):,}クレジット"
    ]
    
    if plan == "FREE":
        # FREE: Initial grant only (Spec 07 - v0.8最終凍結版)
        lines.append("月額：0円")
        initial_grant = plan_config.get("initialGrant", 5000)  # Spec 07: 5,000クレジット
        if user.get("last_grant_yyyymm") == "INITIAL":
            lines.append(f"初回付与：{initial_grant:,}クレジット（初回のみ）")
        else:
            lines.append(f"初回付与：{initial_grant:,}クレジット（初回のみ・未付与）")
        lines.append("月次付与：なし")
    else:
        # STANDARD/PRO: Monthly grants (Spec 07 - v0.8最終凍結版)
        if plan == "STANDARD":
            lines.append("月額：4,000円（税込）")  # Spec 07: 税込表記
        elif plan == "PRO":
            lines.append("月額：8,000円（税込）")  # Spec 07: 8,000円（税込）
        grant = plan_config.get("monthlyGrant", 0)
        ym = yyyymm()
        granted_this_month = (user.get("last_grant_yyyymm") == ym)
        lines.append(f"月次付与：{grant:,}クレジット／月")
        if granted_this_month:
            lines.append("今月分の月次付与は反映済みです。")
        else:
            lines.append("今月分の月次付与は次回アクセス時に反映されます。")
    
    return "\n".join(lines)

def ability_list_text(lead: str) -> str:
    """Generate ability list text"""
    lines = [lead]
    for ability in ABILITIES:
        lines.append(f"{ability['id']}. {ability['name']}")
    return "\n".join(lines)

def run_diagnosis(user: Dict[str, Any]) -> str:
    """Run diagnosis (Spec 07 - v0.8最終凍結版)"""
    logs = db.get_observed_user_messages(user["user_id"], 10)
    
    # Check if enough logs (Spec 07 - 3-1: Maximum 10 logs)
    if len(logs) < 1:
        return "\n".join([
            "【診断】",
            "まだ観測ログが十分ではないため、今回の診断では確度の高い指摘ができません。",
            "通常会話を数往復した後、改めて『診断』を入力してください。",
            "",
            "（自動診断は行いません。診断したいタイミングでのみ実行します）"
        ])
    
    # Filter out commands and normalize (Spec 07 - 3-1: コマンド入力・システム応答を除外)
    observed_logs = []
    for log in logs:
        from api.utils import is_command
        if not is_command(log):
            normalized = log.strip()
            noise_patterns = ["ありがとう", "了解", "OK", "はい", "いいえ"]
            if normalized not in noise_patterns:
                observed_logs.append(normalized)
    
    # Spec 07 - 3-2: Check thinking load zone before calling OpenAI
    if len(observed_logs) < 1:
        return "\n".join([
            "【診断】",
            "診断対象となる観測ログが不足しています。",
            "",
            "診断が成立する入力例：",
            "・情報整理・比較・分解が必要な質問",
            "・判断・設計・仮説構築を要する作業依頼",
            "・思考を要する文章・指示・相談",
            "",
            "通常会話を数往復した後、改めて『診断』を入力してください。"
        ])
    
    load_zone = classify_thinking_load(observed_logs)
    if load_zone == "低負荷":
        # Spec 07 - 3-2: If low load zone, show guidance instead of error (no OpenAI call)
        return "\n".join([
            "【診断】",
            "現在の入力は主に低負荷（雑談・確認・単語のみ）のため、",
            "診断に適した思考パターンを観測できていません。",
            "",
            "診断が成立する入力例：",
            "・情報整理・比較・分解が必要な質問",
            "・判断・設計・仮説構築を要する作業依頼",
            "・思考を要する文章・指示・相談",
            "",
            "（非推奨でも拒否はしません。診断条件を満たす入力が増えたら再度『診断』を実行してください）"
        ])
    
    # Use OpenAI for proper diagnosis (Spec 07, Spec 09 追記㊿)
    # Spec 09 追記㊿: 診断におけるクレジット消費量（目安）約1,000クレジット相当
    cost_established = 1000
    if user.get("credits", 0) < cost_established:
        return "\n".join([
            "【診断】",
            "診断を実行するにはクレジットが不足しています。",
            f"必要：約{cost_established}クレジット、現在：{user.get('credits', 0)}クレジット",
            "",
            "選択肢：",
            "・追加購入：『購入』",
            "・プラン変更：『変更』"
        ])
    
    diagnosis_result = diagnose_with_openai(logs, user)
    
    # Check if diagnosis was non-established (Spec 07 - 3-2: 思考負荷ゾーン判定)
    # Spec 02 - ③: 診断不成立ケースの優先順位
    # Priority: ①低負荷 ②比較不能 ③判断不能 ④差分小 (only one reason returned)
    non_established_reason = None
    if "低負荷" in diagnosis_result or "低負荷が大半" in diagnosis_result or load_zone == "低負荷":
        non_established_reason = "低負荷"
    elif "比較不能" in diagnosis_result:
        non_established_reason = "比較不能"
    elif "判断不能" in diagnosis_result:
        non_established_reason = "判断不能"
    elif "差分小" in diagnosis_result or "顕著な偏りや欠損は見られません" in diagnosis_result:
        non_established_reason = "差分小"
    
    is_non_established = non_established_reason is not None
    
    if is_non_established:
        # Spec 09 追記㊿-1: 診断不成立時のクレジット消費ルール
        # Non-established: 0 credits (簡易説明文のみで1クレジット未満相当のため0扱い)
        cost = 0
    else:
        # Spec 09 追記㊿: 診断におけるクレジット消費量（目安）
        # Established: ~1,000クレジット相当
        cost = cost_established
    
    if cost > 0:
        user["credits"] = max(0, user["credits"] - cost)
        user["updated_at"] = now_iso()
        db.save_user(user)
        db.log_event(
            user["user_id"], "system", "credit_change", user["mode"],
            False, f"diagnosis_consume:{cost}", cost, {"reason": "diagnosis", "established": not is_non_established}
        )
    # Spec 09 追記㊿-1: If cost is 0, no credit consumption (診断できなかっただけでクレジットが減る体験を防止)
    
    return diagnosis_result

def diagnose_with_openai(logs: List[str], user: Dict[str, Any]) -> str:
    """Run diagnosis using OpenAI (Spec 07 - v0.8最終凍結版)"""
    from api.openai_client import call_openai
    from api.utils import safe_json
    
    # Filter out commands and normalize (Spec 02 - 6-3: ログ前処理)
    observed_logs = []
    for log in logs:
        # Skip if it's a command (Spec 02 - 4-3: 観測ログからの除外)
        from api.utils import is_command
        if not is_command(log):
            # Normalize noise (greetings, connectors) while preserving meaning
            normalized = log.strip()
            # Remove common noise patterns
            noise_patterns = ["ありがとう", "了解", "OK", "はい", "いいえ"]
            if normalized not in noise_patterns:
                observed_logs.append(normalized)
    
    if len(observed_logs) < 1:
        # Spec 07 - 3-2: Show guidance instead of error
        return "\n".join([
            "【診断】",
            "診断対象となる観測ログが不足しています。",
            "",
            "診断が成立する入力例：",
            "・情報整理・比較・分解が必要な質問",
            "・判断・設計・仮説構築を要する作業依頼",
            "・思考を要する文章・指示・相談",
            "",
            "通常会話を数往復した後、改めて『診断』を入力してください。"
        ])
    
    # Get last diagnosis for reference only (Spec 01 - 4-6)
    last_diagnosis = safe_json(user.get("last_diagnosis_json", "{}"))
    
    # Classify thinking load zones (Spec 01 - 4-7)
    load_zone = classify_thinking_load(observed_logs)
    
    # Build diagnosis prompt (Spec 01)
    system_prompt = "\n".join([
        "You are AIXEL's diagnosis engine. Analyze the user's AI usage logs to identify thinking ability patterns.",
        "",
        "Core principles:",
        "- Do NOT score, rank, or use numerical evaluation",
        "- Do NOT mention growth, improvement, or level-up",
        "- Focus on factual observation only",
        "- Identify which of 11 thinking abilities are being used",
        "- Classify abilities as: Not Used (contextually unnecessary) or 使う余地があったが使われていない能力 (should have been used)",
        "- Only report 使う余地があったが使われていない能力 (1-2 maximum)",
        "- Use Japanese terminology only (Spec 07 - 4-7: Missed Opportunity日本語表記)"
        "- Do NOT report Not Used abilities",
        "",
        "Thinking Load Zone: " + load_zone,
        "- Low load (低負荷): Small talk, confirmation, simple questions - if majority are low-load, diagnosis may be non-established (do not force missed opportunities)",
        "- Medium load (中負荷): Information organization, structuring, comparison, process design, problem breakdown",
        "- High load (高負荷): Judgment, decision-making, hypothesis building, meta-cognition, philosophy/policy design",
        "",
        "11 Thinking Abilities:",
        "1. 抽象化能力 (abstract) - Extract common patterns/principles",
        "2. 分解能力 (decompose) - Break down into tasks/elements",
        "3. 仕様言語化能力 (specify) - Convert vague requirements to specifications",
        "4. 文脈保持能力 (context) - Maintain premises/constraints consistently",
        "5. 問い生成能力 (question) - Generate good questions for information gathering",
        "6. 仮説構築能力 (hypothesis) - Form testable hypotheses",
        "7. 思考の一時停止能力 (pause) - Recognize when to pause judgment",
        "8. メタ認知能力 (metacog) - Objectify own thinking patterns/biases",
        "9. 捨てる能力 (discard) - Cut unnecessary elements to simplify",
        "10. 判断基準保持能力 (criteria) - Maintain consistent judgment criteria",
        "11. 再利用設計能力 (reuse) - Convert results to reusable templates/rules",
        "",
        "Previous diagnosis (reference only, not binding):",
        str(last_diagnosis) if last_diagnosis else "None",
        "",
        "Output format (in Japanese, adapt language level to user's conversation level):",
        "1. 事実ベースの観測 (Factual observation - no evaluation words, adjust language complexity)",
        "2. 使う余地があったが使われていない能力 (1-2 maximum, Japanese only - Spec 07)",
        "3. 提案型・一言改善案 (2-3 suggestions, no commands/assertions)",
        "",
        "強み（最も使われている能力）の提示ルール (Spec 01 - ④, Spec 02 - ④):",
        "- 強みは、使う余地があったが使われていない能力が存在する場合の補助情報としてのみ表示可",
        "- 強みのみの単独表示は禁止（不足なし＋強みだけは行わない）",
        "- 使う余地があったが使われていない能力がない場合は、強みも表示しない",
        "",
        "Do NOT force 使う余地があったが使われていない能力 if they don't exist.",
        "Do NOT use templates - generate fresh expressions each time."
    ])
    
    user_prompt = "\n".join([
        "以下のユーザーのAI使用ログを分析してください：",
        "",
        "\n".join([f"{i+1}. {log}" for i, log in enumerate(observed_logs[-10:])]),
        "",
        "診断結果を出力してください。"
    ])
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    result = call_openai(messages)
    
    if not result:
        # Fallback to heuristic if OpenAI fails
        analysis = diagnose_heuristic(observed_logs)
        return format_diagnosis_result(analysis, len(observed_logs), user)
    
    # Store diagnosis result for reference (Spec 01 - 4-6)
    diagnosis_data = {
        "timestamp": now_iso(),
        "log_count": len(observed_logs),
        "load_zone": load_zone,
        "result_summary": result[:200]  # Store summary only
    }
    user["last_diagnosis_json"] = json.dumps(diagnosis_data, ensure_ascii=False)
    user["updated_at"] = now_iso()
    db.save_user(user)
    
    # Format the result
    return "\n".join([
        "【診断】",
        f"対象：直近{min(10, len(observed_logs))}件の入力（観測ログ）",
        "",
        result,
        "",
        "必要なら：『トレーニング』で任意の能力を選んで練習できます。"
    ])

def classify_thinking_load(logs: List[str]) -> str:
    """Classify thinking load zone (Spec 02 - 6-4: 思考負荷ゾーン判定)
    
    Spec 01 - ③: 思考負荷ゾーン分類の判定主体
    - 診断対象ログ全体を俯瞰した総合判定とする
    - 単発の低負荷発話が混在しても、中〜高負荷が成立していれば診断可とする
    """
    if not logs:
        return "低負荷"
    
    # Spec 02 - 6-4: More precise classification
    # Spec 01 - ③: Comprehensive judgment of all diagnostic target logs (not single messages)
    low_load_keywords = ["ありがとう", "了解", "OK", "はい", "いいえ", "確認", "雑談", "教えて", "？", "?"]
    medium_load_keywords = ["整理", "構造", "比較", "手順", "設計", "問題", "切り分け", "分析"]
    high_load_keywords = ["判断", "意思決定", "仮説", "検証", "思想", "哲学", "メタ", "前提", "方針", "戦略"]
    
    text = " ".join(logs).lower()
    
    low_count = sum(1 for kw in low_load_keywords if kw in text)
    medium_count = sum(1 for kw in medium_load_keywords if kw in text)
    high_count = sum(1 for kw in high_load_keywords if kw in text)
    
    # Spec 02 - 6-4: Low load if majority are low-load conversations
    total_keywords = low_count + medium_count + high_count
    if total_keywords > 0 and low_count / total_keywords > 0.6:
        return "低負荷"
    
    if high_count >= 2:
        return "高負荷"
    elif medium_count >= 2:
        return "中負荷"
    elif low_count >= 3 or len(text) < 50:
        return "低負荷"
    else:
        return "中負荷"

def format_diagnosis_result(analysis: Dict[str, Any], log_count: int, user: Dict[str, Any]) -> str:
    """Format diagnosis result from heuristic analysis
    Spec 01 - ④, Spec 02 - ④: 強み提示条件
    - 強みは、使う余地があったが使われていない能力が存在する場合の補助情報としてのみ表示可
    - 強みのみの単独表示は禁止（不足なし＋強みだけは行わない）
    """
    strongest_name = next(
        (a["name"] for a in ABILITIES if a["key"] == analysis["strongest"]),
        "（判定不能）"
    )
    
    if not analysis.get("missed"):
        # Spec 01 - ④, Spec 02 - ④: No strength display when no missed opportunities
        return "\n".join([
            "【診断】",
            f"対象：直近{min(10, log_count)}件の入力（観測ログ）",
            "",
            "今回、顕著な偏りや欠損は見られません。",
            "（この場合、改善案やトレーニング案内は出しません）"
        ])
    
    missed_names = [
        next((a["name"] for a in ABILITIES if a["key"] == k), None)
        for k in analysis["missed"]
    ]
    missed_names = [n for n in missed_names if n]
    
    impact_lead = random_choice([
        "このままだと起こりやすいのは、",
        "放置すると発生しやすいのは、",
        "影響として出やすいのは、"
    ])
    
    # Spec 01 - ④, Spec 02 - ④: Show strength only as supplementary info when missed opportunities exist
    return "\n".join([
        "【診断】",
        f"対象：直近{min(10, log_count)}件の入力（観測ログ）",
        "",
        "使う余地があったが使われていない能力（1〜2件）：",
        "\n".join(f"- {n}" for n in missed_names),
        "",
        f"最も使われている思考能力（補助情報）：{strongest_name}",
        "",
        "観測した事実（短く）：",
        "\n".join(f"- {f}" for f in analysis["facts"]),
        "",
        f"{impact_lead}{analysis['impact']}",
        "",
        "改善の選択肢（押し付けず提案）：",
        "\n".join(f"- {s}" for s in analysis["suggestions"]),
        "",
        "必要なら：『トレーニング』で任意の能力を選んで練習できます。"
    ])

def diagnose_heuristic(logs: List[str]) -> Dict[str, Any]:
    """Heuristic diagnosis (can be replaced with API call)"""
    score = {
        "abstract": 0, "decompose": 0, "specify": 0, "context": 0,
        "question": 0, "hypothesis": 0, "pause": 0, "metacog": 0,
        "discard": 0, "criteria": 0, "reuse": 0
    }
    
    facts = []
    triggers = {
        "needsDecompose": False,
        "needsSpecify": False,
        "needsCriteria": False,
        "needsReuse": False,
        "needsHypothesis": False
    }
    
    for text in logs:
        s = str(text or "")
        
        # Scoring (simplified)
        if any(kw in s for kw in ["要点", "本質", "抽象", "共通", "原理", "パターン"]):
            score["abstract"] += 2
        if any(kw in s for kw in ["分解", "手順", "ステップ", "タスク", "チェックリスト", "順番", "依存"]):
            score["decompose"] += 2
        if any(kw in s for kw in ["仕様", "要件", "入力", "出力", "例外", "禁止", "定義", "固定"]):
            score["specify"] += 2
        if any(kw in s for kw in ["前提", "制約", "決定", "矛盾", "整合", "引き継ぎ"]):
            score["context"] += 2
        if "？" in s or "?" in s or any(kw in s for kw in ["質問", "確認"]):
            score["question"] += 1
        if any(kw in s for kw in ["仮説", "原因", "検証", "可能性"]):
            score["hypothesis"] += 2
        if any(kw in s for kw in ["保留", "一旦", "止める", "あとで"]):
            score["pause"] += 1
        if any(kw in s for kw in ["自分", "癖", "バイアス", "思い込み", "俯瞰", "メタ"]):
            score["metacog"] += 2
        if any(kw in s for kw in ["捨て", "削る", "後回し", "スコープ", "最小", "MVP"]):
            score["discard"] += 2
        if any(kw in s for kw in ["基準", "判断", "優先", "比較", "トレードオフ"]):
            score["criteria"] += 2
        if any(kw in s for kw in ["テンプレ", "再利用", "型", "仕組み化", "チェックリスト化"]):
            score["reuse"] += 2
        
        # Triggers
        if any(kw in s for kw in ["やり方", "手順", "進め方", "実装", "タスク"]):
            triggers["needsDecompose"] = True
        if any(kw in s for kw in ["仕様", "要件", "どこに書く", "どう実装"]):
            triggers["needsSpecify"] = True
        if any(kw in s for kw in ["どっち", "比較", "決める", "方針"]):
            triggers["needsCriteria"] = True
        if any(kw in s for kw in ["毎回", "繰り返し", "引き継ぎ", "テンプレ", "仕組み"]):
            triggers["needsReuse"] = True
        if any(kw in s for kw in ["原因", "バグ", "おかしい", "破綻"]):
            triggers["needsHypothesis"] = True
    
    # Find strongest
    strongest = "context"
    best = -1
    for k, v in score.items():
        if v > best:
            best = v
            strongest = k
    
    # Find missed opportunities
    candidates = []
    if triggers["needsDecompose"]:
        candidates.append("decompose")
    if triggers["needsSpecify"]:
        candidates.append("specify")
    if triggers["needsCriteria"]:
        candidates.append("criteria")
    if triggers["needsReuse"]:
        candidates.append("reuse")
    if triggers["needsHypothesis"]:
        candidates.append("hypothesis")
    
    candidates.sort(key=lambda x: score[x])
    missed = []
    for c in candidates:
        if c == strongest:
            continue
        if c in missed:
            continue
        if score[c] <= 1:
            missed.append(c)
        if len(missed) >= 2:
            break
    
    # Facts
    if score["context"] > 0:
        facts.append("前提・制約・決定事項に触れる入力が複数回あった")
    if score["specify"] > 0:
        facts.append("仕様/実装への言及が複数回あった")
    if score["decompose"] > 0:
        facts.append("手順/分解の話題が出ていた")
    if score["criteria"] > 0:
        facts.append("比較/判断の話題が出ていた")
    if not facts:
        facts.append("短文中心で、文脈からの確度が限定的")
    
    # Impact and suggestions
    impact = "影響は限定的です。"
    if "decompose" in missed:
        impact = "次の一手が曖昧になり、実装や運用の「迷子」が再発しやすくなります。"
    elif "specify" in missed:
        impact = "仕様が曖昧なまま進み、同じ修正が繰り返されやすくなります。"
    elif "criteria" in missed:
        impact = "意思決定が状況で揺れ、判断のやり直しが増えやすくなります。"
    elif "reuse" in missed:
        impact = "毎回ゼロから考える比率が増え、負荷が積み上がりやすくなります。"
    elif "hypothesis" in missed:
        impact = "原因探索が広がりすぎて、検証コストが増えやすくなります。"
    
    suggestions = []
    for m in missed:
        if m == "decompose":
            suggestions.append("ゴール→最小タスク→順番（依存）までを10行以内で書いてみる")
        elif m == "specify":
            suggestions.append("曖昧語を3つだけ潰し、入力/出力/例外/禁止を1回だけ固定する")
        elif m == "criteria":
            suggestions.append("判断基準を3つに固定し、優先順位も一言で添える")
        elif m == "reuse":
            suggestions.append("今回の結論を、次回も使える「見出し固定」の形にする")
        elif m == "hypothesis":
            suggestions.append("原因仮説を3つに絞り、検証コスト順に並べる")
    
    return {
        "strongest": strongest,
        "missed": missed,
        "facts": facts,
        "impact": impact,
        "suggestions": suggestions
    }

def run_normal_chat(user: Dict[str, Any], user_text: str) -> str:
    """Run normal chat with OpenAI"""
    system = "\n".join([
        "You are AIXEL, a conversational assistant.",
        "Core philosophy:",
        "- Do not auto-diagnose, do not score, do not rank, do not mention 'level up' or growth theatrics.",
        "- Do not force training, do not push recommendations. User keeps decision rights.",
        "- Normal conversation should be natural and helpful like ChatGPT, but avoid coercive tone.",
        "- If the user asks for diagnosis, they will use the exact command '診断'. Otherwise do not analyze their thinking abilities.",
        "- If the user asks for training, they will use 'トレーニング'. Otherwise do not start training."
    ])
    
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text}
    ]
    
    reply = call_openai(messages)
    return reply or "（応答生成に失敗しました。設定（OPENAI_API_KEY）を確認してください）"

def handle_oneshot_start(user: Dict[str, Any]) -> str:
    """Handle oneshot experience start (Spec 04 - ワンショット思考点検)"""
    # Spec 04 - 5-2: Check if already used
    if user.get("oneshot_experience_used", False):
        # Spec 04 - 5-3: Re-purchase prevention message
        return "\n".join([
            "この体験は、",
            "1人1回限りの思考点検として設計されています。",
            "すでにご利用済みのため、再購入はできません。"
        ])
    
    # Start purchase flow
    user["mode"] = MODE["ONESHOT_EXPERIENCE"]
    user["mode_started_at"] = now_iso()
    user["tmp_json"] = '{"step":"purchase"}'
    user["updated_at"] = now_iso()
    db.save_user(user)
    
    # Spec 04 - 4-1: Price display (tax-excluded/tax-inclusive)
    price_ex_tax = 1000
    price_in_tax = int(price_ex_tax * (1 + TAX_RATE))
    
    return "\n".join([
        "ワンショット思考点検（1000円体験）",
        "",
        f"価格：{price_ex_tax:,}円（税抜）／{price_in_tax:,}円（税込）",
        "回数：1回完結",
        "",
        "購入を確定する場合は「購入する」と入力してください。",
        "（βでは外部決済連携は未接続想定のため、ここでは(購入完了)として処理します。後で外部決済に差し替え可能です）"
    ])

def handle_oneshot_purchase(user: Dict[str, Any], text: str) -> str:
    """Handle oneshot purchase confirmation (Spec 04)"""
    from api.utils import safe_json
    
    tmp = safe_json(user.get("tmp_json", "{}"))
    if tmp.get("step") != "purchase":
        user["mode"] = MODE["IDLE"]
        user["updated_at"] = now_iso()
        db.save_user(user)
        return "状態が不整合だったため、通常モードに戻しました。"
    
    # Check if user confirmed purchase
    if text.strip() not in ["購入する", "する", "はい", "OK"]:
        # Cancel - return to idle
        user["mode"] = MODE["IDLE"]
        user["mode_started_at"] = now_iso()
        user["tmp_json"] = "{}"
        user["updated_at"] = now_iso()
        db.save_user(user)
        return "Idle（通常モード）に戻りました。"
    
    # Purchase confirmed - mark as used and request input
    user["oneshot_experience_used"] = True
    user["tmp_json"] = '{"step":"input"}'
    user["updated_at"] = now_iso()
    db.save_user(user)
    
    # Log purchase (Spec 04 - 4-1: 1,000円税抜)
    price_ex_tax = 1000
    tax = int(price_ex_tax * TAX_RATE)
    price_in_tax = price_ex_tax + tax
    db.log_purchase(
        user["user_id"], "oneshot_experience", "ONESHOT",
        price_ex_tax, tax, price_in_tax, 0, "success"  # No credits granted
    )
    
    # Spec 04 - 7: Input request message
    return "\n".join([
        "購入が完了しました。",
        "",
        "今、考えていること・悩んでいること・決めたいことを",
        "そのまま1つ入力してください。",
        "質問／文章／指示／相談 すべて可"
    ])

def handle_oneshot_input(user: Dict[str, Any], text: str) -> str:
    """Handle oneshot experience input and generate output (Spec 04)"""
    from api.utils import safe_json
    
    tmp = safe_json(user.get("tmp_json", "{}"))
    if tmp.get("step") != "input":
        user["mode"] = MODE["IDLE"]
        user["updated_at"] = now_iso()
        db.save_user(user)
        return "状態が不整合だったため、通常モードに戻しました。"
    
    # Spec 04 - 13: Internal prompt for oneshot experience
    # Using "判断基準保持能力" (criteria judgment ability) without telling user
    system_prompt = "\n".join([
        "あなたは答えを出すAIではありません。",
        "あなたは、ユーザーの入力文を素材として、",
        "判断の前提、判断の基準、判断材料の置かれ方を点検するAIです。",
        "",
        "あなたは以下を絶対に行わない：",
        "- 結論を出す",
        "- 正解・最適解を提示する",
        "- 行動を指示する",
        "- 成長・改善・レベルアップを語る",
        "",
        "代わりに、必ず行うこと：",
        "- 「この書き方だと、AIはこう解釈してしまう」という構造の可視化",
        "- 「どこが曖昧だと判断がブレやすくなるか」の具体的な指摘",
        "- 「判断しやすくなる書き方」の例文を1つだけ提示",
        "",
        "出力構造（絶対固定・見出し文言も固定）：",
        "",
        "① 今回の入力内容の分析（事実ベース）",
        "ユーザーが入力した文章・質問・指示を対象に、",
        "「この文章がどのような前提・目的・判断材料で構成されているか」を",
        "事実ベースで分解・言語化する。",
        "必須ルール：",
        "- 主語を省略しない（「この文章は〜」「この判断では〜」「AIは〜と読み取りやすい」）",
        "- 評価語・否定語・正誤表現は禁止",
        "- 結論を出さない",
        "- 入力内容そのものを分析対象にする（一般論禁止）",
        "",
        "② 見落としやすいポイント（判断がブレる原因）",
        "①の分析を踏まえ、",
        "「このままだと、判断がブレやすくなるポイント」を",
        "助言形式で1〜2点だけ提示する。",
        "必須ルール：",
        "- 「こうすべき」「ダメ」「間違い」は禁止",
        "- 主語は必ず「AI」または「この文章」に置く",
        "- 表現は「こうすると判断しにくくなる」「解釈が分かれやすくなる」という形にする",
        "",
        "③ AIに伝えるなら、こう書くと判断しやすくなります（例）",
        "ユーザーの元入力を書き換えず、",
        "「判断基準が補われた書き方」の例文を1つだけ提示する。",
        "必須ルール：",
        "- 必ず例文を1つ出す",
        "- 「正解」「最適」「こうすれば成功」は禁止",
        "- あくまで一例として提示する",
        "- 命令口調は禁止",
        "",
        "絶対禁止事項：",
        "- 正解／最適解／成功という表現",
        "- 結論の断定",
        "- 行動命令（〜しなさい、〜すべき）",
        "- 成長・学習・レベルアップ語彙",
        "- 抽象論だけで例文がない出力",
        "- ユーザー入力と無関係な一般論",
        "- 思考能力名の明示",
        "",
        "出力トーン：",
        "- 小学生でも意味が分かる日本語",
        "- 1文は短く",
        "- 主語を必ず書く",
        "- 専門用語を使わない",
        "- 上から目線・説教口調は禁止"
    ])
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text}
    ]
    
    result = call_openai(messages)
    if not result:
        # Fallback if OpenAI fails
        result = "\n".join([
            "① 今回の入力内容の分析（事実ベース）",
            "この文章では、目的や判断基準が読み取れます。",
            "",
            "② 見落としやすいポイント（判断がブレる原因）",
            "判断基準が書かれていないため、AIは優先順位を決めにくくなります。",
            "",
            "③ AIに伝えるなら、こう書くと判断しやすくなります（例）",
            "例えば、目的と判断基準を明示すると、AIは迷いにくくなります。"
        ])
    
    # Spec 04 - 12: End declaration and return to Idle
    user["mode"] = MODE["IDLE"]
    user["mode_started_at"] = now_iso()
    user["tmp_json"] = "{}"
    user["updated_at"] = now_iso()
    db.save_user(user)
    
    return "\n".join([
        result,
        "",
        "以上で今回の点検は終了です。",
        "このまま通常の利用に戻ります。"
    ])
