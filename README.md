# Shopee Webhook Forwarder

Receives Shopee webhooks, fetches full order details, and forwards to your custom service with optional Telegram notifications.

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Supported-blue.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## Features

- **Webhook Forwarding** - Forwards webhooks to your custom service with enriched order data
- **Complete Order Data** - Automatic API fetch for comprehensive order details
- **Real-time Notifications** - Optional Telegram notifications for order updates
- **Auto Token Refresh** - Seamless handling of Shopee API token expiration
- **Smart Messaging** - Intelligent message splitting for large orders (>4000 chars)
- **Health Monitoring** - Built-in health checks for orchestration systems
- **Organized Logs** - Date and session-based logging with Singapore timezone
- **No Database** - Stateless forwarder, delegates persistence to your custom service

## Known Issues

### Webhook Signature Validation

The HMAC-SHA256 signature validation is currently **non-functional**. After extensive troubleshooting, the signature validation cannot be made to work with Shopee's webhook implementation.

**Current behavior:**
- System operates with `DEBUG_WEBHOOK=1` environment variable
- All webhooks are accepted without signature verification
- Full functionality maintained for order processing and notifications

**Security note:** This system should only be deployed in trusted environments or behind additional authentication layers (e.g., firewall rules, reverse proxy authentication).

## Architecture

```mermaid
graph LR
    A["Shopee<br/>Platform"] -->|Webhook| B["FastAPI<br/>Server"]
    B -->|Receive| C["Webhook<br/>Handler"]
    C -->|Process| D["Shopee<br/>API Client"]
    D -->|Fetch| E["Order<br/>Details"]
    E -->|Forward| F["Custom<br/>Service"]
    E -->|Notify| G["Telegram<br/>Bot"]

    style A fill:#d32f2f,stroke:#000,color:#fff
    style B fill:#1976d2,stroke:#000,color:#fff
    style C fill:#7b1fa2,stroke:#000,color:#fff
    style D fill:#00796b,stroke:#000,color:#fff
    style E fill:#f57c00,stroke:#000,color:#fff
    style F fill:#c2185b,stroke:#000,color:#fff
    style G fill:#0097a7,stroke:#000,color:#fff
```

## Webhook Processing Flow

```mermaid
sequenceDiagram
    participant Shopee as Shopee Platform
    participant API as FastAPI Server
    participant OrderService as Order Service
    participant ShopeeAPI as Shopee API
    participant CustomService as Custom Service
    participant Telegram as Telegram Bot

    Shopee->>API: POST /webhook/shopee
    API->>OrderService: Process webhook
    OrderService->>ShopeeAPI: GET order details
    ShopeeAPI-->>OrderService: Order data

    OrderService-->>API: Return order info

    par Forward to Custom Service
        API->>CustomService: POST order data
        CustomService-->>API: Acknowledged
    and Send Telegram Notification
        API->>Telegram: Format & send notification
        Telegram-->>Telegram: Split if >4000 chars
    end

    API->>Shopee: HTTP 200 OK
```

## Quick Start

### Prerequisites

- Docker & Docker Compose (recommended)
- Or Python 3.11+ with pip

**Required Credentials:**
- Shopee Partner ID, Key, Shop ID
- Shopee Access & Refresh Tokens
- Telegram Bot Token & Chat ID

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
docker-compose up -d
```

Server runs on `http://localhost:8000`

#### Or Run Locally
```bash
pip install -r requirements.txt
python -m uvicorn shopee_webhook.main:app --host 0.0.0.0 --port 8000
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
| `FORWARD_WEBHOOK_URL` | No | URL to forward webhooks to | `http://localhost:9000/orders` |
| `TELEGRAM_BOT_TOKEN` | No | Telegram Bot Token (optional) | `123456:ABC-DEF` |
| `TELEGRAM_CHAT_ID` | No | Telegram Channel/Chat ID (optional) | `-1001234567890` |
| `LOG_LEVEL` | No | Logging level | `INFO` (default) |

### Auto-Generated Files

These are created automatically on first run:

```
config/
  ├── shopee_tokens.json        # Cached tokens with expiration
  └── telegram_topics.json      # Event code → Topic ID mappings
```

## API Endpoints

### POST `/webhook/shopee`
Receives webhook events from Shopee platform.

**Headers:**
```
X-Shopee-Signature: <HMAC-SHA256 signature>
Content-Type: application/json
```

**Response:** `200 OK` (empty body as required by Shopee)

---

### GET `/health`
Health check endpoint for monitoring.

**Response:**
```json
{
  "status": "healthy|degraded",
  "service": "shopee-webhook-forwarder",
  "checks": {
    "config": {
      "tokens_file": "ok|missing",
      "topics_file": "ok|not_created_yet"
    },
    "environment": {
      "partner_id": "ok|missing",
      "shop_id": "ok|missing",
      "telegram_bot_token": "ok|missing",
      "telegram_chat_id": "ok|missing"
    },
    "forwarding": "enabled|disabled"
  }
}
```

## Webhook Event Support

This system is **extensible for all Shopee webhook event codes**. It dynamically handles any event code sent by Shopee.

**Common event codes** (examples):

| Code | Event Type | Processing |
|------|------------|------------|
| 3 | Order Status Update | Full order fetch + forwarding + Telegram notification |
| 4 | Order Tracking Number | Full order fetch + forwarding + Telegram notification |
| 8 | Reserved Stock Change | Event forwarding + Telegram notification |
| 15 | Shipping Document Status | Event forwarding + Telegram notification |
| 25 | Booking Shipping Document | Event forwarding + Telegram notification |

The system automatically:
- Creates Telegram forum topics for each event code
- Logs all events to `logs/webhook_events_YYYY-MM-DD.json`
- Fetches full order details for event codes 3 and 4
- Forwards all events to your custom service (if configured)
- Sends formatted Telegram notifications (if configured)

**Note:** Enable specific event codes in your Shopee Partner Console webhook settings.

## Telegram Message Format

Messages are automatically split into two clear sections:

### Section 1: Webhook Event
What Shopee called back:
- Event code and name
- Shop ID and timestamp
- Event data (ordersn, status, update_time, etc.)

### Section 2: Order Details
Complete order information from API:
- **Order Info**: ID, status, created/updated times
- **Buyer**: Username and contact info
- **Shipping**: Address details (if available)
- **Financial**: Amount, currency, payment method
- **Shipping Carrier**: Logistics provider
- **Items**: All items with SKUs, variations, quantities

### Message Splitting
If the message exceeds 4000 characters:
- Automatically splits into multiple parts
- Each part is sent sequentially to same Telegram topic
- Preserves formatting and readability

## Forwarded Payload Format

When `FORWARD_WEBHOOK_URL` is configured, the forwarder sends:

```json
{
  "event": {
    "code": 3,
    "shop_id": 443972786,
    "timestamp": 1704337899,
    "data": {
      "ordersn": "2601033YS140TT",
      "status": "READY_TO_SHIP"
    }
  },
  "order_data": {
    "order_id": "2601033YS140TT",
    "shop_id": 443972786,
    "status": "READY_TO_SHIP",
    "buyer_username": "buyer123",
    "items": [
      {
        "item_name": "Product Name",
        "item_sku": "SKU123",
        "model_sku": "SKU123-VARIANT",
        "variation_name": "Size L",
        "quantity": 2,
        "total_amount": 99.90
      }
    ],
    "total_amount": 99.90,
    "currency": "SGD",
    "create_time": 1704337899,
    "update_time": 1704337899
  }
}
```

Your custom service should handle this POST request and store the data as needed.

## Logging

### Log Structure

Logs are organized by date and session:
```
logs/
  webhook_2026-01-04_2fced767.log  # Date + Session ID
  webhook_2026-01-05_a8d7e9f2.log
  webhook_2026-01-05_9b3c1e5d.log  # Multiple sessions same day
```

### Log Format

All logs are structured JSON for easy parsing:
```json
{
  "timestamp": "2026-01-04T03:11:39.464868+08:00",
  "level": "INFO",
  "logger": "shopee_webhook.services.order_service",
  "message": "Stored 4 items for order 2601033YS140TT in database"
}
```

### Timezone

Logs use Singapore timezone (UTC+8) to match local time.

### View Logs

```bash
# Real-time Docker logs
docker-compose logs -f webhook-server

# View specific log file
cat logs/webhook_2026-01-04_*.log | python -m json.tool

# Pretty print JSON logs
cat logs/*.log | jq '.'
```

## Testing

### Manual Webhook Test

```bash
python test_order_webhook.py
```

This sends a test webhook to `http://localhost:8000/webhook/shopee` and displays the response.

### Health Check

```bash
curl http://localhost:8000/health | python -m json.tool
```

### View Logs

```bash
# View recent webhook events
cat logs/webhook_events_*.json | tail -20

# Pretty print JSON logs
cat logs/webhook_*.log | jq '.'
```

## Troubleshooting

### Webhook Signature Validation

**Note**: Signature validation is currently non-functional (see Known Issues section). Ensure `DEBUG_WEBHOOK=1` is set in your environment variables.

### API Returns 403 Forbidden

**Issue**: Token validation failed or invalid access_token

**Solution**:
1. App auto-refreshes tokens - wait a moment
2. Verify `ACCESS_TOKEN` and `REFRESH_TOKEN` are valid
3. Check `PARTNER_ID`, `PARTNER_KEY`, `SHOP_ID` are correct
4. Ensure tokens haven't expired on Shopee console

### No Telegram Messages Received

**Issue**: No notifications in Telegram

**Solution**:
1. Verify `TELEGRAM_BOT_TOKEN` format: `123456:ABC-DEF...`
2. Check `TELEGRAM_CHAT_ID` is valid (e.g., `-1001234567890`)
3. Ensure bot has permission to post in the channel
4. Check health endpoint: `curl http://localhost:8000/health`

### Webhook Forwarding Not Working

**Issue**: Custom service not receiving webhooks

**Solution**:
1. Verify `FORWARD_WEBHOOK_URL` is set in `.env`
2. Ensure custom service is running and accessible
3. Check custom service logs for incoming requests
4. Verify custom service accepts POST with JSON payload
5. Check forwarder logs: `docker-compose logs -f webhook-server`

## Deployment

### Docker Production

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f webhook-server

# Stop
docker-compose down
```

### Health Monitoring

Container includes automated health checks:
- **Interval**: Every 30 seconds
- **Timeout**: 3 seconds
- **Startup grace period**: 5 seconds
- **Retries**: 3 failures before unhealthy

Check status:
```bash
docker-compose ps
# Healthy: "Up X seconds (healthy)"
# Unhealthy: "Up X seconds (unhealthy)"
```

### Graceful Shutdown

- Waits for all pending tasks to complete
- Ensures all webhooks are forwarded before shutdown
- No data loss during restart

## Environment Example

```bash
# Shopee API Credentials
PARTNER_ID=2011563
PARTNER_KEY=your_partner_key_here
SHOP_ID=443972786
ACCESS_TOKEN=your_access_token_here
REFRESH_TOKEN=your_refresh_token_here

# Webhook Security
WEBHOOK_PARTNER_KEY=your_webhook_key_here

# Webhook Forwarding (Optional)
# Forward webhooks to your custom service
# Leave empty to disable forwarding
FORWARD_WEBHOOK_URL=http://localhost:9000/process-order

# Telegram Bot (Optional)
TELEGRAM_BOT_TOKEN=123456789:ABCDefGHIjklmnoPQRstuvWXYz
TELEGRAM_CHAT_ID=-1001234567890

# Optional
LOG_LEVEL=INFO
RELOAD=false
```

## How It Works

```mermaid
stateDiagram-v2
    [*] --> WaitWebhook: Server Started

    WaitWebhook --> ReceiveWebhook: Webhook Arrives
    ReceiveWebhook --> ValidateSignature: HMAC-SHA256 Check

    ValidateSignature --> Invalid: Bad Signature
    Invalid --> WaitWebhook

    ValidateSignature --> Valid: Valid Signature
    Valid --> FetchOrder: Get Order from API
    FetchOrder --> ForwardWebhook: Forward to Custom Service
    ForwardWebhook --> SendTelegram: Send Telegram Notification
    SendTelegram --> Response200: Return 200 OK
    Response200 --> WaitWebhook
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For issues or questions:
1. Check the health endpoint: `GET /health`
2. Review Docker logs: `docker-compose logs webhook-server`
3. View log files: `logs/webhook_*.log`
4. See Troubleshooting section above
