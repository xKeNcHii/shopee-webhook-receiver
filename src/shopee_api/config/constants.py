"""
Centralized application constants.

This file acts as the single point of truth for business logic constants
shared across the webhook handler and processor services.
"""

# ==============================================================================
# SHOPEE BUSINESS LOGIC
# ==============================================================================

# Order-related event codes
# 3 = Order Status Update
# 4 = Order Tracking Number Update
ORDER_EVENT_CODES = [3, 4]

# Statuses to ignore (don't add to Google Sheets)
IGNORE_STATUSES = ["UNPAID"]

# Currency formatting
CURRENCY_DECIMAL_PLACES = 2

# ==============================================================================
# REGIONAL SETTINGS
# ==============================================================================

# Timezone configuration (Singapore Standard Time is UTC+8)
TIMEZONE_OFFSET_HOURS = 8
