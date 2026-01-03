"""Shopee Webhook Signature Verification.

Verifies that incoming webhooks are genuinely from Shopee using HMAC-SHA256.
Based on official Shopee Push Mechanism documentation.
"""

import hashlib
import hmac
import os
from typing import Optional

from shopee_webhook.config.settings import settings
from shopee_webhook.core.logger import setup_logger

logger = setup_logger(__name__)


def verify_push_signature(
    request_body: str,
    signature_header: Optional[str],
) -> bool:
    """
    Verify a Shopee webhook signature.

    Args:
        request_body: Raw request body as string (NOT parsed JSON)
        signature_header: Value from Authorization header

    Returns:
        True if signature is valid and came from Shopee

    Reference:
        Shopee uses HMAC-SHA256 over the raw request body only.
    """
    # Validate inputs
    if not signature_header:
        logger.warning("Webhook received without Authorization header")
        return False

    if not request_body:
        logger.warning("Missing request body for signature verification")
        return False

    # Try both keys - HMAC is computed over JUST the request body
    keys_to_try = []

    # First try: partner_key
    if settings.partner_key:
        key = settings.partner_key
        if key.startswith("shpk"):
            key = key[4:]
        keys_to_try.append(("partner_key", key))

    # Second try: webhook_partner_key
    if settings.webhook_partner_key:
        key = settings.webhook_partner_key
        if key.startswith("shpk"):
            key = key[4:]
        keys_to_try.append(("webhook_partner_key", key))

    # Try to validate with each key
    for key_source, key_to_use in keys_to_try:
        try:
            # IMPORTANT: Compute HMAC over ONLY the request body (not url|body)
            expected_signature = hmac.new(
                key_to_use.encode("utf-8"),
                request_body.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            # Compare using constant-time comparison
            is_valid = hmac.compare_digest(expected_signature, signature_header)

            if is_valid:
                logger.info(f"✓ Valid webhook signature using {key_source}")
                return True
        except Exception as e:
            logger.error(f"Error verifying signature with {key_source}: {e}")
            continue

    # If we get here, no keys matched
    logger.warning(f"Invalid webhook signature. Got: {signature_header[:16]}...")

    # If DEBUG_WEBHOOK is enabled, accept invalid signatures for testing
    if os.getenv("DEBUG_WEBHOOK") == "1":
        logger.warning("DEBUG MODE: Accepting invalid signature (DEBUG_WEBHOOK=1)")
        return True

    return False


def validate_webhook_request(
    raw_body: bytes,
    authorization_header: Optional[str],
) -> tuple[bool, Optional[str]]:
    """
    Full webhook validation: signature verification + basic checks.

    Args:
        raw_body: Raw request body as bytes
        authorization_header: Value from Authorization header

    Returns:
        Tuple of (is_valid: bool, error_message: Optional[str])
        If valid: (True, None)
        If invalid: (False, error_message)
    """
    # Convert body to string for signature verification
    try:
        body_str = raw_body.decode("utf-8")
    except UnicodeDecodeError as e:
        error = f"Invalid UTF-8 in request body: {e}"
        logger.error(error)
        return False, error

    # Body must not be empty
    if not body_str.strip():
        return False, "Empty request body"

    # Verify signature (HMAC computed over just the request body)
    if not verify_push_signature(body_str, authorization_header):
        return False, "Invalid webhook signature"

    return True, None
