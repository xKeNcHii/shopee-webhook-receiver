"""Google Sheets repository implementation."""

import gspread
import json
import os
from pathlib import Path
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google.oauth2.credentials import Credentials as OAuth2Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from typing import List, Dict, Any, Optional
from shopee_worker.repositories.base import OrderRepository
from shopee_api.core.logger import setup_logger
from shopee_api.config.constants import TIMEZONE_OFFSET_HOURS

logger = setup_logger(__name__)

# ============================================================================
# CONSTANTS - Header Configuration
# ============================================================================

# Column header names (order matters for initial table creation)
COLUMN_ORDER_ID = "Order ID"
COLUMN_DATE_TIME = "Date & Time"
COLUMN_BUYER = "Buyer"
COLUMN_PLATFORM = "Platform"
COLUMN_PRODUCT_NAME = "Product Name"
COLUMN_ITEM_TYPE = "Item Type"
COLUMN_PARENT_SKU = "Parent SKU"
COLUMN_SKU = "SKU"
COLUMN_QUANTITY = "Quantity"
COLUMN_TOTAL_SALE = "Total Sale"
COLUMN_SHOPEE_STATUS = "Shopee Status"
COLUMN_NOTES = "Notes"

# Full header list (used for initial table creation)
SHEET_HEADERS = [
    COLUMN_ORDER_ID,
    COLUMN_DATE_TIME,
    COLUMN_BUYER,
    COLUMN_PLATFORM,
    COLUMN_PRODUCT_NAME,
    COLUMN_ITEM_TYPE,
    COLUMN_PARENT_SKU,
    COLUMN_SKU,
    COLUMN_QUANTITY,
    COLUMN_TOTAL_SALE,
    COLUMN_SHOPEE_STATUS,
    COLUMN_NOTES,
]

# Mapping from item dict keys to column headers
ITEM_TO_COLUMN_MAPPING = {
    "order_id": COLUMN_ORDER_ID,
    "date_time": COLUMN_DATE_TIME,
    "buyer": COLUMN_BUYER,
    "platform": COLUMN_PLATFORM,
    "product_name": COLUMN_PRODUCT_NAME,
    "item_type": COLUMN_ITEM_TYPE,
    "parent_sku": COLUMN_PARENT_SKU,
    "sku": COLUMN_SKU,
    "quantity": COLUMN_QUANTITY,
    "total_sale": COLUMN_TOTAL_SALE,
    "shopee_status": COLUMN_SHOPEE_STATUS,
    "notes": COLUMN_NOTES,
}

# Default values for each data type
DEFAULT_VALUES = {
    COLUMN_PLATFORM: "Shopee",
    COLUMN_QUANTITY: 0,
    COLUMN_TOTAL_SALE: 0.0,
}

# Keys used for row matching (upsert logic)
ROW_MATCH_KEY_ORDER_ID = "order_id"
ROW_MATCH_KEY_SKU = "sku"

# Google Sheets API scopes
GOOGLE_SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# OAuth token filename
OAUTH_TOKEN_FILENAME = "token.json"

# Google Sheets API configuration
GOOGLE_SHEETS_API_VERSION = 'v4'
INSERT_ROW_START_INDEX = 1  # 0-based: row 2 in 1-based numbering
INSERT_ROW_END_INDEX = 2    # Exclusive: insert 1 row

# ============================================================================


class GoogleSheetsRepository(OrderRepository):
    """Google Sheets storage implementation."""

    def __init__(self, credentials_path: str, spreadsheet_id: str, sheet_name: str = None):
        """Initialize Google Sheets client.

        Args:
            credentials_path: Path to Google credentials JSON file (service account or OAuth client)
            spreadsheet_id: Google Spreadsheet ID (from URL)
            sheet_name: Optional sheet name (e.g., "Orders", "January").
                       If not provided, uses first sheet (Sheet1)
        """
        try:
            logger.info(f"Initializing Google Sheets repository: {spreadsheet_id}")
            if sheet_name:
                logger.info(f"Target sheet: {sheet_name}")
            else:
                logger.info("Target sheet: First sheet (default)")

            # Determine credential type and authenticate
            creds = self._get_credentials(credentials_path, GOOGLE_SHEETS_SCOPES)
            self.client = gspread.authorize(creds)

            # Store credentials and IDs for API v4 calls
            self._credentials = creds
            self._spreadsheet_id = spreadsheet_id
            self._sheet_name = sheet_name

            # Initialize Google Sheets API v4 service
            from googleapiclient.discovery import build
            self._sheets_service = build('sheets', GOOGLE_SHEETS_API_VERSION, credentials=creds)

            # Cache for column positions (maps column name -> column index)
            self._column_positions: Optional[Dict[str, int]] = None

            # Open spreadsheet
            self.spreadsheet = self.client.open_by_key(spreadsheet_id)

            # Get target worksheet
            if sheet_name:
                # Get worksheet by name
                try:
                    self.worksheet = self.spreadsheet.worksheet(sheet_name)
                    logger.info(f"Found existing sheet: {sheet_name}")
                except gspread.exceptions.WorksheetNotFound:
                    # Create new sheet if it doesn't exist
                    logger.info(f"Sheet '{sheet_name}' not found, creating...")
                    self.worksheet = self.spreadsheet.add_worksheet(
                        title=sheet_name,
                        rows=1000,
                        cols=12
                    )
                    logger.info(f"Created new sheet: {sheet_name}")
            else:
                # Use first sheet
                self.worksheet = self.spreadsheet.sheet1

            # Initialize headers if needed
            self._initialize_headers()

            logger.info("Google Sheets repository initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets repository: {e}", exc_info=True)
            raise

    def _get_credentials(self, credentials_path: str, scopes: list):
        """Get Google credentials from file (supports service account and OAuth client).

        Args:
            credentials_path: Path to credentials JSON
            scopes: Required OAuth scopes

        Returns:
            Credentials object
        """
        # Read credentials file to determine type
        with open(credentials_path, 'r') as f:
            cred_data = json.load(f)

        # Check if it's a service account (has 'client_email' field)
        if 'client_email' in cred_data:
            logger.info("Using service account credentials")
            return ServiceAccountCredentials.from_service_account_file(
                credentials_path,
                scopes=scopes
            )

        # Check if it's an OAuth client credentials file (has 'installed' field)
        elif 'installed' in cred_data:
            logger.info("Using OAuth 2.0 client credentials")
            return self._get_oauth_credentials(credentials_path, scopes)

        else:
            raise ValueError(
                "Invalid credentials file. Must be either:\n"
                "1. Service account JSON (has 'client_email' field)\n"
                "2. OAuth 2.0 client JSON (has 'installed' field)"
            )

    def _get_oauth_credentials(self, credentials_path: str, scopes: list):
        """Get OAuth 2.0 credentials with token caching.

        Args:
            credentials_path: Path to OAuth client credentials JSON
            scopes: Required OAuth scopes

        Returns:
            OAuth2Credentials object
        """
        # Token file path (stored alongside credentials)
        creds_dir = Path(credentials_path).parent
        token_path = creds_dir / OAUTH_TOKEN_FILENAME

        creds = None

        # Try to load existing token
        if token_path.exists():
            logger.info(f"Loading existing OAuth token from {token_path}")
            creds = OAuth2Credentials.from_authorized_user_file(str(token_path), scopes)

        # If no valid credentials, need to authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired OAuth token")
                creds.refresh(Request())
            else:
                # No valid token - need user authentication
                logger.warning(
                    f"No valid OAuth token found at {token_path}. "
                    "User authentication required."
                )
                logger.info("Starting OAuth flow...")

                flow = InstalledAppFlow.from_client_secrets_file(
                    credentials_path,
                    scopes
                )

                # Run local server for OAuth callback
                # This will open a browser for the user to authenticate
                creds = flow.run_local_server(port=0)

                logger.info("OAuth flow completed successfully")

            # Save token for future use
            logger.info(f"Saving OAuth token to {token_path}")
            with open(token_path, 'w') as token_file:
                token_file.write(creds.to_json())

        return creds

    def _get_column_positions(self) -> Dict[str, int]:
        """Get current column positions from sheet headers.

        Caches the result to avoid repeated API calls.
        Returns a dict mapping column name -> column index (1-based).

        Returns:
            Dict mapping column header names to their positions
        """
        if self._column_positions is not None:
            return self._column_positions

        # Read first row to get headers
        headers = self.worksheet.row_values(1) if self.worksheet.row_count > 0 else []

        # Build position map (1-based indexing)
        self._column_positions = {
            header: idx + 1
            for idx, header in enumerate(headers)
            if header
        }

        logger.info(f"Column positions: {self._column_positions}")
        return self._column_positions

    def _refresh_column_positions(self):
        """Force refresh of column position cache."""
        self._column_positions = None
        return self._get_column_positions()

    def _get_sheet_id(self) -> int:
        """Get numeric sheet ID (sheetId) for API v4 calls.

        Returns:
            Integer sheet ID (e.g., 0, 123456) used in batchUpdate requests
        """
        try:
            # Get spreadsheet metadata
            spreadsheet = self._sheets_service.spreadsheets().get(
                spreadsheetId=self._spreadsheet_id
            ).execute()

            # Find sheet by name
            for sheet in spreadsheet['sheets']:
                if sheet['properties']['title'] == self.worksheet.title:
                    return sheet['properties']['sheetId']

            raise ValueError(f"Sheet '{self.worksheet.title}' not found")

        except Exception as e:
            logger.error(f"Failed to get sheet ID: {e}", exc_info=True)
            raise

    def _get_column_letter(self, col_index: int) -> str:
        """Convert column index (1-based) to Excel-style letter (A, B, C, ..., Z, AA, AB, ...).

        Args:
            col_index: Column index (1-based)

        Returns:
            Column letter (e.g., 1 -> 'A', 27 -> 'AA')
        """
        result = ""
        while col_index > 0:
            col_index -= 1
            result = chr(col_index % 26 + ord('A')) + result
            col_index //= 26
        return result

    def _get_range_notation(self, row: int, start_col: int, end_col: int) -> str:
        """Build A1 notation range (e.g., 'A1:L1' or 'B5:M5').

        Args:
            row: Row number (1-based)
            start_col: Starting column index (1-based)
            end_col: Ending column index (1-based)

        Returns:
            Range in A1 notation (e.g., 'A1:L1')
        """
        start_letter = self._get_column_letter(start_col)
        end_letter = self._get_column_letter(end_col)
        return f"{start_letter}{row}:{end_letter}{row}"

    def _insert_row_at_top(self, row_values: list) -> bool:
        """Insert a single row at row 2 (top, below headers) using API v4.

        Implementation matches dca.py approach:
        1. Insert empty row at startIndex: 1 (0-based, = row 2 in 1-based)
        2. Populate row with values via batchUpdate

        Args:
            row_values: List of values for the row (must match column count)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Log the values being inserted for debugging
            logger.info(f"Row values to insert: {row_values[:3]}... (showing first 3 of {len(row_values)})")

            # STEP 1: Insert empty row at top (below headers)
            logger.info("Inserting empty row at row 2...")

            insert_request = {
                'requests': [{
                    'insertDimension': {
                        'range': {
                            'sheetId': self._get_sheet_id(),
                            'dimension': 'ROWS',
                            'startIndex': INSERT_ROW_START_INDEX,  # 0-based: row 2 in 1-based numbering
                            'endIndex': INSERT_ROW_END_INDEX     # Insert 1 row (endIndex is exclusive)
                        }
                    }
                }]
            }

            self._sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body=insert_request
            ).execute()

            logger.info("Empty row inserted at row 2")

            # STEP 2: Populate the row with values
            logger.info(f"Populating row 2 with {len(row_values)} values...")

            # Build range notation for row 2 (e.g., "A2:L2" for 12 columns)
            num_cols = len(row_values)
            range_notation = self._get_range_notation(2, 1, num_cols)

            # Include sheet name in range (e.g., "TESTING(IGNORE)!A2:L2")
            sheet_range = f"{self.worksheet.title}!{range_notation}"
            logger.info(f"Writing to range: {sheet_range}")

            # Batch update with values
            batch_update_body = {
                'valueInputOption': 'USER_ENTERED',
                'data': [{
                    'range': sheet_range,
                    'values': [row_values]  # Single row
                }]
            }

            self._sheets_service.spreadsheets().values().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body=batch_update_body
            ).execute()

            logger.info("Row 2 populated successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to insert row at top: {e}", exc_info=True)
            return False

    def _initialize_headers(self):
        """Create header row if sheet is empty or verify required columns exist."""
        try:
            # Get first row to check if headers exist
            first_row = self.worksheet.row_values(1) if self.worksheet.row_count > 0 else []

            if not first_row:
                # Sheet is completely empty - create headers
                logger.info(f"Sheet is empty. Creating header row with {len(SHEET_HEADERS)} columns")
                self.worksheet.append_row(SHEET_HEADERS)
                logger.info(f"Headers created: {', '.join(SHEET_HEADERS)}")
                self._refresh_column_positions()
            else:
                # Sheet has headers - check if all required columns exist
                missing_columns = []
                for header in SHEET_HEADERS:
                    if header not in first_row:
                        missing_columns.append(header)

                if missing_columns:
                    logger.warning(f"Missing required columns: {', '.join(missing_columns)}")
                    logger.info("Adding missing columns to the end of the header row...")

                    # Append missing columns at the end
                    updated_row = first_row + missing_columns
                    range_notation = self._get_range_notation(1, 1, len(updated_row))
                    self.worksheet.update(range_notation, [updated_row])
                    logger.info(f"Added columns: {', '.join(missing_columns)}")
                    self._refresh_column_positions()
                else:
                    logger.info("All required columns present in header row")
                    self._refresh_column_positions()
        except Exception as e:
            logger.error(f"Error initializing headers: {e}", exc_info=True)
            raise

    def _ensure_headers_exist(self):
        """Verify headers exist before data operations. Creates them if missing."""
        try:
            first_row = self.worksheet.row_values(1) if self.worksheet.row_count > 0 else []
            expected_col_count = len(SHEET_HEADERS)

            if not first_row:
                logger.warning("Headers missing! Creating header row before insert...")
                self.worksheet.insert_row(SHEET_HEADERS, index=1)
                logger.info("Headers created successfully")
                self._refresh_column_positions()
            elif len(first_row) < expected_col_count:
                logger.warning(f"Headers incomplete. Updating to full {expected_col_count} columns...")
                range_notation = self._get_range_notation(1, 1, expected_col_count)
                self.worksheet.update(range_notation, [SHEET_HEADERS])
                logger.info("Headers updated successfully")
                self._refresh_column_positions()
        except Exception as e:
            logger.error(f"Error ensuring headers exist: {e}", exc_info=True)
            raise

    async def upsert_order_items(self, items: List[Dict[str, Any]]) -> bool:
        """Insert or update order items into Google Sheets.

        Strategy:
        1. Ensure headers exist (create if missing)
        2. Get all existing rows
        3. For each new item:
           - Find matching row (Order ID + SKU)
           - Update if found, append if new

        Args:
            items: List of order item dictionaries

        Returns:
            True if successful
        """
        try:
            if not items:
                logger.warning("No items to upsert")
                return True

            logger.info(f"Upserting {len(items)} items to Google Sheets")

            # IMPORTANT: Ensure headers exist before any data operation
            self._ensure_headers_exist()

            # Get current column positions based on actual sheet headers
            col_positions = self._get_column_positions()

            # Get all existing data
            all_records = self.worksheet.get_all_records()

            for item in items:
                # Build row data dict using column header names as keys
                row_data = {}
                for item_key, col_header in ITEM_TO_COLUMN_MAPPING.items():
                    # Get value from item, or use default value (skip notes for now)
                    if col_header == COLUMN_NOTES:
                        continue  # Will be set based on changes
                    value = item.get(item_key, DEFAULT_VALUES.get(col_header, ""))
                    row_data[col_header] = value

                # Find existing row by Order ID + SKU
                existing_row_index = None
                existing_row_data = None
                for idx, row in enumerate(all_records, start=2):  # Start at 2 (row 1 is header)
                    if (row.get(COLUMN_ORDER_ID) == item.get(ROW_MATCH_KEY_ORDER_ID) and
                        row.get(COLUMN_SKU) == item.get(ROW_MATCH_KEY_SKU)):
                        existing_row_index = idx
                        existing_row_data = row
                        break

                # Generate Notes based on whether this is new or updated
                # Get current datetime in Singapore timezone (UTC+8)
                from datetime import datetime, timezone, timedelta
                singapore_tz = timezone(timedelta(hours=TIMEZONE_OFFSET_HOURS))
                now = datetime.now(singapore_tz)
                timestamp_str = now.strftime("%Y-%m-%d %H:%M")

                if existing_row_data:
                    # Track changes for Shopee Status and Total Sale
                    changes = []

                    # Check Shopee Status change
                    old_status = existing_row_data.get(COLUMN_SHOPEE_STATUS, "")
                    new_status = row_data.get(COLUMN_SHOPEE_STATUS, "")

                    # DEBUG: Log comparison values
                    logger.info(
                        f"Comparing status for {item.get(ROW_MATCH_KEY_ORDER_ID)} "
                        f"SKU {item.get(ROW_MATCH_KEY_SKU)}: "
                        f"OLD='{old_status}' vs NEW='{new_status}'"
                    )

                    if old_status != new_status and new_status:
                        changes.append(f"Status: {old_status}->{new_status}")
                        logger.info(f"STATUS CHANGE DETECTED: {old_status} -> {new_status}")

                    # Check Total Sale change
                    old_sale = existing_row_data.get(COLUMN_TOTAL_SALE, "")
                    new_sale = row_data.get(COLUMN_TOTAL_SALE, "")

                    # DEBUG: Log comparison values
                    logger.info(
                        f"Comparing sale for {item.get(ROW_MATCH_KEY_ORDER_ID)}: "
                        f"OLD='{old_sale}' vs NEW='{new_sale}'"
                    )
                    # Convert to float for comparison to handle string vs number
                    try:
                        old_sale_val = float(old_sale) if old_sale else 0
                        new_sale_val = float(new_sale) if new_sale else 0
                        if abs(old_sale_val - new_sale_val) > 0.01:  # Changed
                            changes.append(f"Sale: {old_sale}->{new_sale}")
                    except (ValueError, TypeError):
                        # If conversion fails, do string comparison
                        if old_sale != new_sale:
                            changes.append(f"Sale: {old_sale}->{new_sale}")

                    # Set notes with timestamp - Append to existing notes
                    existing_notes = existing_row_data.get(COLUMN_NOTES, "")
                    
                    if changes:
                        new_note = f"[{timestamp_str}] {', '.join(changes)}"
                        if existing_notes:
                            row_data[COLUMN_NOTES] = f"{existing_notes}\n{new_note}"
                        else:
                            row_data[COLUMN_NOTES] = new_note
                    else:
                        # Keep existing notes if no changes
                        row_data[COLUMN_NOTES] = existing_notes
                else:
                    # New order with timestamp
                    row_data[COLUMN_NOTES] = f"[{timestamp_str}] New order"

                # Convert row_data dict to list of values based on current column order
                # This allows columns to be reordered in the sheet
                row_values = []
                header_row = self.worksheet.row_values(1)
                for header in header_row:
                    row_values.append(row_data.get(header, ""))

                if existing_row_index:
                    # Update existing row - dynamically calculate range
                    num_cols = len(header_row)
                    cell_range = self._get_range_notation(existing_row_index, 1, num_cols)
                    self.worksheet.update(cell_range, [row_values])
                    logger.info(
                        f"Updated row {existing_row_index} for order {item.get(ROW_MATCH_KEY_ORDER_ID)} "
                        f"SKU {item.get(ROW_MATCH_KEY_SKU)}"
                    )
                else:
                    # Insert new row at top (row 2) - newest first
                    success = self._insert_row_at_top(row_values)
                    if success:
                        logger.info(
                            f"Inserted new row at top for order {item.get(ROW_MATCH_KEY_ORDER_ID)} "
                            f"SKU {item.get(ROW_MATCH_KEY_SKU)}"
                        )
                    else:
                        logger.error(
                            f"Failed to insert row for order {item.get(ROW_MATCH_KEY_ORDER_ID)}"
                        )
                        return False  # Abort on insertion failure

            logger.info(f"Successfully upserted {len(items)} items")
            return True

        except Exception as e:
            logger.error(f"Error upserting to Google Sheets: {e}", exc_info=True)
            return False

    async def get_order_items(self, order_id: str) -> List[Dict[str, Any]]:
        """Get all items for a specific order.

        Args:
            order_id: Order serial number

        Returns:
            List of order items matching the order_id
        """
        try:
            all_records = self.worksheet.get_all_records()
            items = [r for r in all_records if r.get(COLUMN_ORDER_ID) == order_id]
            logger.info(f"Found {len(items)} items for order {order_id}")
            return items

        except Exception as e:
            logger.error(f"Error getting order items: {e}", exc_info=True)
            return []

    async def health_check(self) -> bool:
        """Check if we can access the spreadsheet.

        Returns:
            True if accessible, False otherwise
        """
        try:
            # Simple access test
            _ = self.spreadsheet.title
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
