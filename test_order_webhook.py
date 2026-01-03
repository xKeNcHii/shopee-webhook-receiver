#!/usr/bin/env python3
"""Test webhook for a specific order."""

import hmac
import hashlib
import json
import requests
import time
import os
from dotenv import load_dotenv

load_dotenv()

PARTNER_KEY = os.getenv("PARTNER_KEY")
WEBHOOK_URL = "http://localhost:8000/webhook/shopee"

# Load test data from environment or use placeholders
ORDER_SN = os.getenv("TEST_ORDER_SN", "TEST_ORDER_SN_PLACEHOLDER")
SHOP_ID = int(os.getenv("TEST_SHOP_ID", "123456"))

# Create webhook payload (Code 3 = Order Status Update)
payload = {
    "code": 3,
    "shop_id": SHOP_ID,
    "timestamp": int(time.time()),
    "data": {
        "ordersn": ORDER_SN,
        "status": "SHIPPED",  # Changed to SHIPPED to test change tracking
        "update_time": int(time.time())
    }
}

# Generate signature
body_str = json.dumps(payload)
signature = hmac.new(
    PARTNER_KEY.encode('utf-8'),
    body_str.encode('utf-8'),
    hashlib.sha256
).hexdigest()

print("=" * 80)
print("SENDING TEST WEBHOOK")
print("=" * 80)
print(f"\nOrder SN: {ORDER_SN}")
print(f"Event Code: 3 (Order Status Update)")
print(f"Payload:\n{json.dumps(payload, indent=2)}")
print(f"\nSignature: {signature[:32]}...")

# Send webhook
try:
    response = requests.post(
        WEBHOOK_URL,
        json=payload,
        headers={"Authorization": signature},
        timeout=10
    )
    
    print(f"\n{'=' * 80}")
    print(f"RESPONSE: {response.status_code}")
    print(f"{'=' * 80}")
    if response.text:
        print(f"Body: {response.text}")
    else:
        print("Body: (empty - as expected)")
    
    if response.status_code == 200:
        print("\n✅ Webhook accepted successfully!")
    else:
        print("\n❌ Error receiving webhook")
        
except Exception as e:
    print(f"\n❌ Error: {e}")