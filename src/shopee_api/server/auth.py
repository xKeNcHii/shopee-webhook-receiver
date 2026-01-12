"""
Authentication Middleware

Simple API key authentication for dashboard endpoints.
"""

from fastapi import Header, HTTPException, status
from shopee_api.config.settings import settings


async def verify_api_key(x_api_key: str = Header(..., description="Dashboard API key")):
    """
    Verify API key from X-API-Key header.

    Args:
        x_api_key: API key from X-API-Key header

    Raises:
        HTTPException: If API key is missing, invalid, or dashboard is not configured

    Returns:
        True if authentication successful
    """
    expected_key = settings.dashboard_api_key

    # Check if dashboard is configured
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard not configured (DASHBOARD_API_KEY not set in environment)"
        )

    # Verify API key matches
    if x_api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"}
        )

    return True
