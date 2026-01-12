# SalonAI LINE Bot - 完全ドキュメント

AI搭載FAQ応答、Googleカレンダー連携、自動リマインダーシステムを備えたサロン予約管理LINEボットの包括的なドキュメントです。

## 目次

1. [概要](#概要)
2. [機能](#機能)
3. [アーキテクチャ](#アーキテクチャ)
4. [前提条件](#前提条件)
5. [インストール・セットアップ](#インストールセットアップ)
6. [環境変数](#環境変数)
7. [デプロイメント](#デプロイメント)
8. [APIエンドポイント](#apiエンドポイント)
9. [設定ファイル](#設定ファイル)
10. [ユーザーフロー](#ユーザーフロー)
11. [トラブルシューティング](#トラブルシューティング)
12. [メンテナンス](#メンテナンス)

## 概要

SalonAI LINE Botは以下の機能を提供する高度な予約管理システムです：

- **AI搭載FAQシステム**: RAG（検索拡張生成）+ ChatGPT統合
- **予約管理**: Googleカレンダー同期による予約の作成、変更、キャンセル
- **マルチプラットフォーム通知**: 管理者向けSlack・LINE通知
- **ユーザー同意管理**: GDPR準拠のユーザー同意追跡
- **包括的ログ**: 全インタラクションのGoogleスプレッドシート記録

## 機能

### 🤖 AI搭載FAQシステム

- **RAGシステム**: KBデータとのキーワードベースマッチング
- **ChatGPT統合**: 自然言語応答
- **フォールバックシステム**: API利用不可時の直接KB応答
- **テンプレート処理**: KB事実からの動的回答生成

### 📅 予約管理

- **予約作成**: 日付、時間、サービス、スタッフ選択
- **予約変更**: 日付、時間、サービス、スタッフの変更
- **予約キャンセル**: カレンダー同期による完全キャンセル
- **再予約**: キャンセルと新規予約を一つのフローで実行
- **空き状況確認**: リアルタイムスロット空き状況
- **競合防止**: 重複予約と時間競合の防止

### 🔔 通知システム

- **マルチプラットフォーム**: Slack・LINE通知
- **設定可能**: 環境変数による通知方法選択
- **管理者通知**: ユーザーログイン、予約確認、変更、キャンセル

### 📊 データ管理

- **Googleスプレッドシート統合**: 包括的ログとユーザー管理
- **ユーザー追跡**: セッション管理と同意追跡
- **予約履歴**: 完全な予約ライフサイクル追跡
- **分析**: 処理時間メトリクス付きメッセージログ

## アーキテクチャ

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   LINEユーザー   │◄──►│   LINE Bot API   │◄──►│  FastAPI アプリ  │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                                        │
                       ┌────────────────────────────────┼────────────────────────────────┐
                       │                                │                                │
                       ▼                                ▼                                ▼
              ┌─────────────────┐              ┌─────────────────┐              ┌─────────────────┐
              │ Googleカレンダー │              │   Googleスプレッドシート │              │   通知システム   │
              │   （予約管理）   │              │   （ログ記録）   │              │  （Slack/LINE） │
              └─────────────────┘              └─────────────────┘              └─────────────────┘
                       │                                │                                │
                       ▼                                ▼                                ▼
              ┌─────────────────┐              ┌─────────────────┐              ┌─────────────────┐
              │   OpenAI API    │              │                 │              │   ユーザーセッション│
              │   （ChatGPT）   │              │                 │              │   管理          │
              └─────────────────┘              └─────────────────┘              └─────────────────┘
```

## 前提条件

### 必要なアカウント・サービス

1. **LINE Developerアカウント**: LINE Bot認証情報用
2. **Google Cloud Platform**: カレンダー・スプレッドシートAPI用
3. **OpenAIアカウント**: ChatGPT統合用（オプション）
4. **Slackワークスペース**: 管理者通知用（オプション）
5. **Renderアカウント**: デプロイメント用（または任意のクラウドプラットフォーム）

### 必要な認証情報

- LINE Channel Access Token
- LINE Channel Secret
- Google Service Account JSON（カレンダー + スプレッドシート）
- Google Sheet ID
- OpenAI API Key（オプション）
- Slack Webhook URL（オプション）

## インストール・セットアップ

### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd salonLineBot
```

### 2. 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 3. Google Cloudセットアップ

#### カレンダーAPI

1. [Google Cloud Console](https://console.cloud.google.com/)にアクセス
2. 新しいプロジェクトを作成または既存を選択
3. Google Calendar APIを有効化
4. サービスアカウントを作成
5. JSON認証情報をダウンロード
6. カレンダーをサービスアカウントメールと共有

#### スプレッドシートAPI

1. 同じプロジェクトでGoogle Sheets APIを有効化
2. 同じサービスアカウントを使用
3. ログ用のGoogleスプレッドシートを作成
4. スプレッドシートをサービスアカウントメールと共有
5. URLからSheet IDをコピー

### 4. LINE Botセットアップ

1. [LINE Developers Console](https://developers.line.biz/)にアクセス
2. 新しいプロバイダーとチャンネルを作成
3. チャンネルタイプを「Messaging API」に設定
4. Channel Access TokenとChannel Secretをコピー
5. ウェブフックURLを設定（デプロイ後）

### 5. OpenAIセットアップ（オプション）

1. [OpenAI Platform](https://platform.openai.com/)にアクセス
2. APIキーを作成
3. 請求情報を追加

## 環境変数

### 必須変数

| 変数名                          | 説明                          | 例                                 |
| ------------------------------- | ----------------------------- | ---------------------------------- |
| `LINE_CHANNEL_ACCESS_TOKEN`   | LINE Bot Channel Access Token | `abc123...`                      |
| `LINE_CHANNEL_SECRET`         | LINE Bot Channel Secret       | `def456...`                      |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Google Service Account JSON   | `{"type": "service_account"...}` |
| `GOOGLE_SHEET_ID`             | ログ用Google Sheet ID         | `1ABC...XYZ`                     |

### オプション変数

| 変数名                                | 説明                     | デフォルト           | 例                              |
| ------------------------------------- | ------------------------ | -------------------- | ------------------------------- |
| `OPENAI_API_KEY`                    | ChatGPT用OpenAI APIキー  | None                 | `sk-...`                      |
| `SLACK_WEBHOOK_URL`                 | SlackウェブフックURL     | None                 | `https://hooks.slack.com/...` |
| `LINE_CHANNEL_ACCESS_TOKEN_MANAGER` | 管理者通知用LINEトークン | None                 | `abc123...`                   |
| `NOTIFICATION_METHOD`               | 通知方法                 | `slack`            | `slack`, `line`, `both`   |
| `GOOGLE_CALENDAR_ID`                | GoogleカレンダーID       | プライマリカレンダー | `primary`                     |

### 環境変数セットアップ

#### ローカル開発

`.env`ファイルを作成：

```env
LINE_CHANNEL_ACCESS_TOKEN=your_line_token
LINE_CHANNEL_SECRET=your_line_secret
GOOGLE_SERVICE_ACCOUNT_JSON={"type": "service_account", ...}
GOOGLE_SHEET_ID=your_sheet_id
OPENAI_API_KEY=your_openai_key
SLACK_WEBHOOK_URL=your_slack_webhook
NOTIFICATION_METHOD=slack
```

#### 本番環境（Render）

Renderダッシュボードで環境変数を追加：

1. サービス設定に移動
2. 「Environment」タブに移動
3. 各変数とその値を追加

## デプロイメント

### Renderデプロイメント

1. **リポジトリ接続**:

   - [Render Dashboard](https://dashboard.render.com)にアクセス
   - 「New +」→「Web Service」をクリック
   - GitHubを接続し、リポジトリを選択
2. **サービス設定**:

   - **名前**: `salon-line-bot`
   - **環境**: `Python 3`
   - **ビルドコマンド**: `pip install -r requirements.txt`
   - **開始コマンド**: `python -m uvicorn api.index:app --host 0.0.0.0 --port $PORT`
3. **環境変数設定**:

   - すべての必須環境変数を追加
   - JSON値が正しくフォーマットされていることを確認
4. **デプロイ**:

   - 「Create Web Service」をクリック
   - デプロイ完了を待つ
5. **ウェブフック設定**:

   - サービスURLをコピー
   - LINE Developers ConsoleでウェブフックURLを設定: `https://your-service.onrender.com/api/callback`

### 代替デプロイメントプラットフォーム

#### Heroku

```bash
# Heroku CLIをインストール
# Procfileを作成（既に含まれています）
# デプロイ
git push heroku main
```

#### Railway

```bash
# Railway CLIをインストール
# リポジトリを接続
# 環境変数を設定
# 自動デプロイ
```

## APIエンドポイント

### コアエンドポイント

| エンドポイント           | メソッド | 説明                         |
| ------------------------ | -------- | ---------------------------- |
| `/`                    | GET      | ヘルスチェック               |
| `/api/callback`        | POST     | LINE Botウェブフック         |

### ウェブフックエンドポイント詳細

#### `/api/callback` (POST)

- **目的**: LINE Botイベント受信
- **認証**: LINE署名検証
- **処理イベント**:
  - `MessageEvent`: テキストメッセージ、フォローイベント
  - `FollowEvent`: ユーザーがボットを友達追加
  - `PostbackEvent`: ボタンインタラクション

## 設定ファイル

### `/api/data/kb.json`

サロン情報を含むナレッジベース：

```json
{
  "キー": "SalonAI 表参道店",
}
```

### `/api/data/services.json`

サービスとスタッフ設定：

```json
{
  "services": {
    "カット": {
      "duration": 60,
      "price": 5000
    }
  },
  "staff": {
    "あやか": {
      "color_id": "1",
      "email_env": "STAFF_AYAKA_EMAIL"
    }
  }
}
```

### `/api/data/faq_data.json`

FAQ質問とテンプレート：

```json
{
  "question": "営業時間は？",
  "required_elements": ["BUSINESS_HOURS_WEEKDAY"],
  "answer_template": "平日は{BUSINESS_HOURS_WEEKDAY}です。",
  "category": "基本情報"
}
```

### `/api/data/keywords.json`

インテント検出キーワード：

```json
{
  "intent_keywords": {
    "reservation": ["予約", "予約したい"],
    "modify": ["変更", "変更したい"],
    "cancel": ["キャンセル", "キャンセルしたい"]
  }
}
```

## ユーザーフロー

### 1. 新規ユーザーフロー

```
ユーザーがボットを友達追加 → FollowEvent → 同意画面 → ユーザーが同意 → ウェルカムメッセージ
```

### 2. 予約フロー

```
ユーザー: "予約したい" → 日付選択 → 時間選択 → サービス選択 → スタッフ選択 → 確認 → カレンダーイベント作成
```

### 3. 変更フロー

```
ユーザー: "予約変更したい" → 予約選択 → フィールド選択（日付/時間/サービス/スタッフ） → 新選択 → 確認 → カレンダー更新
```

### 4. FAQフロー

```
ユーザー: "営業時間は？" → RAG検索 → KB事実 → テンプレート処理 → 応答
```

### 5. 再予約フロー

```
ユーザー: "複数項目変更したい" → 確認 → 現在の予約をキャンセル → 新規予約作成
```

## トラブルシューティング

### よくある問題

#### 1. "Error loading KB data: No such file or directory"

**原因**: 異なる環境でのファイルパス問題
**解決方法**:

- `/api/data/`にファイルが存在することを確認
- 大文字小文字の区別を確認（Linux vs Windows）
- ファイル権限を確認

#### 2. "Google Calendar API error"

**原因**: 認証または権限問題
**解決方法**:

- サービスアカウントJSONフォーマットを確認
- サービスアカウントとのカレンダー共有を確認
- Calendar APIが有効化されていることを確認

#### 3. "LINE webhook verification failed"

**原因**: 不正なウェブフックURLまたは署名
**解決方法**:

- ウェブフックURLフォーマットを確認
- LINE_CHANNEL_SECRETを確認
- HTTPSが使用されていることを確認

#### 4. "通知が送信されない"

**原因**: 無効な認証情報またはウェブフックURL
**解決方法**:

- SlackウェブフックURLを確認
- LINE Channel Access Tokenを確認
- 通知エンドポイントをテスト

### デバッグモード

デバッグログを有効化：

```python
# api/index.pyで
DEBUG = True
```

### ログ分析

Googleスプレッドシートで以下を確認：

- メッセージログ（Sheet1）
- 予約データ（Reservationsシート）
- ユーザーデータ（Usersシート）

## メンテナンス

### 定期タスク

```

```

1. **ログ監視**: Googleスプレッドシートでエラーを確認
2. **KBデータ更新**: サロン情報を最新に保つ
3. **通知テスト**: Slack/LINE通知が動作することを確認
4. **リマインダー確認**: 日次リマインダーが送信されることを確認
5. **予約確認**: カレンダー同期の正確性を監視

### 更新

1. **コード更新**: Git pushでデプロイ
2. **設定更新**: JSONファイルを修正
3. **環境変数**: デプロイメントプラットフォームで更新
4. **依存関係**: requirements.txtを更新

### バックアップ

1. **Googleスプレッドシート**: 定期的にエクスポート
2. **設定ファイル**: バージョン管理
3. **環境変数**: 安全に文書化
4. **カレンダーデータ**: Googleカレンダーバックアップ

### パフォーマンス監視

- **応答時間**: API応答時間を監視
- **エラー率**: 失敗リクエストを追跡
- **ユーザーエンゲージメント**: メッセージパターンを分析
- **予約精度**: カレンダー同期を検証

## サポート

技術サポートの場合：

1. Googleスプレッドシートのログを確認
2. デプロイメントログのエラーメッセージを確認
3. 個別コンポーネントをテスト
4. 環境変数を確認
5. APIクォータと制限を確認

## ライセンス

このプロジェクトはプロプライエタリソフトウェアです。全著作権所有。
