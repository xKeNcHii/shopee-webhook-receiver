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

# ==============================================================================
# RECONCILIATION CONFIGURATION
# ==============================================================================

# Scheduled sync interval (how often to run periodic sync)
SYNC_INTERVAL_HOURS = 1

# Daily full sync hour (24-hour format, local timezone)
# 3 AM is typically low-traffic period
DAILY_SYNC_HOUR = 3

# Historical range for full syncs (how far back to look)
HISTORICAL_DAYS = 7

# Overlap buffer for scheduled syncs (fetch orders updated within last N hours)
# This ensures we don't miss orders updated just before last sync
SYNC_OVERLAP_HOURS = 2

# Maximum orders per API page (Shopee limit is 100)
ORDER_LIST_PAGE_SIZE = 100

# Batch size for order detail fetching (Shopee limit is 50)
ORDER_DETAIL_BATCH_SIZE = 50

# Sync timeout (maximum time for a single sync operation in seconds)
SYNC_TIMEOUT_SECONDS = 600  # 10 minutes

# Delay between API calls to avoid rate limiting (in seconds)
API_CALL_DELAY_SECONDS = 0.2
