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
    """Ensure monthly grant is given if not yet this month"""
    ym = yyyymm()
    if user["last_grant_yyyymm"] == ym:
        return {"granted": False, "amount": 0}
    
    plan = user.get("plan", "FREE")
    plan_config = PLANS.get(plan, PLANS["FREE"])
    amount = plan_config.get("monthlyGrant", 0)
    
    user["credits"] = (user.get("credits", 0) or 0) + amount
    user["last_grant_yyyymm"] = ym
    user["updated_at"] = now_iso()
    db.save_user(user)
    
    db.log_event(
        user["user_id"], "system", "credit_change", user["mode"],
        False, f"monthly_grant:{amount}", amount, {"ym": ym, "plan": plan}
    )
    
    return {"granted": True, "amount": amount}

def ability_explain_content(ability_id: int, plan: str) -> str:
    """Generate ability explanation content"""
    ability = next((a for a in ABILITIES if a["id"] == ability_id), None)
    if not ability:
        return "不明な能力です。"
    
    # Ability definitions (simplified from GAS version)
    defs = {
        "abstract": {
            "def": "個別の話から共通ルール（本質）を抜き出して、別の場面でも使える形にする力。",
            "effect": "AIに『要点・共通点・原理』を抽出させたり、方針のブレを防ぐのに効きます。",
            "timing": ["話が散らかってきた時", "複数の事例をまとめたい時", "方針を一言で固定したい時"],
            "prompts": [
                "この話を一段抽象化して「原理」にすると何？",
                "複数の例に共通するパターンを抜き出して",
                "今の内容を『再利用できるルール』に言い換えて"
            ]
        },
        "decompose": {
            "def": "大きい課題を「作業できる粒度」まで切り分け、順番と依存関係を作る力。",
            "effect": "AIにタスク分解・手順化・抜け漏れチェックをさせる時に効きます。",
            "timing": ["やることが曖昧で止まっている時", "仕様や作業が重い時", "最短ルートを作りたい時"],
            "prompts": [
                "このゴールを最小タスクに分解して、順番も付けて",
                "抜け漏れが出ないチェックリストにして",
                "依存関係（先に必要なもの）も含めて分解して"
            ]
        }
        # Add other abilities as needed...
    }
    
    ability_def = defs.get(ability["key"], {
        "def": "(定義未設定)",
        "effect": "",
        "timing": [],
        "prompts": []
    })
    
    tier = "PRO" if plan == "PRO" else ("STANDARD" if plan == "STANDARD" else "FREE")
    
    extra = ""
    if tier == "STANDARD":
        extra = "\n補足：この能力は「出力の質」というより、AIに渡す入力の設計精度を上げる方向で効きます。"
    elif tier == "PRO":
        extra = "\n補足：使える形にするコツは「(1)前提固定 → (2)制約明示 → (3)出力形式指定 → (4)反例/例外」をセットで投げることです。"
    
    lines = []
    lines.append(f"【{ability['name']}】")
    lines.append(f"定義：{ability_def['def']}")
    lines.append(f"AI利用で何に効くか：{ability_def['effect']}")
    if ability_def.get("timing"):
        lines.append(f"使うタイミング例：{' / '.join(ability_def['timing'])}")
    if ability_def.get("prompts"):
        prompt_count = 2 if tier == "FREE" else 3
        prompts = ability_def["prompts"][:prompt_count]
        lines.append("プロンプト例：")
        for p in prompts:
            lines.append(f"- {p}")
    lines.append(extra)
    
    return "\n".join(lines)

def help_content() -> str:
    """Help content"""
    return "\n".join([
        "AIXELは「答えを押し付けるAI」ではなく、あなたの思考を観測し、必要な時だけ改善の選択肢を提示する「思考トレーナー」です。",
        "普段：通常会話はできます（内部では観測ログを溜めます）。自動で診断や指摘はしません。",
        "診断：実行したいタイミングで、コマンド『診断』と入力してください。",
        "トレーニング：任意です。コマンド『トレーニング』→能力番号で開始します（開始後は完了まで誘導します）。",
        "クレジット：1クレジット＝1トークン。すべてのAI応答で消費されます。無制限・使い放題は採用しません。",
        "残量確認：『クレジット』／プラン変更：『変更』／追加購入：『購入』"
    ])

def credit_status_text(user: Dict[str, Any]) -> str:
    """Generate credit status text"""
    plan = user.get("plan", "FREE")
    plan_config = PLANS.get(plan, PLANS["FREE"])
    grant = plan_config.get("monthlyGrant", 0)
    ym = yyyymm()
    granted_this_month = (user.get("last_grant_yyyymm") == ym)
    
    next_hint = "今月分の月次付与は反映済みです。" if granted_this_month else "今月分の月次付与は次回アクセス時に反映されます。"
    
    return "\n".join([
        f"プラン：{plan}",
        f"残クレジット：{user.get('credits', 0):,}クレジット",
        f"月次付与：{grant:,}クレジット／月",
        next_hint
    ])

def ability_list_text(lead: str) -> str:
    """Generate ability list text"""
    lines = [lead]
    for ability in ABILITIES:
        lines.append(f"{ability['id']}. {ability['name']}")
    return "\n".join(lines)

def run_diagnosis(user: Dict[str, Any]) -> str:
    """Run diagnosis"""
    logs = db.get_observed_user_messages(user["user_id"], 10)
    
    if len(logs) < 3:
        return "\n".join([
            "【診断】",
            "まだ観測ログが十分ではないため、今回の診断では確度の高い指摘ができません。",
            "通常会話を数往復した後、改めて『診断』を入力してください。",
            "",
            "（自動診断は行いません。診断したいタイミングでのみ実行します）"
        ])
    
    analysis = diagnose_heuristic(logs)
    
    if not analysis["missed"]:
        strongest_name = next(
            (a["name"] for a in ABILITIES if a["key"] == analysis["strongest"]),
            analysis.get("strongest_name", "（判定不能）")
        )
        return "\n".join([
            "【診断】",
            f"対象：直近{min(10, len(logs))}件の入力（観測ログ）",
            "",
            f"最も使われている思考能力（事実ベース）：{strongest_name}",
            "",
            "今回、顕著な偏りや欠損は見られません。",
            "（この場合、改善案やトレーニング案内は出しません）"
        ])
    
    strongest_name = next(
        (a["name"] for a in ABILITIES if a["key"] == analysis["strongest"]),
        "（判定不能）"
    )
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
        f"対象：直近{min(10, len(logs))}件の入力（観測ログ）",
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
