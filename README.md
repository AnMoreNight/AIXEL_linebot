# AIXEL LINE Bot

AIXEL is a LINE bot that acts as a "thinking trainer" - it observes user conversations and provides improvement suggestions only when requested, rather than automatically diagnosing or pushing recommendations.

## Overview

AIXEL is designed with the philosophy that users maintain decision rights. It:
- **Observes** normal conversations (logs are accumulated internally)
- **Does NOT** auto-diagnose or provide unsolicited feedback
- **Only** runs diagnosis when explicitly requested via the `診断` command
- Provides training and ability explanations on demand
- Uses a credit system for all AI responses (1 credit = 1 token)

## Features

### Core Features

- **Normal Chat**: Regular conversation with OpenAI (observed for diagnosis)
- **Diagnosis** (`診断`): Analyzes recent conversation patterns and suggests improvements
- **Training** (`トレーニング`): Interactive training sessions for specific thinking abilities
- **Ability Explanation** (`能力解説`): Detailed explanations of the 11 thinking abilities
- **Credit Management**: Monthly grants, purchases, and plan changes
- **Event Logging**: All interactions logged to Google Sheets

### 11 Thinking Abilities

1. **抽象化能力** (Abstract Thinking)
2. **分解能力** (Decomposition)
3. **仕様言語化能力** (Specification)
4. **文脈保持能力** (Context Maintenance)
5. **問い生成能力** (Question Generation)
6. **仮説構築能力** (Hypothesis Building)
7. **思考の一時停止能力** (Pause Thinking)
8. **メタ認知能力** (Metacognition)
9. **捨てる能力** (Discard Ability)
10. **判断基準保持能力** (Criteria Maintenance)
11. **再利用設計能力** (Reuse Design)

## Architecture

```
LINE User → LINE Bot API → FastAPI App
                              │
                              ├─→ Google Sheets (Database)
                              ├─→ OpenAI API (Chat)
                              └─→ Handlers (Business Logic)
```

### Project Structure

```
api/
├── index.py          # Main FastAPI application & LINE webhook handler
├── config.py         # Configuration constants (plans, commands, abilities)
├── database.py       # Google Sheets database operations
├── handlers.py       # Business logic (diagnosis, chat, etc.)
├── openai_client.py # OpenAI API client
└── utils.py          # Utility functions
```

## Prerequisites

- Python 3.8+
- LINE Developer Account
- Google Cloud Platform Account (for Google Sheets API)
- OpenAI API Key (optional, for chat functionality)
- Render/Heroku account (or any cloud platform for deployment)

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd code
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up Google Sheets

1. Create a new Google Sheet
2. Create 3 sheets with these exact names:
   - `Users`
   - `Events`
   - `Purchases`
3. Add header rows (see [Google Sheets Structure](#google-sheets-structure) below)
4. **Create additional sheets for Management UI** (optional, will be auto-created):
   - `AdminUsers` - Admin user accounts
   - `Incidents` - Incident management
   - `AuditLogs` - Audit trail
   - `Settings` - System settings
5. Create a Google Service Account:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select existing
   - Enable Google Sheets API
   - Create a Service Account
   - Download JSON credentials
   - Share your Google Sheet with the service account email
5. Copy the Sheet ID from the URL: `https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit`

### 4. Set up LINE Bot

1. Go to [LINE Developers Console](https://developers.line.biz/)
2. Create a new provider and channel
3. Set channel type to "Messaging API"
4. Copy Channel Access Token and Channel Secret

## Environment Variables

Create a `.env` file or set these in your deployment platform:

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot Channel Access Token | `abc123...` |
| `LINE_CHANNEL_SECRET` | LINE Bot Channel Secret | `def456...` |
| `GOOGLE_SHEET_ID` | Google Sheet ID | `1ABC...XYZ` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Service Account JSON (as string) | `{"type":"service_account",...}` |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API Key (for chat) | - |
| `OPENAI_MODEL` | OpenAI model name | `gpt-4o-mini` |
| `OPENAI_BASE_URL` | OpenAI API base URL | `https://api.openai.com/v1` |
| `MAX_LINE_SPLITS` | Max message splits for LINE | `6` |
| `TIMEZONE` | Timezone for all datetime operations | `Asia/Tokyo` |
| `JWT_SECRET_KEY` | JWT secret for admin authentication | `your-secret-key-change-in-production` |

### Example `.env` file

```env
LINE_CHANNEL_ACCESS_TOKEN=your_line_token_here
LINE_CHANNEL_SECRET=your_line_secret_here
GOOGLE_SHEET_ID=your_sheet_id_here
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"..."}
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
MAX_LINE_SPLITS=6
TIMEZONE=Asia/Tokyo
JWT_SECRET_KEY=your-secret-key-change-in-production-use-random-string
```

## Google Sheets Structure

### Sheet: `Users`

| Column | Type | Description |
|--------|------|-------------|
| `user_id` | TEXT | LINE user ID (Primary Key) |
| `plan` | TEXT | User plan (FREE/STANDARD/PRO) |
| `credits` | NUMBER | Current credit balance |
| `last_grant_yyyymm` | TEXT | Last monthly grant (YYYYMM) |
| `mode` | TEXT | Current mode (idle/training/etc.) |
| `mode_started_at` | TEXT | Mode start time (ISO) |
| `tmp_json` | TEXT | Temporary state data (JSON) |
| `created_at` | TEXT | Account creation time (ISO) |
| `updated_at` | TEXT | Last update time (ISO) |

### Sheet: `Events`

| Column | Type | Description |
|--------|------|-------------|
| `event_id` | TEXT | Unique event ID (UUID) |
| `timestamp` | TEXT | Event time (ISO) |
| `user_id` | TEXT | LINE user ID |
| `channel` | TEXT | Channel (line/web/system) |
| `type` | TEXT | Event type |
| `mode` | TEXT | User mode at event time |
| `is_observed` | TEXT | Observed for diagnosis (true/false) |
| `text` | TEXT | Message/event text |
| `token_est` | NUMBER | Estimated token count |
| `meta_json` | TEXT | Additional metadata (JSON) |

### Sheet: `Purchases`

| Column | Type | Description |
|--------|------|-------------|
| `purchase_id` | TEXT | Unique purchase ID (UUID) |
| `user_id` | TEXT | LINE user ID |
| `product_type` | TEXT | Product type |
| `pack` | TEXT | Pack size (S/M/L) |
| `amount_yen_ex_tax` | NUMBER | Price excluding tax |
| `tax` | NUMBER | Tax amount |
| `amount_yen_in_tax` | NUMBER | Total price with tax |
| `credits` | NUMBER | Credits granted |
| `status` | TEXT | Purchase status |
| `created_at` | TEXT | Purchase time (ISO) |
| `updated_at` | TEXT | Last update time (ISO) |

## Commands

All commands require **exact match** (case-sensitive):

| Command | Description |
|---------|-------------|
| `診断` | Run diagnosis on recent conversations |
| `トレーニング` | Start training for a thinking ability |
| `能力解説` | View explanation of an ability |
| `クレジット` | Check credit balance |
| `変更` | Change subscription plan |
| `購入` | Purchase additional credits |
| `説明` / `使い方` / `ヘルプ` | Show help message |

## Plans & Credits

### Subscription Plans

| Plan | Monthly Grant | Training Access |
|------|--------------|-----------------|
| FREE | 5,000 credits | Abilities 1-2 only |
| STANDARD | 65,000 credits | All abilities |
| PRO | 230,000 credits | All abilities |

### Credit Packs (Additional Purchase)

| Pack | Price (ex-tax) | Credits |
|------|----------------|---------|
| S | ¥2,000 | 50,000 |
| M | ¥5,000 | 125,000 |
| L | ¥10,000 | 250,000 |

*Tax rate: 10% (Japan)*

## Local Development

### Run the application

```bash
# Using uvicorn directly
uvicorn api.index:app --host 0.0.0.0 --port 8000 --reload

# Or using the Procfile command
python -m uvicorn api.index:app --host 0.0.0.0 --port $PORT
```

### Test webhook locally

Use [ngrok](https://ngrok.com/) or similar tool to expose your local server:

```bash
ngrok http 8000
```

Then set the webhook URL in LINE Developers Console to: `https://your-ngrok-url.ngrok.io/api/callback`

## Management UI

A separate Next.js Management UI is available in the `management/` directory. See `management/README.md` for details.

### Creating Admin Users

1. Navigate to `/signup` in the Management UI
2. Fill in display name, email, and password
3. **First user** automatically becomes `OWNER`
4. **Subsequent users** default to `AUDITOR_VIEWER`

**Roles**: `OWNER`, `INCIDENT_RESPONDER`, `BILLING_ADMIN`, `ANALYST`, `AUDITOR_VIEWER`

### Admin API Endpoints

The admin API endpoints are available at `/api/admin/*`:
- `POST /api/admin/auth/signup` - Create admin account (first user = OWNER)
- `POST /api/admin/auth/login` - Admin login
- `GET /api/admin/auth/me` - Get current admin
- `GET /api/admin/dashboard/stats` - Dashboard statistics
- `GET /api/admin/users/lookup` - Search users
- `GET /api/admin/users/{user_id}` - Get user details
- `GET /api/admin/incidents` - List incidents
- `GET /api/admin/billing/credit-ledger` - Credit ledger
- `GET /api/admin/audit` - Audit logs
- And more... (see `api/admin_routes.py`)

See `API_STRUCTURE.md` for detailed API documentation, `GOOGLE_SHEETS_SETUP.md` for database schema, and `API_TESTING_GUIDE.md` for testing instructions.

## Deployment

### Render

1. Connect your GitHub repository to Render
2. Create a new Web Service
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `python -m uvicorn api.index:app --host 0.0.0.0 --port $PORT`
5. Add all required environment variables
6. Deploy

The `render.yaml` file is included for easy setup.

### Other Platforms

The application can be deployed to any platform that supports Python:
- Heroku
- Railway
- AWS Lambda (with modifications)
- Google Cloud Run
- Azure App Service

## API Endpoints

### `GET /`
Health check endpoint.

**Response:**
```json
{"status": "ok"}
```

### `POST /api/callback`
LINE webhook endpoint for receiving events.

**Headers:**
- `X-Line-Signature`: LINE signature for verification

**Body:** LINE webhook event JSON

## How It Works

### Normal Conversation Flow

1. User sends a message
2. System checks if user exists (creates if new)
3. Monthly credit grant is checked/processed
4. Message is logged as "observed" (for diagnosis)
5. OpenAI generates response
6. Credits are consumed (1 credit = 1 token)
7. Response is sent to user

### Diagnosis Flow

1. User sends `診断` command
2. System retrieves last 10 observed user messages
3. Heuristic analysis is performed
4. Results show:
   - Most used thinking ability
   - Abilities that could have been used but weren't
   - Observations and suggestions
5. No scoring or ranking (philosophy: no pressure)

### Training Flow

1. User sends `トレーニング` command
2. System prompts for ability number (1-11)
3. Plan restrictions are checked (FREE only allows 1-2)
4. Challenge is presented
5. User can ask questions (up to 4 times)
6. User provides answer
7. Feedback is given (no scoring, just observations)
8. Returns to idle mode

## Philosophy

AIXEL follows these core principles:

- **No Auto-Diagnosis**: Only diagnoses when explicitly requested
- **No Scoring**: No numbers, levels, or rankings
- **No Pressure**: Users maintain full decision rights
- **Observation Only**: Normal conversations are observed but not analyzed automatically
- **Credit-Based**: All AI responses consume credits (no unlimited usage)

## Troubleshooting

### Database Connection Issues

- Verify `GOOGLE_SHEET_ID` is correct
- Ensure `GOOGLE_SERVICE_ACCOUNT_JSON` is valid JSON string
- Check that service account email has access to the sheet
- Verify Google Sheets API is enabled

### LINE Webhook Issues

- Check `LINE_CHANNEL_SECRET` matches your channel
- Verify webhook URL is correct and accessible
- Ensure HTTPS is used (required by LINE)

### OpenAI API Issues

- Verify `OPENAI_API_KEY` is set correctly
- Check API quota/limits
- Ensure model name is correct

## License

Proprietary - All rights reserved
