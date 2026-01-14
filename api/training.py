"""
Training system implementation (Spec 02, Spec 05 - 内部フロー仕様凍結版)
"""
from typing import Dict, Any, List, Optional
from api.config import ABILITIES, PLANS, MODE
from api.database import db
from api.openai_client import call_openai
from api.utils import now_iso, safe_json

# Training type definitions (Spec 05 - 型システム, Spec 06 - 10型フル設計)
# 型 = 内部テンプレート（ユーザー非公開）
# Structure: aim, direction, observation_points, ng_directions, challenge_template
# Note: Type numbers/names are NEVER shown to users (Spec 05 - 8, 9)
# challenge_template is reference for generation, actual challenge text is generated dynamically (Spec 05 - 5)
TRAINING_TYPES = {
    "abstract": {
        1: {
            "aim": "複数の具体例から「共通構造（パターン）」を抜き出す",
            "direction": "比較／抽出",
            "observation_points": ["3つが同カテゴリでなくても共通構造を取れているか", "「特徴の羅列」ではなく「仕組み」として言えているか"],
            "ng_directions": ["具体例が並ぶだけで共通点が出ない", "共通点が抽象でなく単なる同義反復になっている"],
            "challenge_template": "具体例を3つ挙げて、共通点を1つにまとめてください（「要するに」で1文）。"
        },
        2: {
            "aim": "一度きりの目的を、他の状況でも使える「再利用可能な原理」に変換する",
            "direction": "再構成",
            "observation_points": ["目的が特定行動ではなく判断原理に変換されているか", "状況が変わっても使える抽象度になっているか"],
            "ng_directions": ["目的を別の言葉で言い換えただけ", "特定の場面にしか使えない原理になっている"],
            "challenge_template": "この目的を、他の場面でも使える「原理」として言い換えてください（『〜すると〜になりやすい』の形で1文）。"
        },
        3: {
            "aim": "状況に「名前」を与え、思考の再利用単位にする",
            "direction": "ラベル化",
            "observation_points": ["その場限りの感想名ではなく、再利用できる命名か", "定義が「条件」で書けているか"],
            "ng_directions": ["名前がキャッチコピーになっている", "定義が曖昧で、どれが該当するか判断できない"],
            "challenge_template": "この状況に名前を付けてください（例：『◯◯型』）。その型の定義を1文で。"
        },
        4: {
            "aim": "文章を「要素→関係→結論」の構造にして捉える",
            "direction": "構造マップ化",
            "observation_points": ["要素がMECE気味に分けられているか", "関係が因果・条件・対比などで明示されているか"],
            "ng_directions": ["要素が増えすぎて整理できていない", "関係が「なんとなく」になっている"],
            "challenge_template": "この話を「要素（3つ）／関係（矢印）／結論（1つ）」で書いてください。"
        },
        5: {
            "aim": "次回も使える「入力テンプレ」として抽象化する",
            "direction": "テンプレ抽出",
            "observation_points": ["変数（穴埋め）が適切に設計されているか", "何を入れれば再現できるかが明確か"],
            "ng_directions": ["テンプレが長文の言い換えで終わっている", "変数が曖昧で再利用できない"],
            "challenge_template": "この内容を、次回も使える「入力テンプレ」にしてください（穴埋め式で）。"
        },
        6: {
            "aim": "差分ではなく「構造の違い」として比較する",
            "direction": "比較抽象化",
            "observation_points": ["表面の違い（量・見た目）で止まっていないか", "仕組み／前提／制約の違いを取れているか"],
            "ng_directions": ["特徴の列挙になっている", "「Aはこう、Bはこう」で終わる"],
            "challenge_template": "AとBの違いを「構造の違い」として説明してください（表層の特徴は禁止）。"
        },
        7: {
            "aim": "変化を「結果」ではなく「成立条件の変化」として捉える",
            "direction": "成立条件変化抽象化",
            "observation_points": ["行動や感想ではなく条件の変化として書けているか", "同じ変化を再現できる視点になっているか"],
            "ng_directions": ["結果や気持ちの変化だけを書いている", "条件が曖昧で再利用できない"],
            "challenge_template": "Before と After で、「何の成立条件がどう変わったか」を1文で書いてください。"
        },
        8: {
            "aim": "失敗を「他でも起きる型」にして再発防止の資産にする",
            "direction": "失敗抽象化",
            "observation_points": ["個人・偶然要因を外して条件で書けているか", "次回の予防に使える粒度か"],
            "ng_directions": ["反省文になっている", "原因が「性格」に寄っている"],
            "challenge_template": "この失敗を『〜のときに起きやすい失敗型』として抽象化してください。"
        },
        9: {
            "aim": "判断を再利用できる「条件分岐ルール」にする",
            "direction": "ルール化",
            "observation_points": ["条件が観測可能で曖昧でないか", "ルールが矛盾しないか"],
            "ng_directions": ["条件が主観で測れない", "例外だらけになっている"],
            "challenge_template": "この判断を『もし〜なら〜する』のルールにしてください（最大3本）。"
        },
        10: {
            "aim": "抽象化できない原因（詰まり）を特定して解除する",
            "direction": "抽象化阻害要因の言語化",
            "observation_points": ["「材料不足」か「視点不足」か「目的不明」かを切れているか", "補うべき情報が具体化されているか"],
            "ng_directions": ["「自分は抽象化が苦手」で終わる", "補う内容が曖昧で次に繋がらない"],
            "challenge_template": "抽象化を難しくしている要因を1つ特定し、どう補えば抽象化できるかを書いてください。"
        }
    },
    "decompose": {
        1: {
            "aim": "最終ゴールから逆算して、必要要素を洗い出す",
            "direction": "ゴール逆算分解",
            "observation_points": ["ゴールから逆方向に分けているか", "抜けている前提条件がないか"],
            "ng_directions": ["思いつき順で並べている", "ゴールと直接関係ない要素が混ざる"],
            "challenge_template": "このゴールを達成するために必要な要素を、逆算で5つに分解してください。"
        },
        2: {
            "aim": "思考を「今すぐ着手できる行動単位」まで分解する",
            "direction": "実行可能単位分解",
            "observation_points": ["1項目＝1行動になっているか", "依存条件が明示されているか"],
            "ng_directions": ["「検討する」「考える」など行動になっていない", "実行順や前提が不明確"],
            "challenge_template": "この作業を、「今すぐ実行できる最小単位」まで分解してください。"
        },
        3: {
            "aim": "議論・判断を「論点」に分けて整理する",
            "direction": "論点分解",
            "observation_points": ["論点同士が重複していないか", "すべて揃えば判断できる構成か"],
            "ng_directions": ["論点が感想レベル", "重要な論点が抜けている"],
            "challenge_template": "このテーマを判断するための論点を3〜5個に分けてください。"
        },
        4: {
            "aim": "問題の原因を「可能性」として切り分ける",
            "direction": "原因切り分け",
            "observation_points": ["原因が混ざらず独立しているか", "検証可能な粒度か"],
            "ng_directions": ["原因と結果が混同されている", "精神論・性格論に寄っている"],
            "challenge_template": "この問題の原因候補を、独立した要因として列挙してください。"
        },
        5: {
            "aim": "暗黙の前提を洗い出して可視化する",
            "direction": "前提分解",
            "observation_points": ["「当たり前」を疑えているか", "前提が条件文で書けているか"],
            "ng_directions": ["前提が1つも出てこない", "前提が事実と混同されている"],
            "challenge_template": "この話に含まれている前提条件をすべて書き出してください。"
        },
        6: {
            "aim": "制約を要素別に分け、影響範囲を把握する",
            "direction": "制約分解",
            "observation_points": ["制約がカテゴリごとに分かれているか", "実際の判断に影響する制約か"],
            "ng_directions": ["制約が感覚的", "重要制約が抜けている"],
            "challenge_template": "この状況の制約を「時間／お金／人／ルール」に分けて整理してください。"
        },
        7: {
            "aim": "同時に考えている要素を順序づける",
            "direction": "優先順位分解",
            "observation_points": ["判断基準が明示されているか", "順序に一貫性があるか"],
            "ng_directions": ["全部大事で順番がつかない", "理由が後付け"],
            "challenge_template": "要素を重要度順に並べ、その理由を1行ずつ書いてください。"
        },
        8: {
            "aim": "物事を「段階（フェーズ）」に分けて捉える",
            "direction": "フェーズ分解",
            "observation_points": ["フェーズごとに役割が違うか", "同じ作業が重複していないか"],
            "ng_directions": ["フェーズ分けが時間順だけ", "各フェーズの目的が曖昧"],
            "challenge_template": "この取り組みを3フェーズに分け、それぞれの目的を書いてください。"
        },
        9: {
            "aim": "判断に必要な情報を要素化する",
            "direction": "判断材料分解",
            "observation_points": ["材料が「意見」でなく「情報」か", "足りない材料が特定できているか"],
            "ng_directions": ["情報と推測が混ざる", "集めるべき材料が不明"],
            "challenge_template": "この判断に必要な材料を、情報項目として列挙してください。"
        },
        10: {
            "aim": "どこで破綻しやすいかを事前に切り分ける",
            "direction": "破綻ポイント分解",
            "observation_points": ["リスクを要素単位で見ているか", "対策検討につながる分解か"],
            "ng_directions": ["楽観前提で分解しない", "破綻を「運」で片付ける"],
            "challenge_template": "この計画が破綻するとしたら、どの要素が原因になりやすいか分解してください。"
        }
    },
    "specify": {
        1: {
            "aim": "曖昧な要望を、実装可能な仕様文に変換する",
            "direction": "要件→仕様変換",
            "observation_points": ["主語・対象・動作が明確か", "曖昧語が排除されているか"],
            "ng_directions": ["「いい感じに」「適切に」などが残る", "実装者の解釈に委ねている"],
            "challenge_template": "この要望を、実装者が迷わない仕様文に書き換えてください。"
        },
        2: {
            "aim": "「やってはいけないこと」を仕様として言語化する",
            "direction": "禁止事項明文化",
            "observation_points": ["禁止が行動レベルで書かれているか", "例外と混ざっていないか"],
            "ng_directions": ["禁止が抽象的", "暗黙の禁止が放置されている"],
            "challenge_template": "この機能で「やってはいけないこと」を仕様として列挙してください。"
        },
        3: {
            "aim": "入力と出力の関係を明確にする",
            "direction": "入出力定義",
            "observation_points": ["入力条件が具体か", "出力が状態として定義されているか"],
            "ng_directions": ["入力が前提依存", "出力が「結果が出る」など曖昧"],
            "challenge_template": "この処理の入力と出力を、それぞれ明確に定義してください。"
        },
        4: {
            "aim": "通常ケースと例外ケースを切り分ける",
            "direction": "例外条件定義",
            "observation_points": ["例外が網羅されているか", "例外時の挙動が決まっているか"],
            "ng_directions": ["例外が「想定外」で処理されている", "例外時の責務が不明"],
            "challenge_template": "通常ケースと、例外ケースを分けて仕様化してください。"
        },
        5: {
            "aim": "どこまでが対象で、どこからが対象外かを定義する",
            "direction": "境界条件言語化",
            "observation_points": ["境界が言葉で切れているか", "グレーゾーンが残っていないか"],
            "ng_directions": ["「ケースバイケース」で逃げている", "対象外が未定義"],
            "challenge_template": "この仕様の適用範囲と対象外を明確に書いてください。"
        },
        6: {
            "aim": "状態の変化を文章で追えるようにする",
            "direction": "状態遷移言語化",
            "observation_points": ["開始状態と終了状態が明確か", "中間状態が抜けていないか"],
            "ng_directions": ["状態が暗黙", "遷移条件が書かれていない"],
            "challenge_template": "この機能の状態遷移を、文章で順に説明してください。"
        },
        7: {
            "aim": "言葉の意味を仕様として固定する",
            "direction": "用語定義固定",
            "observation_points": ["用語が一意に定義されているか", "文脈で意味が変わらないか"],
            "ng_directions": ["同じ言葉を別の意味で使っている", "定義が感覚的"],
            "challenge_template": "この中で誤解されやすい用語を定義してください。"
        },
        8: {
            "aim": "仕様判断の基準を明文化する",
            "direction": "判断基準言語化",
            "observation_points": ["基準が比較可能か", "優先順位が明示されているか"],
            "ng_directions": ["判断が人依存", "基準が後付け"],
            "challenge_template": "どちらを採用するかの判断基準を仕様として書いてください。"
        },
        9: {
            "aim": "仕様が「書きすぎ／足りなさすぎ」になっていないかを判断する",
            "direction": "仕様過不足点検",
            "observation_points": ["実装に不要な説明を見抜けているか", "実装に必要な情報が抜けていないか"],
            "ng_directions": ["全部必要だとして削れない", "逆に重要情報まで削ってしまう"],
            "challenge_template": "この仕様について、過剰な部分と不足している部分をそれぞれ指摘してください。"
        },
        10: {
            "aim": "実装者の視点で仕様の穴を見つける",
            "direction": "実装者視点チェック",
            "observation_points": ["迷いポイントが具体か", "追記が仕様文になっているか"],
            "ng_directions": ["「たぶん伝わる」で終わる", "実装者任せ"],
            "challenge_template": "実装者が迷いそうな点を洗い出し、追記してください。"
        }
    },
    "context": {
        1: {
            "aim": "会話・設計の前提条件を明示し、途中でズレないように固定する",
            "direction": "前提固定確認",
            "observation_points": ["前提が明示されているか", "暗黙前提を言語化できているか", "前提と結論が矛盾していないか"],
            "ng_directions": ["前提を書かずに結論から入る", "途中で前提がすり替わっている", "「なんとなく共有されている前提」に依存している"],
            "challenge_template": "この話の前提条件を箇条書きで整理し、変えてはいけない前提を明確にしてください。"
        },
        2: {
            "aim": "すでに決まった事項を保持し、それを崩さずに次の検討を進める",
            "direction": "決定事項保持",
            "observation_points": ["決定事項と未決定事項が分けられているか", "決定事項を前提に話が進んでいるか"],
            "ng_directions": ["決定事項を無視した新案を出す", "「一度決めたこと」を毎回揺らしてしまう"],
            "challenge_template": "これまでに決まっている事項を整理し、それを前提に次の検討ポイントを出してください。"
        },
        3: {
            "aim": "提案内容が、既存の前提・思想と矛盾していないかを検出する",
            "direction": "前提ズレ検出",
            "observation_points": ["矛盾点を具体箇所で指摘できているか", "なぜズレるのか理由を説明できているか"],
            "ng_directions": ["内容の良し悪しだけで判断している", "前提チェックをせず採用／却下している"],
            "challenge_template": "この提案が、既存の前提や思想と矛盾している可能性がある箇所を指摘してください。"
        },
        4: {
            "aim": "議論途中でズレた前提認識を再同期する",
            "direction": "前提再同期",
            "observation_points": ["前提の食い違いを検出できているか", "意味を変えずに再定義できているか"],
            "ng_directions": ["単なる要約で終わる", "再掲時に前提の意味が変わっている"],
            "challenge_template": "現在の前提を整理し、認識がズレていそうな点を揃えてください。"
        },
        5: {
            "aim": "前提や条件が変わった場合の影響範囲を把握する",
            "direction": "条件変更影響確認",
            "observation_points": ["影響範囲を漏れなく出せているか", "直接／間接影響を分けているか"],
            "ng_directions": ["条件変更を軽く扱っている", "一部の影響しか見ていない"],
            "challenge_template": "この条件が変わった場合、どこに影響が出るかを整理してください。"
        },
        6: {
            "aim": "判断や仕様が、上位思想・方針と整合しているかを確認する",
            "direction": "思想整合チェック",
            "observation_points": ["思想を基準として使っているか", "好き嫌いで判断していないか"],
            "ng_directions": ["思想を確認せず「便利だから」で決める", "短期最適で長期思想を壊す"],
            "challenge_template": "この判断が、上位思想・方針と整合しているかを確認してください。"
        },
        7: {
            "aim": "議論が本筋から逸れていないかを確認し、軌道修正する",
            "direction": "話題逸脱防止",
            "observation_points": ["本来の目的を言語化できているか", "逸脱点を具体に指摘できているか"],
            "ng_directions": ["盛り上がりに流される", "目的を見失ったまま話を続ける"],
            "challenge_template": "現在の議論が、本来の目的から逸れていないか確認してください。"
        },
        8: {
            "aim": "検討範囲（スコープ）を守り、不要な拡張を防ぐ",
            "direction": "スコープ保持",
            "observation_points": ["スコープ内外を明確に分けているか", "「今はやらない」を言語化できているか"],
            "ng_directions": ["思いつきで範囲を広げる", "全部やろうとして破綻する"],
            "challenge_template": "今回の検討スコープを明確にし、含めない内容を整理してください。"
        },
        9: {
            "aim": "中断後・時間経過後に文脈を正しく再接続する",
            "direction": "文脈再接続",
            "observation_points": ["過去の流れを正確に拾えているか", "今回やるべきことが明確か"],
            "ng_directions": ["前回内容を思い込みで補完する", "最初からやり直してしまう"],
            "challenge_template": "前回までの文脈を要約し、今回の位置づけを整理してください。"
        },
        10: {
            "aim": "途中変更があった点を把握し、最新版前提で進める",
            "direction": "変更履歴意識",
            "observation_points": ["旧案と新版を混同していないか", "最新仕様を基準にしているか"],
            "ng_directions": ["古い前提で話してしまう", "変更点を把握しないまま進める"],
            "challenge_template": "途中で変更された点を整理し、最新前提を明確にしてください。"
        }
    },
    "question": {
        1: {
            "aim": "作業・相談・依頼の「そもそもの目的」を明確にする問いを立てる",
            "direction": "目的確認問い生成",
            "observation_points": ["手段ではなく目的に向いた問いになっているか", "Yes/Noで終わらない問いか"],
            "ng_directions": ["方法論の質問になっている", "「どうやるか」しか聞いていない"],
            "challenge_template": "この依頼の目的を明確にするための問いを1つ作ってください。"
        },
        2: {
            "aim": "暗黙の前提を表に出す問いを作る",
            "direction": "前提確認問い生成",
            "observation_points": ["前提が存在しそうな箇所を特定できているか", "相手を責めない聞き方になっているか"],
            "ng_directions": ["前提を決めつけている", "確認ではなく主張になっている"],
            "challenge_template": "この話に含まれていそうな前提を確認する問いを作ってください。"
        },
        3: {
            "aim": "判断に使われる基準を明確にする問いを立てる",
            "direction": "判断基準確認",
            "observation_points": ["基準という概念に触れているか", "価値観・優先順位に向いた問いか"],
            "ng_directions": ["結論を急がせる問いになっている", "基準ではなく意見を聞いている"],
            "challenge_template": "この判断で、何を基準に決めるのかを確認する問いを作ってください。"
        },
        4: {
            "aim": "時間・コスト・ルールなどの制約を明らかにする問いを作る",
            "direction": "制約条件抽出",
            "observation_points": ["制約を限定せず広く捉えているか", "後出し制約を防ぐ問いになっているか"],
            "ng_directions": ["制約を無視して話を進めている", "都合のいい制約しか聞いていない"],
            "challenge_template": "この話で考慮すべき制約を確認する問いを作ってください。"
        },
        5: {
            "aim": "抜けていそうな視点を補う問いを立てる",
            "direction": "視点不足検出",
            "observation_points": ["別の立場・時間軸・影響範囲を意識しているか", "思考を広げる問いか"],
            "ng_directions": ["自分の視点だけで考えている", "話題を広げすぎている"],
            "challenge_template": "この話で抜けていそうな視点を補う問いを作ってください。"
        },
        6: {
            "aim": "複数要素がある中で、優先順位を明らかにする問いを作る",
            "direction": "優先順位明確化",
            "observation_points": ["比較前提の問いになっているか", "トレードオフを意識しているか"],
            "ng_directions": ["全部大事という前提で聞いている", "優先順位を避けている"],
            "challenge_template": "この中で何を最優先に考えるべきかを確認する問いを作ってください。"
        },
        7: {
            "aim": "「どこまで行けばOKか」を定義する問いを立てる",
            "direction": "ゴール定義問い生成",
            "observation_points": ["成果物や状態に触れているか", "曖昧なゴールを具体化できているか"],
            "ng_directions": ["終わりを考えていない", "精神論的なゴールになっている"],
            "challenge_template": "この作業の完了条件を確認する問いを作ってください。"
        },
        8: {
            "aim": "失敗・ズレが起きる可能性を事前に確認する問いを作る",
            "direction": "リスク想定問い生成",
            "observation_points": ["悲観ではなく想定として聞けているか", "現実的なリスクに向いているか"],
            "ng_directions": ["楽観前提で問いを作っている", "抽象的すぎる不安になっている"],
            "challenge_template": "この判断で起こり得るリスクを確認する問いを作ってください。"
        },
        9: {
            "aim": "誰が最終判断を持つのかを明確にする問いを作る",
            "direction": "判断主体確認",
            "observation_points": ["責任の所在に触れているか", "役割分担が明確になる問いか"],
            "ng_directions": ["全員判断になっている", "責任を曖昧にしている"],
            "challenge_template": "この件の最終判断者を確認する問いを作ってください。"
        },
        10: {
            "aim": "行動ではなく「次に行う判断」を明確にする",
            "direction": "次の判断行為定義",
            "observation_points": ["行動ではなく判断になっているか", "判断の対象と基準が見えているか"],
            "ng_directions": ["ToDoや作業指示になっている", "判断内容が曖昧"],
            "challenge_template": "この後に行うべき「判断行為」を1つ定義してください。"
        }
    },
    "hypothesis": {
        1: {
            "aim": "問題の原因を複数仮説として立て、思考を固定しない",
            "direction": "原因仮説列挙",
            "observation_points": ["単一原因に決め打ちしていないか", "仮説として「断定していない」か"],
            "ng_directions": ["最初の思いつきを真因扱いする", "原因と事象を混同している"],
            "challenge_template": "この問題の原因仮説を3つ挙げてください。"
        },
        2: {
            "aim": "主要因と副次要因を分けて考える",
            "direction": "影響要因分離",
            "observation_points": ["影響度の大小を意識できているか", "全部同列に扱っていないか"],
            "ng_directions": ["重要度の差を付けられない", "「あり得る」だけで並べている"],
            "challenge_template": "主因になりそうな仮説と、影響が小さい仮説を分けてください。"
        },
        3: {
            "aim": "仮説を「検証できる形」に落とす",
            "direction": "検証可能化",
            "observation_points": ["観測・比較・実験など具体手段があるか", "結果で是非が分かるか"],
            "ng_directions": ["検証不能な仮説", "感覚・印象に依存している"],
            "challenge_template": "この仮説が正しいか確認する方法を1つ書いてください。"
        },
        4: {
            "aim": "思い込みを壊すための逆仮説を立てる",
            "direction": "逆仮説（反証）設定",
            "observation_points": ["自説を疑えているか", "反証の視点があるか"],
            "ng_directions": ["仮説を守りにいっている", "逆仮説を考えない"],
            "challenge_template": "この仮説が間違っているとしたら、どんな可能性がありますか。"
        },
        5: {
            "aim": "複数仮説を並べ、相対比較で検討する",
            "direction": "比較仮説",
            "observation_points": ["比較軸が明確か", "感情ではなく材料で比べているか"],
            "ng_directions": ["好みで選んでいる", "比較軸が曖昧"],
            "challenge_template": "2つの仮説を比べ、どちらが妥当か判断材料を書いてください。"
        },
        6: {
            "aim": "仮説を立てるには情報が足りないと判断できる",
            "direction": "データ不足認識",
            "observation_points": ["不足を認められているか", "追加情報が具体か"],
            "ng_directions": ["材料不足でも仮説を断定する", "不足点を言語化できない"],
            "challenge_template": "仮説を立てるには、どんな情報が不足していますか。"
        },
        7: {
            "aim": "問題が起きた順序から仮説を組み立てる",
            "direction": "時系列仮説",
            "observation_points": ["順序と因果を分けて考えているか", "後出し原因になっていないか"],
            "ng_directions": ["結果から原因を捏造する", "時系列を無視する"],
            "challenge_template": "出来事を時系列に並べ、原因仮説を立ててください。"
        },
        8: {
            "aim": "条件ごとに異なる仮説を立てる",
            "direction": "条件分岐仮説",
            "observation_points": ["条件依存を考慮しているか", "一律仮説にしていないか"],
            "ng_directions": ["条件差を無視している", "万能仮説になっている"],
            "challenge_template": "条件AとBで、原因仮説がどう変わるか書いてください。"
        },
        9: {
            "aim": "最小コストで仮説の是非を確かめる",
            "direction": "検証コスト最小化",
            "observation_points": ["コスト（時間・手間・リスク）を意識しているか", "完璧検証を求めていないか"],
            "ng_directions": ["検証難易度を考慮していない", "大掛かりな検証を選んでいる"],
            "challenge_template": "最も検証コストが低い仮説を1つ選び、理由を書いてください。"
        },
        10: {
            "aim": "検証結果を踏まえて仮説を更新する",
            "direction": "仮説更新",
            "observation_points": ["仮説を捨て・修正できているか", "結果に固執していないか"],
            "ng_directions": ["最初の仮説に固執する", "更新せず次に進む"],
            "challenge_template": "検証結果を踏まえて、仮説をどう更新しますか。"
        }
    },
    "pause": {
        1: {
            "aim": "材料不足のまま決めない姿勢を明確にする",
            "direction": "判断保留宣言",
            "observation_points": ["保留理由が具体か", "「逃げ」ではなく根拠があるか"],
            "ng_directions": ["理由なき保留", "不安を理由にした先延ばし"],
            "challenge_template": "この判断はいま保留にすべき理由を1文で書いてください。"
        },
        2: {
            "aim": "決断に足りない情報を特定する",
            "direction": "情報不足特定",
            "observation_points": ["具体情報になっているか", "取得可能性があるか"],
            "ng_directions": ["抽象的（もっと調査）", "取得不能な情報"],
            "challenge_template": "判断に足りない情報を3つ挙げてください。"
        },
        3: {
            "aim": "「止まる」と同時に次の一手を決める",
            "direction": "追加情報取得計画",
            "observation_points": ["手段が現実的か", "期限が意識されているか"],
            "ng_directions": ["計画がない", "期限不明"],
            "challenge_template": "不足情報をどう集めるか手順を書いてください。"
        },
        4: {
            "aim": "暫定判断と最終判断を分ける",
            "direction": "仮決定明示",
            "observation_points": ["仮決定の条件が明確か", "覆る余地を残しているか"],
            "ng_directions": ["仮決定を本決定扱い", "条件未定義"],
            "challenge_template": "仮決定として採る案と、その前提条件を書いてください。"
        },
        5: {
            "aim": "決めない間のリスクを抑える",
            "direction": "リスク最小化保留",
            "observation_points": ["被害抑制の視点があるか", "過剰対応になっていないか"],
            "ng_directions": ["放置", "過剰な防御"],
            "challenge_template": "判断保留中に取る最小安全策を書いてください。"
        },
        6: {
            "aim": "無期限の停止を防ぐ",
            "direction": "判断期限設定",
            "observation_points": ["期限が具体か", "条件が測定可能か"],
            "ng_directions": ["期限なし", "条件が曖昧"],
            "challenge_template": "判断期限と、期限までに満たす条件を書いてください。"
        },
        7: {
            "aim": "目的を持って判断を一時停止する",
            "direction": "観点切替目的停止",
            "observation_points": ["停止理由が明確か", "切り替える観点が具体か"],
            "ng_directions": ["理由なく止まっている", "切り替え先が不明確"],
            "challenge_template": "別の観点に切り替えるため、いま止める理由を1文で書いてください。"
        },
        8: {
            "aim": "情報過多による誤判断を避ける",
            "direction": "情報過多停止",
            "observation_points": ["絞り込み基準があるか", "追加取得を止められているか"],
            "ng_directions": ["情報収集を続けるだけ", "基準なし"],
            "challenge_template": "情報が多すぎるため止める理由と、絞り込み基準を書いてください。"
        },
        9: {
            "aim": "感情が判断に影響する場面で止まる",
            "direction": "感情影響遮断",
            "observation_points": ["感情を特定できているか", "判断と切り離しているか"],
            "ng_directions": ["感情を無視", "感情で即断"],
            "challenge_template": "いま判断を止めるべき感情要因を書いてください。"
        },
        10: {
            "aim": "停止後に「いつ再開するか」を決める",
            "direction": "再開条件定義",
            "observation_points": ["再開条件が明確か", "確認可能か"],
            "ng_directions": ["再開条件なし", "主観的条件のみ"],
            "challenge_template": "判断を再開する条件を1つ定義してください。"
        }
    },
    "metacog": {
        1: {
            "aim": "自分が無意識に置いている前提を言語化する",
            "direction": "前提可視化",
            "observation_points": ["前提が具体か", "事実と仮定を分けているか"],
            "ng_directions": ["前提が抽象的", "事実と仮定が混在"],
            "challenge_template": "いまの判断で、前提として置いていることを3つ書いてください。"
        },
        2: {
            "aim": "判断に影響する思い込みを特定する",
            "direction": "バイアス検出",
            "observation_points": ["自分視点で書けているか", "感情と区別できているか"],
            "ng_directions": ["他人のバイアス指摘", "一般論のみ"],
            "challenge_template": "この判断に影響していそうな思い込みを1つ挙げてください。"
        },
        3: {
            "aim": "当事者視点と第三者視点を切り分ける",
            "direction": "視点分離",
            "observation_points": ["主語が切り替わっているか", "感情が薄れているか"],
            "ng_directions": ["当事者視点のまま", "評価語が強い"],
            "challenge_template": "第三者から見た場合、この状況はどう見えるかを書いてください。"
        },
        4: {
            "aim": "手段に引っ張られず、目的を再確認する",
            "direction": "目的再確認",
            "observation_points": ["手段が混ざっていないか", "測れる目的か"],
            "ng_directions": ["手段が目的化", "目的が曖昧"],
            "challenge_template": "そもそもの目的を1文で書き直してください。"
        },
        5: {
            "aim": "感情と判断材料を分離する",
            "direction": "感情分離",
            "observation_points": ["感情を名詞で書けているか", "判断材料と分けているか"],
            "ng_directions": ["感情の否認", "感情＝結論"],
            "challenge_template": "いまの判断に影響している感情を書き出してください。"
        },
        6: {
            "aim": "自分の典型的な思考パターンを把握する",
            "direction": "思考癖認識",
            "observation_points": ["具体例があるか", "再現性があるか"],
            "ng_directions": ["一回限りの話", "抽象的性格論"],
            "challenge_template": "似た場面で繰り返している判断パターンを書いてください。"
        },
        7: {
            "aim": "使っている判断基準が適切か点検する",
            "direction": "判断基準点検",
            "observation_points": ["基準が明示されているか", "目的と整合しているか"],
            "ng_directions": ["基準不在", "場当たり基準"],
            "challenge_template": "いま使っている判断基準は何かを書いてください。"
        },
        8: {
            "aim": "別の切り口で状況を見る",
            "direction": "代替視点生成",
            "observation_points": ["軸が具体か", "結論を急いでいないか"],
            "ng_directions": ["軸が同じ", "比較になっていない"],
            "challenge_template": "別の評価軸で見るとどう見えるかを書いてください。"
        },
        9: {
            "aim": "頭の中と文章のズレに気づく",
            "direction": "言語化ズレ検知",
            "observation_points": ["言い換えが成立しているか", "意味が変わっていないか"],
            "ng_directions": ["表現だけ変更", "意味が逸脱"],
            "challenge_template": "本当は何を考えているかを、別の言い方で書いてください。"
        },
        10: {
            "aim": "自分が「どの段階で判断しているか」を把握する",
            "direction": "判断位置確認",
            "observation_points": ["段階認識が正確か", "次の行動が明確か"],
            "ng_directions": ["段階不明", "すべて判断済み扱い"],
            "challenge_template": "いまは判断前・判断中・判断後のどこかを書いてください。"
        }
    },
    "discard": {
        1: {
            "aim": "目的に直接寄与しない要素を切る",
            "direction": "目的再照合カット",
            "observation_points": ["目的基準で判定しているか", "感情で残していないか"],
            "ng_directions": ["「念のため」で残す", "目的が曖昧なまま判断"],
            "challenge_template": "この要素は「目的達成」に直接必要かを判定し、不要なら外してください。"
        },
        2: {
            "aim": "価値に対してコストが高い要素を捨てる",
            "direction": "価値／コスト比較",
            "observation_points": ["価値とコストが分離されているか", "相対比較ができているか"],
            "ng_directions": ["絶対評価のみ", "コスト未言語化"],
            "challenge_template": "各要素の価値とコストを1行で書き、捨て候補を選んでください。"
        },
        3: {
            "aim": "最小成立形に落とす",
            "direction": "MVP圧縮",
            "observation_points": ["必須条件の明確化", "「あったら良い」の排除"],
            "ng_directions": ["必須の定義不足", "将来要件の混入"],
            "challenge_template": "成立に必須な要素だけ残し、MVPを定義してください。"
        },
        4: {
            "aim": "境界線を引いて切る",
            "direction": "優先度境界",
            "observation_points": ["明確な線引き", "理由の簡潔さ"],
            "ng_directions": ["同率多発", "理由が感想"],
            "challenge_template": "上位3つだけ残し、4位以下を捨ててください。"
        },
        5: {
            "aim": "全体を壊しうる最大リスク源を切断する",
            "direction": "最大リスク源切除",
            "observation_points": ["リスクの因果を説明できているか", "代替や割り切りができているか"],
            "ng_directions": ["リスクが抽象的", "調整や先送りで済ませている"],
            "challenge_template": "この中で、最も致命的なリスク源を1つ選び、捨ててください。"
        },
        6: {
            "aim": "判断速度を上げるために削る",
            "direction": "意思決定速度",
            "observation_points": ["遅延要因の特定", "速度指標の意識"],
            "ng_directions": ["速度未意識", "網羅志向"],
            "challenge_template": "判断を遅くしている要素を1つ捨ててください。"
        },
        7: {
            "aim": "再利用性が低いものを切る",
            "direction": "再利用観点",
            "observation_points": ["再利用基準の明確化", "将来視点"],
            "ng_directions": ["今回最適のみ", "場当たり判断"],
            "challenge_template": "再利用できない要素を捨ててください。"
        },
        8: {
            "aim": "複雑な依存を断つ",
            "direction": "依存関係解消",
            "observation_points": ["依存の可視化", "代替の想定"],
            "ng_directions": ["依存未認識", "切断不可前提"],
            "challenge_template": "依存関係を1つ切るなら何を捨てますか。"
        },
        9: {
            "aim": "スコープ膨張を止める",
            "direction": "スコープ凍結",
            "observation_points": ["否定文の明確さ", "境界の具体性"],
            "ng_directions": ["曖昧な否定", "例外多発"],
            "challenge_template": "ここから先は「やらない」と決める範囲を書いてください。"
        },
        10: {
            "aim": "捨てる判断を再現可能にする",
            "direction": "捨てた理由言語化",
            "observation_points": ["判断基準が含まれるか", "他者に伝わるか"],
            "ng_directions": ["感情理由", "事後正当化"],
            "challenge_template": "捨てた理由を一文で言語化してください。"
        }
    },
    "criteria": {
        1: {
            "aim": "判断がブレる原因（基準の未定義）を潰す",
            "direction": "判断基準の言語化",
            "observation_points": ["基準が名詞で明確", "優先順位がある", "基準と目的が混線していない"],
            "ng_directions": ["基準が感情・気分語", "「いい感じ」など曖昧", "優先順位なし"],
            "challenge_template": "この判断の「基準（何を優先するか）」を1〜3個に言語化してください。"
        },
        2: {
            "aim": "判断が常に基準から始まっているかを検証する",
            "direction": "基準先行一貫性検証",
            "observation_points": ["基準が最初に置かれているか", "結論が基準から導かれているか"],
            "ng_directions": ["結論先行", "基準が途中で差し替わる"],
            "challenge_template": "判断基準→理由→結論の順で、因果を説明してください。"
        },
        3: {
            "aim": "複数基準の衝突時に迷わない順序を作る",
            "direction": "基準の優先順位固定",
            "observation_points": ["順位が明確", "順位の理由がある", "順位が状況で変わる条件が書けている"],
            "ng_directions": ["全部大事で順位なし", "場面でコロコロ変わる", "「ケースバイケース」で逃げる"],
            "challenge_template": "基準を最大3つに絞り、優先順位（1位〜3位）を決めてください。"
        },
        4: {
            "aim": "見落としやすい評価軸を事前に補完する",
            "direction": "基準の抜け検出",
            "observation_points": ["リスク・コスト・時間・再現性などが入る", "追加基準が目的と整合"],
            "ng_directions": ["思いつき羅列", "追加基準が結論誘導のためだけ", "目的と無関係"],
            "challenge_template": "この判断で見落としやすい基準を2つ追加候補として出してください。"
        },
        5: {
            "aim": "「基準」と「制約（守らないといけない条件）」の混同を解く",
            "direction": "制約条件の分離",
            "observation_points": ["制約が「絶対NG/必須」で書ける", "基準は比較軸になっている"],
            "ng_directions": ["制約が基準扱い", "基準が制約化して思考停止", "「できれば」が混ざる"],
            "challenge_template": "基準（優先順位）と制約（絶対条件）を分けて書いてください。"
        },
        6: {
            "aim": "案の評価軸を統一して比較できるようにする",
            "direction": "代替案の同一基準比較",
            "observation_points": ["同一基準で比較", "採点ではなく言語で優劣理由", "基準の重みが一貫"],
            "ng_directions": ["案ごとに基準を変える", "印象論", "比較軸が途中で増減"],
            "challenge_template": "案A/Bを「同じ基準」で比較し、どちらが上かを決めてください。"
        },
        7: {
            "aim": "基準が使えない例外を先に定義し、ブレを防ぐ",
            "direction": "例外条件の定義",
            "observation_points": ["例外が具体", "例外時の代替基準がある", "例外が乱用されない"],
            "ng_directions": ["例外が広すぎる", "例外＝言い訳化", "例外時の方針が未定義"],
            "challenge_template": "この基準を使わない例外条件を1〜2個だけ定義してください。"
        },
        8: {
            "aim": "材料不足での見切り発車を防ぎ、判断品質を保つ",
            "direction": "判断材料不足の宣言",
            "observation_points": ["不足材料が具体", "「何が揃えば決めるか」が明確", "収集手段が現実的"],
            "ng_directions": ["不足が抽象的", "集め方なし", "「とりあえず決める」で逃げる"],
            "challenge_template": "今の判断に足りない材料を3つ挙げ、集め方を1つ書いてください。"
        },
        9: {
            "aim": "毎回ブレる基準を「短い固定文」にして保持しやすくする",
            "direction": "判断基準の固定フレーズ化",
            "observation_points": ["短い", "優先順位が入る", "状況が変わっても使える抽象度"],
            "ng_directions": ["長すぎて覚えられない", "抽象すぎて使えない", "具体に寄りすぎて汎用性ゼロ"],
            "challenge_template": "判断基準を「1文」に圧縮して書いてください（20字〜40字程度）。"
        },
        10: {
            "aim": "別ケースでも同じ基準で判断できるかを検証する",
            "direction": "一貫性検証",
            "observation_points": ["基準が維持", "変化理由が基準に紐づく", "例外条件の扱いが明確"],
            "ng_directions": ["ケースごとに基準がすり替わる", "結論先行の後付け", "例外が曖昧"],
            "challenge_template": "ケースを1つ変えて、同じ基準で結論がどう変わるか説明してください。"
        }
    },
    "reuse": {
        1: {
            "aim": "一度出した結論を、次回も使える形にする",
            "direction": "結論テンプレ化",
            "observation_points": ["前提／判断基準／結論が分離されているか", "流用可能な構造か"],
            "ng_directions": ["今回限りの文脈依存", "感想や経緯が混入"],
            "challenge_template": "この結論を「テンプレ1枚」に変換してください。"
        },
        2: {
            "aim": "判断の順序を再現可能にする",
            "direction": "判断フロー化",
            "observation_points": ["分岐条件が明確か", "再現可能な粒度か"],
            "ng_directions": ["思考の省略", "条件未定義"],
            "challenge_template": "同じ判断をするための手順（フロー）を書いてください。"
        },
        3: {
            "aim": "抜け漏れを防ぐ資産に変換する",
            "direction": "チェックリスト化",
            "observation_points": ["Yes/Noで確認できるか", "過不足のない項目数"],
            "ng_directions": ["抽象項目のみ", "確認不能な表現"],
            "challenge_template": "次回のためのチェックリストを作ってください。"
        },
        4: {
            "aim": "AIに投げる入力を再利用可能にする",
            "direction": "入力テンプレ設計",
            "observation_points": ["必須項目が揃っているか", "空欄前提で使えるか"],
            "ng_directions": ["今回の内容ベタ貼り", "汎用化不足"],
            "challenge_template": "同種タスク用の入力テンプレを作ってください。"
        },
        5: {
            "aim": "毎回の出力品質を安定させる",
            "direction": "出力フォーマット固定",
            "observation_points": ["項目順が明確", "評価語を含まない"],
            "ng_directions": ["自由記述のみ", "順序不定"],
            "challenge_template": "望ましい出力フォーマットを固定してください。"
        },
        6: {
            "aim": "再利用時の認知コストを下げる",
            "direction": "命名規則設計",
            "observation_points": ["意味が推測できるか", "拡張に耐えるか"],
            "ng_directions": ["場当たり命名", "略語乱用"],
            "challenge_template": "この仕組みに一貫した命名規則を付けてください。"
        },
        7: {
            "aim": "避けるべき型を資産化する",
            "direction": "失敗パターン抽出",
            "observation_points": ["具体的行動で書けているか", "再発防止に使えるか"],
            "ng_directions": ["精神論", "抽象注意喚起"],
            "challenge_template": "次回避けるべき失敗パターンを3つ書いてください。"
        },
        8: {
            "aim": "使える／使えない境界を定義する",
            "direction": "再利用条件明文化",
            "observation_points": ["条件が具体", "誤用防止になる"],
            "ng_directions": ["条件未定義", "万能扱い"],
            "challenge_template": "この型が使える条件・使えない条件を書いてください。"
        },
        9: {
            "aim": "改善を積み重ねられる設計にする",
            "direction": "バージョン管理",
            "observation_points": ["更新トリガー明確", "後方互換意識"],
            "ng_directions": ["更新無計画", "都度上書き"],
            "challenge_template": "更新ルール（いつ・何を・どう変えるか）を定義してください。"
        },
        10: {
            "aim": "第三者が使える資産にする",
            "direction": "他者引き継ぎ",
            "observation_points": ["前提説明の有無", "誤解余地の少なさ"],
            "ng_directions": ["内輪前提", "説明不足"],
            "challenge_template": "初見の人向けに使い方を1分で説明してください。"
        }
    }
}

def select_training_type(
    ability_key: str,
    user_id: str,
    context: Optional[Dict[str, Any]] = None,
    exclude_types: Optional[List[int]] = None
) -> int:
    """Select training type (Spec 05 - 4: 型選定ルール, Spec 06 - 10型フル設計)
    - Avoid recently used types
    - Prioritize context fit
    - Never show type number to user
    
    Spec 06 - ②: トレーニング「型①〜⑩」の出題選択ルール
    - 対象能力内の型①〜⑩すべてを出題候補とする
    - 直近で使用した型は必ず除外（同一能力内）
    - 各型に文脈適合度を内部算出し、適合度を重みとしたランダム選択を行う
    - 文脈が弱い場合のみ等確率ランダムを許可
    """
    # Get available types for this ability (Spec 06: All abilities have 10 types)
    types = TRAINING_TYPES.get(ability_key, {})
    if not types:
        return 1  # Default to type 1

    available_types = sorted(list(types.keys()))  # Ensure sorted: 1-10
    
    # Spec 06 - ②: Exclude recently used types
    if exclude_types:
        available_types = [t for t in available_types if t not in exclude_types]
    
    # If no types available after exclusion, fall back to all types
    if not available_types:
        available_types = sorted(list(types.keys()))

    # If only one type available, use it
    if len(available_types) == 1:
        return available_types[0]

    # Spec 06 - ②: Context-aware selection with weight
    # For now, use random selection from available types
    # In full implementation, would calculate context fit and weight accordingly
    # Spec 05 - 4-2: Context fit prioritization can be added here
    import random
    return random.choice(available_types)

def generate_challenge_text(
    ability_id: int,
    type_def: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> str:
    """Generate natural challenge text (Spec 05 - 5: 課題文生成ルール)
    - Not textbook/exercise style
    - 1-3 sentences, natural language
    - Context-aware (inject conversation context if available)
    - No type numbers/names shown
    """
    ability = next((a for a in ABILITIES if a["id"] == ability_id), None)
    if not ability:
        return "この能力を使う場面を考えてみてください。"
    
    # Use OpenAI to generate natural challenge text based on type definition
    system_prompt = "\n".join([
        "You are generating a training challenge for AIXEL.",
        "",
        "Requirements (Spec 05 - 5):",
        "- NOT textbook/exercise style (no '次の問いに答えよ')",
        "- 1-3 sentences, natural language",
        "- Daily/work context preferred",
        "- Leave ambiguity (allow thinking space)",
        "- No single correct answer structure",
        "",
        f"Ability: {ability['name']}",
        f"Aim: {type_def.get('aim', '')}",
        f"Direction: {type_def.get('direction', '')}",
        "",
        "Generate a natural, conversational challenge that creates a situation",
        "where this thinking ability would be used."
    ])
    
    user_prompt = "自然な日本語で、この能力を使う場面を作る課題文を1〜3文で生成してください。教材調・問題文調は禁止です。"
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    challenge_text = call_openai(messages)
    
    if not challenge_text:
        # Fallback: simple natural challenge
        if ability_id == 1:  # abstract
            challenge_text = "今考えていることや悩んでいることを、具体例から共通点を見つけて整理してみてください。"
        elif ability_id == 2:  # decompose
            challenge_text = "大きな目標を、小さな作業に分けて考えてみてください。"
        else:
            challenge_text = f"{ability['name']}を使う場面を考えてみてください。"
    
    return challenge_text.strip()

def get_training_challenge(
    ability_id: int,
    training_type: int = None,
    user_id: str = None,
    context: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """Get training challenge for ability (Spec 05 - 内部構造)
    Returns internal structure with generated challenge text (type info hidden from user)
    """
    ability = next((a for a in ABILITIES if a["id"] == ability_id), None)
    if not ability:
        return None
    
    ability_key = ability["key"]
    types = TRAINING_TYPES.get(ability_key, {})
    
    # Select type if not provided
    if training_type is None:
        # Spec 06 - ②: Exclude recently used types for this ability
        # In full implementation, would query Events table for recent training types
        # For now, pass empty exclude list (can be enhanced)
        exclude_types = []  # Can be populated from training history
        training_type = select_training_type(ability_key, user_id or "", context, exclude_types)
    
    type_def = types.get(training_type)
    
    if not type_def:
        # Fallback: create minimal type definition
        type_def = {
            "aim": f"{ability['name']}の使用",
            "direction": "思考操作",
            "observation_points": ["能力の観測ポイントが満たされているか"],
            "ng_directions": []
        }
    
    # Generate natural challenge text (Spec 05 - 5)
    challenge_text = generate_challenge_text(ability_id, type_def, context)
    
    return {
        "ability_id": ability_id,
        "ability_name": ability["name"],
        "type": training_type,  # Internal only, never shown to user
        "challenge": challenge_text,  # Natural language, context-aware
        "observation_points": type_def.get("observation_points", []),
        "ng_directions": type_def.get("ng_directions", [])
    }

def generate_training_feedback(
    user_input: str,
    challenge: str,
    ability_id: int,
    plan: str,
    observation_points: List[str],
    previous_state: Optional[str] = None
) -> str:
    """Generate training feedback (Spec 05 - 7: フィードバック生成ルール)
    Plan-based granularity:
    - FREE: One fact only, minimal language
    - STANDARD: Facts + supplementary explanation
    - PRO: Facts + structural explanation (reuse perspective)
    """
    ability = next((a for a in ABILITIES if a["id"] == ability_id), None)
    if not ability:
        return "能力が見つかりませんでした。"
    
    # Plan-based granularity (Spec 05 - 7)
    tier = "PRO" if plan == "PRO" else ("STANDARD" if plan == "STANDARD" else "FREE")
    
    system_prompt = "\n".join([
        "You are AIXEL's training feedback generator (Spec 05 - 内部フロー仕様).",
        "",
        "Core principles (Spec 05 - 7):",
        "- Factual observation only (事実ベース)",
        "- NO commands (命令禁止)",
        "- NO right/wrong evaluation (正誤禁止)",
        "- NO ability name exposure (能力名の明示禁止)",
        "- Detect which thinking operations were used (観測ポイントに基づく検出)",
        "",
        f"Ability (internal): {ability['name']}",
        f"Challenge: {challenge}",
        f"Observation points: {', '.join(observation_points)}",
        "",
        "Feedback granularity by plan (Spec 05 - 7):",
        "",
        "FREE:",
        "- Observe ONE fact only",
        "- Minimal language, short text",
        "- Purpose: 'あ、そういう見方もあるのか'",
        "",
        "STANDARD:",
        "- Observed facts + supplementary explanation",
        "- Why that perspective emerges (language)",
        "- Lightly touch on other possibilities",
        "- Purpose: 'この能力を使うと、こう整理できる'",
        "",
        "PRO:",
        "- Observed facts + structural explanation",
        "- Include thinking context, reuse perspective",
        "- Higher abstraction level is OK",
        "- Purpose: '自分の思考の型が見えた'",
        "",
        "Output:",
        "- No evaluation words",
        "- No commands",
        "- No ability name mention",
        "- Factual observation of thinking operations used"
    ])
    
    user_prompt = "\n".join([
        f"ユーザーの入力：",
        user_input,
        "",
        "上記の入力について、観測ポイントに基づいて、どの思考操作が使われたかを事実ベースで検出し、",
        f"プラン（{tier}）に応じた粒度でフィードバックしてください。"
    ])
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    feedback = call_openai(messages)
    
    if not feedback:
        # Fallback by plan
        if tier == "FREE":
            feedback = "観測した事実：思考操作が使われました。"
        elif tier == "STANDARD":
            feedback = "観測した事実：思考操作が使われました。\n補足：この見え方になる理由を言語化できます。"
        else:  # PRO
            feedback = "観測した事実：思考操作が使われました。\n構造説明：思考の前後関係と再利用視点が含まれています。"
    
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
        
        # Check plan restrictions (Spec 02 - 12-2: FREE only allows abilities 1-2)
        if plan == "FREE" and n not in PLANS["FREE"]["trainingAllowed"]:
            return "\n".join([
                "現在のプラン（FREE）では、トレーニング対象は以下のみです：",
                "1 抽象化能力 / 2 分解能力",
                "",
                "他の能力をトレーニングしたい場合：『変更』で STANDARD / PRO を選択できます。",
                "（トレーニングは任意です。無理に誘導はしません）"
            ])
        
        # Get training challenge (Spec 05 - context-aware type selection)
        # Spec 05 - ③: 文脈注入範囲と診断ログ参照範囲
        # トレーニング直前の会話・入力内容のみを使用（診断対象ログは注入対象に含めない）
        # Get training session context only (not diagnostic logs)
        # For now, use empty context (can be enhanced with session-specific context)
        context = None  # Spec 05 - ③: Only training session context, not diagnostic logs
        
        challenge_def = get_training_challenge(
            n,
            training_type=None,  # Auto-select based on context
            user_id=user["user_id"],
            context=context
        )
        if not challenge_def:
            return "トレーニング課題の取得に失敗しました。"
        
        # Spec 01 - ⑥: トレーニング「差分ベースのフィードバック」の差分対象
        # トレーニング開始直前の思考状態との差分を対象とする（診断時との差分は用いない）
        # Capture pre-training state for difference-based feedback
        pre_training_state = None  # Will be captured from training session start
        
        # Update state (Spec 05 - type stored internally, never shown)
        import json
        tmp["step"] = "challenge"
        tmp["ability_id"] = n
        tmp["training_type"] = challenge_def["type"]  # Internal only
        tmp["q_count"] = 0
        tmp["attempt"] = 0
        tmp["pre_training_state"] = pre_training_state  # Spec 01 - ⑥: Store for difference calculation
        user["tmp_json"] = json.dumps(tmp, ensure_ascii=False)
        user["updated_at"] = now_iso()
        db.save_user(user)
        
        # Not observed (Spec 02)
        db.log_event(
            user["user_id"], "system", "user_message", MODE["TRAINING"],
            False, text, 0, {"excluded": True, "training_ability": n}
        )
        
        # Return challenge (Spec 05 - 9: Never show type numbers/names)
        return "\n".join([
            f"【トレーニング：{challenge_def['ability_name']}】",
            "",
            "能力の簡単な説明：",
            f"{challenge_def['ability_name']}は、{get_ability_simple_explanation(n)}",
            "",
            challenge_def["challenge"],  # Natural language challenge (Spec 05 - 5)
            "",
            "回答を入力してください（質問は最大4回まで可能です）。"  # Spec 07: 最大4回
        ])
    
    # Step 2: Handle challenge input
    elif step == "challenge":
        ability_id = tmp.get("ability_id")
        q_count = tmp.get("q_count", 0)
        
        # Check if it's a question (Spec 01)
        is_question = "？" in text or "?" in text or any(kw in text for kw in ["質問", "確認", "教えて", "どういう", "意味"])
        
        # Check for mixed question+answer input (Spec 01 - 6-7)
        has_answer = any(kw in text for kw in ["例", "答え", "回答", "考え", "思う", "です", "ます", "。", "、"])
        
        if is_question and has_answer:
            # Mixed input: answer question only, ask for re-input
            import json
            tmp["q_count"] = q_count + 1
            user["tmp_json"] = json.dumps(tmp, ensure_ascii=False)
            user["updated_at"] = now_iso()
            db.save_user(user)
            
            challenge_def = get_training_challenge(ability_id, tmp.get("training_type", 1), user["user_id"])
            if challenge_def:
                # Spec 05 - 9: Never show observation points to users (internal only)
                answer = f"課題について：{challenge_def['challenge']}\n\n質問に回答しました。課題への回答を改めて入力してください。"
            else:
                answer = "課題について質問を受け付けました。課題への回答を改めて入力してください。"
            
            return answer
        
        if is_question and q_count < 4:  # Spec 07: Maximum 4 questions
            # Answer question only (Spec 01 - 6-5)
            import json
            tmp["q_count"] = q_count + 1
            user["tmp_json"] = json.dumps(tmp, ensure_ascii=False)
            user["updated_at"] = now_iso()
            db.save_user(user)
            
            # Generate question answer (Spec 01 - 6-5: answer understanding questions, not solution requests)
            challenge_def = get_training_challenge(ability_id, tmp.get("training_type", 1), user["user_id"])
            if challenge_def:
                # Spec 05 - 9: Never show observation points to users
                answer = f"課題について：{challenge_def['challenge']}"
            else:
                answer = "課題について質問を受け付けました。回答を入力してください。"
            
            return answer
        
        elif is_question and q_count >= 4:  # Spec 07: Reset after 4 questions
            # Reset challenge (Spec 01, Spec 05 - 4: Select different type)
            # Spec 05 - ②: 型切替と質問回数制限仕様との関係
            # 別設計課題に切り替える = 必ず別型を使用すること（同型での表現変更のみは不可）
            import json
            current_type = tmp.get("training_type", 1)
            # Spec 06 - ②: 型選択ルール - 直近で使用した型は必ず除外
            # Get ability key to check type history
            ability = next((a for a in ABILITIES if a["id"] == ability_id), None)
            if ability:
                ability_key = ability["key"]
                # Select different type (exclude current type)
                available_types = sorted([t for t in TRAINING_TYPES.get(ability_key, {}).keys() if t != current_type])
                if available_types:
                    # Spec 06 - ②: Context-aware selection with weight (for now, simple random from available)
                    from api.utils import random_choice
                    import random
                    new_type = random.choice(available_types) if available_types else (current_type % 10) + 1
                else:
                    # Fallback: cycle if no other types available
                    new_type = (current_type % 10) + 1
            else:
                new_type = (current_type % 10) + 1
            
            tmp["training_type"] = new_type
            tmp["q_count"] = 0
            tmp["step"] = "challenge"
            user["tmp_json"] = json.dumps(tmp, ensure_ascii=False)
            user["updated_at"] = now_iso()
            db.save_user(user)
            
            challenge_def = get_training_challenge(ability_id, tmp["training_type"], user["user_id"])
            if challenge_def:
                # Spec 05 - 9: Never mention type numbers/names
                return "\n".join([
                    "質問回数が上限に達したため、別の課題に切り替えます。",
                    "",
                    challenge_def["challenge"]  # Natural language only
                ])
        
        # Process user input (Spec 01 - 6-8: No mid-training exit, force completion)
        challenge_def = get_training_challenge(ability_id, tmp.get("training_type", 1), user["user_id"])
        if not challenge_def:
            # Spec 01 - 6-8: Switch to next challenge type instead of exiting
            import json
            tmp["training_type"] = (tmp.get("training_type", 1) % 10) + 1
            tmp["q_count"] = 0
            user["tmp_json"] = json.dumps(tmp, ensure_ascii=False)
            user["updated_at"] = now_iso()
            db.save_user(user)
            
            new_challenge = get_training_challenge(ability_id, tmp["training_type"], user["user_id"])
            if new_challenge:
                # Spec 05 - 9: Never mention type numbers
                return "\n".join([
                    "課題を切り替えます。",
                    "",
                    new_challenge["challenge"]  # Natural language only
                ])
            else:
                # Last resort: return to idle only if no challenges available
                user["mode"] = MODE["IDLE"]
                user["tmp_json"] = "{}"
                user["updated_at"] = now_iso()
                db.save_user(user)
                return "トレーニング課題の取得に失敗したため、通常モードに戻しました。"
        
        # Generate feedback (Spec 05 - 7: Plan-based granularity)
        # Spec 01 - ⑥: トレーニング「差分ベースのフィードバック」の差分対象
        # トレーニング開始直前の思考状態との差分を対象とする（診断時との差分は用いない）
        pre_training_state = tmp.get("pre_training_state")  # Captured at training start
        
        feedback = generate_training_feedback(
            text,
            challenge_def["challenge"],
            ability_id,
            plan,
            challenge_def.get("observation_points", []),  # Spec 05 - 6: Observation points
            pre_training_state  # Spec 01 - ⑥: Difference from immediately before training, not diagnosis
        )
        
        # Spec 09 追記㊿: トレーニングにおけるクレジット消費量（プラン別目安）
        # FREE: 約500クレジット相当／1回
        # STANDARD: 約700クレジット相当／1回
        # PRO: 約1,000クレジット相当／1回
        cost = 500 if plan == "FREE" else (700 if plan == "STANDARD" else 1000)
        if user.get("credits", 0) >= cost:
            user["credits"] = max(0, user["credits"] - cost)
            db.log_event(
                user["user_id"], "system", "credit_change", user["mode"],
                False, f"training_consume:{cost}", cost, {"reason": "training", "ability": ability_id}
            )
        else:
            # Spec 01 - 6-8: Not enough credits - switch challenge instead of exiting
            import json
            tmp["training_type"] = (tmp.get("training_type", 1) % 10) + 1
            tmp["q_count"] = 0
            user["tmp_json"] = json.dumps(tmp, ensure_ascii=False)
            user["updated_at"] = now_iso()
            db.save_user(user)
            
            new_challenge = get_training_challenge(ability_id, tmp["training_type"], user["user_id"])
            if new_challenge:
                # Spec 05 - 9: Never mention type numbers
                return "\n".join([
                    "クレジットが不足していますが、別の課題に切り替えます。",
                    "",
                    new_challenge["challenge"]  # Natural language only
                ])
            else:
                # Last resort: return to idle only if no challenges available
                user["mode"] = MODE["IDLE"]
                user["tmp_json"] = "{}"
                user["updated_at"] = now_iso()
                db.save_user(user)
                return "クレジットが不足し、課題の取得にも失敗したため、通常モードに戻しました。"
        
        # Final state: Return to idle with awareness point
        awareness_point = get_awareness_point(ability_id, plan)
        
        import json
        user["mode"] = MODE["IDLE"]
        user["mode_started_at"] = now_iso()
        user["tmp_json"] = "{}"
        user["updated_at"] = now_iso()
        db.save_user(user)
        
        # Generate 余韻表現 (1 sentence, no evaluation) - Spec 01 - 6-9
        yoin_expression = generate_yoin_expression(text, ability_id, plan)
        
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
            yoin_expression,  # Spec 01 - 6-9: Post-training 余韻表現
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
    """Get awareness point for daily use (Spec 01)"""
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

def generate_yoin_expression(user_input: str, ability_id: int, plan: str) -> str:
    """Generate post-training 余韻表現 (Spec 01 - 6-9)
    - 1 sentence only
    - Factual observation of current thinking state
    - No evaluation, praise, or achievement language
    - No templates - generate fresh each time
    """
    from api.openai_client import call_openai
    
    ability = next((a for a in ABILITIES if a["id"] == ability_id), None)
    if not ability:
        return "思考状態を確認しました。"
    
    system_prompt = "\n".join([
        "You are generating a post-training '余韻表現' (lingering expression) for AIXEL.",
        "",
        "Requirements:",
        "- Exactly 1 sentence",
        "- Factual observation of user's current thinking state",
        "- NO evaluation, praise, achievement, or growth language",
        "- NO templates - generate fresh expression",
        "- Simple, natural Japanese",
        "",
        "Ability: " + ability["name"],
        "User input: " + user_input[:100]
    ])
    
    user_prompt = "ユーザーの現在の思考状態を事実ベースで1文で言語化してください。評価・称賛・達成感は含めず、状態の確認のみに留めてください。"
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    result = call_openai(messages)
    
    if not result or len(result) > 100:  # Fallback if too long or failed
        return "思考状態を確認しました。"
    
    return result.strip()
