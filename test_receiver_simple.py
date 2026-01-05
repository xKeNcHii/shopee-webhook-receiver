#!/usr/bin/env python3
"""Simple test server to receive forwarded webhooks (event-only format)."""

from flask import Flask, request, jsonify
import json

app = Flask(__name__)

@app.route('/process-order', methods=['POST'])
def process_order():
    """Receive forwarded webhook (event only)."""
    print("\n" + "="*80)
    print("WEBHOOK EVENT RECEIVED")
    print("="*80)

    try:
        # Receive raw webhook event (no wrapper)
        event = request.get_json()

        print(f"\nEvent Code: {event.get('code')}")
        print(f"Shop ID: {event.get('shop_id')}")
        print(f"Timestamp: {event.get('timestamp')}")
        print(f"\nEvent Data:")
        print(json.dumps(event.get('data', {}), indent=2))

        # Check if this is an order event
        if event.get('code') in [3, 4]:
            order_sn = event.get('data', {}).get('ordersn')
            print(f"\n[INFO] Order event detected: {order_sn}")
            print("[INFO] Processor would fetch full details from Shopee API here")

        print("\n" + "="*80)
        print("SUCCESS - Event processed")
        print("="*80 + "\n")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        print(f"\nERROR: {e}\n")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    print("\n" + "="*80)
    print("TEST WEBHOOK RECEIVER - Event-Only Format")
    print("="*80)
    print("\nListening on: http://localhost:9000")
    print("Press CTRL+C to stop\n")

    app.run(host='0.0.0.0', port=9000, debug=False)
