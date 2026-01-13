"""
Command handlers and business logic
"""
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
    """Ensure monthly grant is given if not yet this month (Spec 07 - corrected)
    FREE: Initial 5,000 credits only (once at registration)
    STANDARD/PRO: Monthly grants
    """
    plan = user.get("plan", "FREE")
    plan_config = PLANS.get(plan, PLANS["FREE"])
    
    # FREE plan: Initial grant only (once)
    if plan == "FREE":
        # Check if initial grant was given
        if user.get("credits", 0) == 0 and not user.get("last_grant_yyyymm"):
            amount = plan_config.get("initialGrant", 5000)
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
    """Generate ability explanation content (Spec 02, Spec 08 - plan-based granularity)"""
    ability = next((a for a in ABILITIES if a["id"] == ability_id), None)
    if not ability:
        return "不明な能力です。"
    
    # Complete ability definitions (Spec 02, Spec 06)
    defs = {
        "abstract": {
            "def": "具体例・現象から「共通構造（パターン）」を抜き出し、一般化して扱う能力。",
            "effect": "AIに汎用プロンプト設計、再利用テンプレの作成、戦略の型化をさせるのに効きます。",
            "timing": ["話が散らかってきた時", "複数の事例をまとめたい時", "方針を一言で固定したい時"],
            "prompts": [
                "この状況を「パターン」として抽象化して。再利用できる形にして。",
                "具体例3つから共通原理を1つにまとめて。",
                "今の内容を『再利用できるルール』に言い換えて"
            ]
        },
        "decompose": {
            "def": "目的・問題を要素（タスク／論点／前提）に分け、順序・依存関係を作る能力。",
            "effect": "AIに実装タスク分割、仕様分割、障害切り分けをさせる時に効きます。",
            "timing": ["やることが曖昧で止まっている時", "仕様や作業が重い時", "最短ルートを作りたい時"],
            "prompts": [
                "このゴールを最小タスクに分解して、依存関係付きで並べて。",
                "抜け漏れが出ないチェックリストにして。",
                "原因候補をMECEで切り分けて、検証順を出して。"
            ]
        },
        "specify": {
            "def": "曖昧な要求を、条件・禁止・例外・入出力・境界として文章化する能力。",
            "effect": "AIに仕様書化、受け渡し、テスト観点化をさせる時に効きます。",
            "timing": ["実装が迷う時", "要件が曖昧な時", "境界が不明な時"],
            "prompts": [
                "この要件を「定義／入出力／例外／禁止／状態遷移」で仕様化して。",
                "曖昧語を列挙して、置換案（定義）を作って。"
            ]
        },
        "context": {
            "def": "会話・設計の前提、決定事項、制約を保持し、矛盾なく積み上げる能力。",
            "effect": "AIに長期プロジェクトの破綻防止、統合仕様の維持をさせる時に効きます。",
            "timing": ["前提がズレそうな時", "決定事項を確認したい時", "矛盾を防ぎたい時"],
            "prompts": [
                "いまの提案が既決事項と矛盾する箇所を検出して。",
                "前提・制約・決定事項だけを箇条書きで抽出して。"
            ]
        },
        "question": {
            "def": "次に必要な情報／判断材料を得るために、良い質問を作る能力。",
            "effect": "AIに要件定義、ユーザー調査、設計レビューをさせる時に効きます。",
            "timing": ["不明点がある時", "確認が必要な時", "情報が足りない時"],
            "prompts": [
                "この要件を確定するために必要な質問を5つ作って。",
                "失敗を減らすために先に確認すべき前提は？"
            ]
        },
        "hypothesis": {
            "def": "不確実な状況で、原因・解決策・結果の仮説を立て、検証可能にする能力。",
            "effect": "AIにバグ原因推定、集客改善、施策検証をさせる時に効きます。",
            "timing": ["原因が不明な時", "検証が必要な時", "仮説を立てたい時"],
            "prompts": [
                "起きている問題の原因仮説を3つ出し、検証方法も付けて。",
                "この施策が失敗する仮説（逆仮説）も出して。"
            ]
        },
        "pause": {
            "def": "結論を急がず、判断保留・情報不足を認め、探索フェーズを設ける能力。",
            "effect": "AIに仕様凍結判断、優先順位付け、リスク低減をさせる時に効きます。",
            "timing": ["情報が足りない時", "判断を保留したい時", "探索が必要な時"],
            "prompts": [
                "今は決めるには情報不足。追加で必要な情報と集め方を出して。",
                "この判断を保留する場合の最小安全策は？"
            ]
        },
        "metacog": {
            "def": "自分の思考の癖・前提・感情の影響を「対象化」して扱う能力。",
            "effect": "AIに意思決定の質改善、共進化、学習設計をさせる時に効きます。",
            "timing": ["同じパターンが繰り返される時", "バイアスを確認したい時", "俯瞰したい時"],
            "prompts": [
                "いまの私の前提・バイアス候補を列挙して。",
                "この発言の狙いは何？別の見方は？"
            ]
        },
        "discard": {
            "def": "選択肢を増やすだけでなく、不要な案・機能・論点を切り捨ててシンプルにする能力。",
            "effect": "AIにMVP設計、仕様凍結、工数削減をさせる時に効きます。",
            "timing": ["仕様が肥大化している時", "優先順位を付けたい時", "シンプルにしたい時"],
            "prompts": [
                "この機能群を「捨てる前提」でMVPに落として。",
                "削るべき論点を優先度で並べて。"
            ]
        },
        "criteria": {
            "def": "意思決定の評価軸（思想・制約・ゴール）を保持し、ブレずに選ぶ能力。",
            "effect": "AIに仕様一貫性、ブランド一貫性、価格設計をさせる時に効きます。",
            "timing": ["判断基準を固定したい時", "一貫性を保ちたい時", "選択肢を評価したい時"],
            "prompts": [
                "この選択肢を「思想制約」に照らして可否判定して。",
                "判断基準を3つに固定して、以後それで評価して。"
            ]
        },
        "reuse": {
            "def": "一度作った思考・仕様・成果を、次回以降も使える形（テンプレ・ルール・資産）にする能力。",
            "effect": "AIに社内運用、SOP、教育コンテンツ化をさせる時に効きます。",
            "timing": ["毎回同じことを繰り返す時", "再利用したい時", "資産化したい時"],
            "prompts": [
                "この結論を再利用できるチェックリストにして。",
                "次回も使える「入力テンプレ／出力テンプレ／判断フロー」に変換して。"
            ]
        }
    }
    
    ability_def = defs.get(ability["key"], {
        "def": "(定義未設定)",
        "effect": "",
        "timing": [],
        "prompts": []
    })
    
    # Plan-based granularity (Spec 08)
    tier = "PRO" if plan == "PRO" else ("STANDARD" if plan == "STANDARD" else "FREE")
    
    # Build output with plan-based granularity
    lines = []
    
    # Block 1: Definition (1-2 sentences for FREE, 2-4 for STANDARD, 4-6 for PRO)
    lines.append(f"①定義")
    if tier == "FREE":
        lines.append(ability_def["def"])
    elif tier == "STANDARD":
        lines.append(ability_def["def"])
        lines.append(f"（{ability_def.get('effect', '')}）")
    else:  # PRO
        lines.append(ability_def["def"])
        lines.append(f"（{ability_def.get('effect', '')}）")
        lines.append("この能力は、AIに渡す入力の設計精度を上げる方向で効きます。")
    
    # Block 2: Effect/Timing (plan-based)
    lines.append(f"\n②使うタイミング")
    if tier == "FREE":
        if ability_def.get("timing"):
            lines.append(ability_def["timing"][0] if ability_def["timing"] else "")
    elif tier == "STANDARD":
        if ability_def.get("timing"):
            lines.append(" / ".join(ability_def["timing"][:2]))
    else:  # PRO
        if ability_def.get("timing"):
            lines.append(" / ".join(ability_def["timing"]))
    
    # Block 3: Prompt examples (plan-based count)
    lines.append(f"\n③プロンプト例")
    if ability_def.get("prompts"):
        prompt_count = 1 if tier == "FREE" else (2 if tier == "STANDARD" else 3)
        prompts = ability_def["prompts"][:prompt_count]
        for p in prompts:
            lines.append(f"- {p}")
    
    # Block 4: Additional context (PRO only)
    if tier == "PRO":
        lines.append(f"\n④補足")
        if ability["key"] == "specify":
            lines.append("使える形にするコツは「(1)前提固定 → (2)制約明示 → (3)出力形式指定 → (4)反例/例外」をセットで投げることです。")
        elif ability["key"] == "reuse":
            lines.append("再利用設計は「型」を体験させるものであり、自動的に永続保存するとユーザーの資産管理や正解集化につながります。")
    
    return "\n".join(lines)

def help_content() -> str:
    """Help content (Spec 02)"""
    return "\n".join([
        "AIXELは「答えを押し付けるAI」ではなく、あなたの思考を観測し、必要な時だけ改善の選択肢を提示する「思考トレーナー」です。",
        "",
        "【普段】通常会話はできます（内部では観測ログを溜めます）。自動で診断や指摘はしません。",
        "",
        "【診断】実行したいタイミングで、コマンド『診断』と入力してください。",
        "",
        "【トレーニング】任意です。コマンド『トレーニング』→能力番号で開始します（開始後は完了まで誘導します）。",
        "",
        "【能力解説】コマンド『能力解説』→能力番号で各能力の説明を表示します。",
        "",
        "【クレジット】1クレジット＝1トークン。すべてのAI応答で消費されます。無制限・使い放題は採用しません。",
        "残量確認：『クレジット』／プラン変更：『変更』／追加購入：『購入』",
        "",
        "【推奨利用】質問・作業・設計など「思考を要する入力」",
        "【非推奨】雑談のみを延々と行う使い方（診断価値が出にくい）",
        "",
        "【サポート】技術的問題・課金関連・不具合の問い合わせ：『サポート』または『問い合わせ』"
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
        # FREE: Initial grant only (Spec 07)
        initial_grant = plan_config.get("initialGrant", 5000)
        if user.get("last_grant_yyyymm") == "INITIAL":
            lines.append(f"初回付与：{initial_grant:,}クレジット（1回のみ）")
        else:
            lines.append(f"初回付与：{initial_grant:,}クレジット（1回のみ・未付与）")
    else:
        # STANDARD/PRO: Monthly grants
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
    """Run diagnosis (Spec 02, Spec 07 - proper OpenAI-based diagnosis)"""
    logs = db.get_observed_user_messages(user["user_id"], 10)
    
    # Check if enough logs (7-10 variable, no minimum required - Spec 01, 02)
    if len(logs) < 1:
        return "\n".join([
            "【診断】",
            "まだ観測ログが十分ではないため、今回の診断では確度の高い指摘ができません。",
            "通常会話を数往復した後、改めて『診断』を入力してください。",
            "",
            "（自動診断は行いません。診断したいタイミングでのみ実行します）"
        ])
    
    # Use OpenAI for proper diagnosis (Spec 02, Spec 07)
    # Check credits first (need ~1000 for established diagnosis)
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
    
    # Check if diagnosis was non-established (Spec 09 - 0 credits if <1 credit equivalent)
    # For now, we'll consume credits after diagnosis. In full implementation,
    # we'd check the result first and consume 0 if non-established
    is_non_established = any(keyword in diagnosis_result for keyword in [
        "顕著な偏りや欠損は見られません",
        "診断では確度の高い指摘ができません",
        "観測ログが不足",
        "低負荷", "比較不能", "差分小", "判断不能"
    ])
    
    if is_non_established:
        # Non-established: 0 credits (Spec 09)
        cost = 0
    else:
        # Established: ~1000 credits (Spec 09)
        cost = cost_established
    
    if cost > 0:
        user["credits"] = max(0, user["credits"] - cost)
        user["updated_at"] = now_iso()
        db.save_user(user)
        db.log_event(
            user["user_id"], "system", "credit_change", user["mode"],
            False, f"diagnosis_consume:{cost}", cost, {"reason": "diagnosis", "established": not is_non_established}
        )
    # If cost is 0, no credit consumption (Spec 09)
    
    return diagnosis_result

def diagnose_with_openai(logs: List[str], user: Dict[str, Any]) -> str:
    """Run diagnosis using OpenAI (Spec 02, Spec 07)"""
    from api.openai_client import call_openai
    
    # Filter out commands and normalize (Spec 02, Spec 07)
    observed_logs = []
    for log in logs:
        # Skip if it's a command
        from api.utils import is_command
        if not is_command(log):
            observed_logs.append(log)
    
    if len(observed_logs) < 1:
        return "\n".join([
            "【診断】",
            "診断対象となる観測ログが不足しています。",
            "通常会話を数往復した後、改めて『診断』を入力してください。"
        ])
    
    # Build diagnosis prompt (Spec 02)
    system_prompt = "\n".join([
        "You are AIXEL's diagnosis engine. Analyze the user's AI usage logs to identify thinking ability patterns.",
        "",
        "Core principles:",
        "- Do NOT score, rank, or use numerical evaluation",
        "- Do NOT mention growth, improvement, or level-up",
        "- Focus on factual observation only",
        "- Identify which of 11 thinking abilities are being used",
        "- Identify which abilities had opportunity but were not used (Missed Opportunity)",
        "- Maximum 2 abilities in output (1-2 missed opportunities)",
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
        "Output format (in Japanese):",
        "1. 事実ベースの観測 (Factual observation - no evaluation words)",
        "2. 該当する思考能力名 (Ability names being used)",
        "3. 使う余地があったが使われていない能力 (1-2 abilities maximum)",
        "4. 提案型・一言改善案 (2-3 suggestions, no commands/assertions)",
        "",
        "If no missed opportunities, only show the strongest ability being used.",
        "Do NOT force missed opportunities if they don't exist."
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
        return format_diagnosis_result(analysis, len(observed_logs))
    
    # Format the result
    return "\n".join([
        "【診断】",
        f"対象：直近{min(10, len(observed_logs))}件の入力（観測ログ）",
        "",
        result,
        "",
        "必要なら：『トレーニング』で任意の能力を選んで練習できます。"
    ])

def format_diagnosis_result(analysis: Dict[str, Any], log_count: int) -> str:
    """Format diagnosis result from heuristic analysis"""
    strongest_name = next(
        (a["name"] for a in ABILITIES if a["key"] == analysis["strongest"]),
        "（判定不能）"
    )
    
    if not analysis.get("missed"):
        return "\n".join([
            "【診断】",
            f"対象：直近{min(10, log_count)}件の入力（観測ログ）",
            "",
            f"最も使われている思考能力（事実ベース）：{strongest_name}",
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
    
    return "\n".join([
        "【診断】",
        f"対象：直近{min(10, log_count)}件の入力（観測ログ）",
        "",
        f"最も使われている思考能力（事実ベース）：{strongest_name}",
        "",
        "使う余地があったが使われていない能力（1〜2件）：",
        "\n".join(f"- {n}" for n in missed_names),
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
