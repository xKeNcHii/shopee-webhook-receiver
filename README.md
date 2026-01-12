# Shopee Webhook Integration

A production-ready Shopee Open Platform webhook integration system. This project handles high-volume webhook events from Shopee, processes them asynchronously, sends real-time notifications to Telegram, and synchronizes order data to Google Sheets.

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Supported-blue.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## Features

- **Split Architecture** - Decoupled Listener (`shopee_api`) and Processor (`shopee_worker`) services for high reliability.
- **Webhook Forwarding** - Forwards webhooks to the worker service with enriched order data.
- **Complete Order Data** - Automatic API fetch for comprehensive order details (Income, Escrow, Items).
- **Google Sheets Sync** - Automatically upserts order data into Google Sheets with financial breakdown.
- **Real-time Notifications** - Optional Telegram notifications for order updates.
- **Auto Token Refresh** - Seamless handling of Shopee API token expiration.
- **Smart Messaging** - Intelligent message splitting for large orders (>4000 chars).
- **Health Monitoring** - Built-in health checks for orchestration systems.
- **Topic-Based Alerts** - Automatically creates Telegram Forum Topics for different event types.
- **Dashboard** - Web dashboard for monitoring webhooks and configuration.

## Architecture

The system is split into two microservices:

1.  **Listener (`shopee_api`)**: Receives webhooks, validates signatures, and handles immediate notifications (Telegram).
2.  **Worker (`shopee_worker`)**: Background processor that handles heavy logic (Google Sheets sync).

```mermaid
graph LR
    A["Shopee<br/>Platform"] -->|Webhook| B["Listener<br/>(shopee_api)"]
    B -->|Notify| C["Telegram<br/>Bot"]
    B -->|Forward| D["Worker<br/>(shopee_worker)"]
    D -->|Fetch| E["Shopee<br/>API"]
    D -->|Sync| F["Google<br/>Sheets"]

    style A fill:#d32f2f,stroke:#000,color:#fff
    style B fill:#1976d2,stroke:#000,color:#fff
    style C fill:#0097a7,stroke:#000,color:#fff
    style D fill:#7b1fa2,stroke:#000,color:#fff
    style E fill:#f57c00,stroke:#000,color:#fff
    style F fill:#0f9d58,stroke:#000,color:#fff
```

## Webhook Processing Flow

```mermaid
sequenceDiagram
    participant Shopee as Shopee Platform
    participant Listener as Listener (API)
    participant Telegram as Telegram Bot
    participant Worker as Worker (Processor)
    participant Sheets as Google Sheets

    Shopee->>Listener: POST /webhook/shopee
    Listener->>Shopee: HTTP 200 OK (Immediately)
    
    par Notify Telegram
        Listener->>Telegram: Send formatted alert
    and Forward to Worker
        Listener->>Worker: POST /webhook/process
    end

    Worker->>Worker: Fetch full order details
    Worker->>Sheets: Upsert Order & Items
```

## Quick Start

### Prerequisites

- **Docker & Docker Compose** (Recommended)
- Or Python 3.11+ with pip

**Required Credentials:**
- Shopee Partner ID, Key, Shop ID
- Shopee Access & Refresh Tokens
- Google Service Account (for Sheets)
- Telegram Bot Token & Chat ID (Optional)

### Setup

#### 1. Clone Repository
```bash
git clone https://github.com/yourusername/shopee-webhook.git
cd shopee-webhook
```

#### 2. Configure Credentials
```bash
cp .env.example .env
# Edit .env with your credentials
nano .env
```

#### 3. Run with Docker
```bash
docker-compose up -d --build
```

- **Listener (API)**: `http://localhost:8000`
- **Worker**: `http://localhost:9000`

#### Or Run Locally

**Terminal 1 (Listener):**
```bash
# Windows
$env:PYTHONPATH="src"; python -m shopee_api.main

# Linux/Mac
export PYTHONPATH=src; python -m shopee_api.main
```

**Terminal 2 (Worker):**
```bash
# Windows
$env:PYTHONPATH="src"; python -m shopee_worker.main

# Linux/Mac
export PYTHONPATH=src; python -m shopee_worker.main
```

## Configuration

### Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `PARTNER_ID` | Yes | Shopee Partner ID | `2011563` |
| `PARTNER_KEY` | Yes | Partner Key (for signing) | `abc123def456` |
| `SHOP_ID` | Yes | Your Shop ID | `443972786` |
| `ACCESS_TOKEN` | Yes | Shopee API Access Token | `eyJhbGc...` |
| `REFRESH_TOKEN` | Yes | Shopee API Refresh Token | `eyJhbGc...` |
| `WEBHOOK_PARTNER_KEY` | Yes | Webhook validation key | `webhook_key_xyz` |
| `FORWARD_WEBHOOK_URL` | Yes | URL to forward to Worker | `http://localhost:9000/webhook/process` |
| `TELEGRAM_BOT_TOKEN` | No | Telegram Bot Token | `123456:ABC-DEF` |
| `TELEGRAM_CHAT_ID` | No | Telegram Channel/Chat ID | `-1001234567890` |
| `GOOGLE_CREDENTIALS_JSON`| Yes | Path to Google Service Account | `config/google_credentials.json` |
| `SPREADSHEET_ID` | Yes | Google Sheet ID | `1BxiMvs...` |

## API Endpoints

### Listener Service (Port 8000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/webhook/shopee` | Main webhook receiver for Shopee. |
| `GET` | `/health` | Health check (checks config & env). |
| `GET` | `/dashboard` | Monitoring dashboard. |
| `GET` | `/docs` | Swagger UI documentation. |

### Worker Service (Port 9000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/webhook/process` | Receives forwarded events from Listener. |
| `GET` | `/health` | Health check (checks Google Sheets). |

## Webhook Event Support

This system is **extensible for all Shopee webhook event codes**.

**Default Behavior:**
*   **Configured Events:** Triggers full order fetching (API), rich Telegram notifications, and Google Sheets synchronization.
*   **Unconfigured Events:** Triggers a **Telegram Notification ONLY** (basic raw data) and skips Google Sheets sync.

| Code | Event Type | Status | Processing Flow |
|------|------------|--------|-----------------|
| **3** | Order Status Update | ✅ Configured | Fetch Details -> Rich Telegram -> Sheets Sync |
| **4** | Tracking Number | ✅ Configured | Fetch Details -> Rich Telegram -> Sheets Sync |
| **8** | Stock Change | ⚠️ Default | Basic Telegram Notification Only |
| **15** | Shipping Doc | ⚠️ Default | Basic Telegram Notification Only |

### 🔧 How to Configure New Events

To enable full processing (Order Fetch + Sheets Sync) for other event codes:

1.  Open `src/shopee_api/config/constants.py`.
2.  Add the Shopee Event Code to the `ORDER_EVENT_CODES` list:

```python
# src/shopee_api/config/constants.py

# Add new codes here (e.g., 10 = Order Cancellation)
ORDER_EVENT_CODES = [3, 4, 10] 
```

The system automatically:
- Creates **Telegram Forum Topics** for *every* event code received.
- Logs all events to `logs/webhook_events_*.json`.
- Fetches full order details only for **CONFIGURED events** (Default: 3 & 4).

## Telegram Message Format

Messages are automatically split into two clear sections:

### Section 1: Webhook Event
What Shopee called back:
- Event code and name
- Shop ID and timestamp
- Event data (ordersn, status, update_time)

### Section 2: Order Details
Complete order information from API:
- **Order Info**: ID, status, created/updated times
- **Buyer**: Username and contact info
- **Financial**: Amount, currency, payment method
- **Items**: All items with SKUs, variations, quantities

## Troubleshooting

### API Returns 403 Forbidden
**Issue**: Token validation failed or invalid `access_token`.
**Solution**:
1. App auto-refreshes tokens - wait a moment.
2. Verify `PARTNER_ID`, `PARTNER_KEY`, `SHOP_ID` are correct.
3. Ensure tokens haven't expired on Shopee console.

### No Telegram Messages
**Issue**: No notifications in Telegram.
**Solution**:
1. Verify `TELEGRAM_BOT_TOKEN` format.
2. Check `TELEGRAM_CHAT_ID` is valid (e.g., `-1001234567890`).
3. Ensure bot has permission to post in the channel.

### Worker Not Syncing to Sheets
**Issue**: Orders not appearing in Google Sheets.
**Solution**:
1. Check `GOOGLE_CREDENTIALS_JSON` path is correct.
2. Ensure Service Account email has **Editor** access to the Sheet.
3. Check worker logs: `docker-compose logs shopee-worker`.

## Deployment

### Docker Production

```bash
# Build and run
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Health Monitoring

Containers include automated health checks:
- **Interval**: Every 30 seconds
- **Retries**: 3 failures before unhealthy

Check status:
```bash
docker-compose ps
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.