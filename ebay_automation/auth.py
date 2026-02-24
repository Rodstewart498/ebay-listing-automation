"""
Multi-account eBay OAuth 2.0 token management.

Handles automatic token refresh, expiry caching, and account scanning.
Supports multiple seller accounts with independent credentials,
each stored in separate JSON config files.

Tokens are refreshed on-demand and cached until expiry to minimize
API calls to eBay's OAuth endpoint.
"""

import json
import os
import time
import base64
import logging
from typing import Optional, Dict, Tuple

import requests

logger = logging.getLogger(__name__)

# eBay OAuth endpoints
EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_AUTH_URL = "https://auth.ebay.com/oauth2/authorize"

# Scopes required for Trading API operations
EBAY_SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.marketing.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.marketing",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
]


class EbayAccountConfig:
    """Configuration for a single eBay seller account."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._config = self._load()

    def _load(self) -> dict:
        """Load account config from JSON file."""
        with open(self.filepath, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _save(self) -> None:
        """Persist updated tokens back to config file."""
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, indent=2)

    @property
    def username(self) -> str:
        return self._config.get('username', 'Unknown')

    @property
    def refresh_token(self) -> str:
        return self._config.get('refresh_token', '')

    @property
    def access_token(self) -> str:
        return self._config.get('access_token', '')

    @property
    def access_token_expiry(self) -> float:
        return float(self._config.get('access_token_expiry', 0))

    @property
    def is_token_valid(self) -> bool:
        """Check if the cached access token is still valid (with 5-min buffer)."""
        return (
            bool(self.access_token)
            and self.access_token_expiry > time.time() + 300
        )

    def update_token(self, access_token: str, expires_in: int) -> None:
        """Cache a new access token with its expiry timestamp."""
        self._config['access_token'] = access_token
        self._config['access_token_expiry'] = time.time() + expires_in
        self._save()
        logger.info(f"Token cached for {self.username} (expires in {expires_in}s)")


class EbayAuthManager:
    """
    Manages OAuth tokens across multiple eBay seller accounts.

    Scans a config directory for account JSON files, handles token refresh,
    and caches valid tokens to minimize OAuth API calls.
    """

    def __init__(self, config_dir: str, app_id: str, cert_id: str):
        """
        Args:
            config_dir: Directory containing per-account JSON config files.
            app_id: eBay application (client) ID.
            cert_id: eBay certificate (client secret) ID.
        """
        self.config_dir = config_dir
        self.app_id = app_id
        self.cert_id = cert_id
        self._accounts: Dict[str, EbayAccountConfig] = {}
        self.scan_accounts()

    def scan_accounts(self) -> Dict[str, dict]:
        """
        Scan config directory for eBay account JSON files.

        Returns:
            Dict mapping account names to their config info.
        """
        self._accounts.clear()
        configs = {}

        if not os.path.isdir(self.config_dir):
            logger.warning(f"Config directory not found: {self.config_dir}")
            return configs

        for filename in sorted(os.listdir(self.config_dir)):
            if not filename.endswith('.json'):
                continue

            filepath = os.path.join(self.config_dir, filename)
            try:
                account = EbayAccountConfig(filepath)
                if account.refresh_token:
                    name = account.username or os.path.splitext(filename)[0]
                    self._accounts[name] = account
                    configs[name] = {"filepath": filepath, "username": name}
                    logger.debug(f"Found eBay account: {name}")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Skipping invalid config {filename}: {e}")

        logger.info(f"Scanned {len(self._accounts)} eBay account(s)")
        return configs

    @property
    def account_names(self) -> list:
        """List all configured account names."""
        return list(self._accounts.keys())

    def get_token(self, account_name: Optional[str] = None) -> Optional[str]:
        """
        Get a valid access token for the specified account.

        Uses cached token if still valid, otherwise refreshes via OAuth.

        Args:
            account_name: Account to get token for. Uses first account if None.

        Returns:
            Access token string, or None if refresh fails.
        """
        if not account_name:
            if not self._accounts:
                logger.error("No eBay accounts configured")
                return None
            account_name = next(iter(self._accounts))

        account = self._accounts.get(account_name)
        if not account:
            logger.error(f"Account not found: {account_name}")
            return None

        # Return cached token if still valid
        if account.is_token_valid:
            logger.debug(f"Using cached token for {account_name}")
            return account.access_token

        # Refresh the token
        return self._refresh_token(account)

    def _refresh_token(self, account: EbayAccountConfig) -> Optional[str]:
        """
        Refresh an expired access token using the stored refresh token.

        Args:
            account: Account configuration with refresh token.

        Returns:
            New access token, or None on failure.
        """
        logger.info(f"Refreshing token for {account.username}...")

        # Build Basic auth header: base64(app_id:cert_id)
        credentials = base64.b64encode(
            f"{self.app_id}:{self.cert_id}".encode()
        ).decode()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials}"
        }

        data = {
            "grant_type": "refresh_token",
            "refresh_token": account.refresh_token,
            "scope": " ".join(EBAY_SCOPES)
        }

        try:
            response = requests.post(
                EBAY_TOKEN_URL,
                headers=headers,
                data=data,
                timeout=15
            )

            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data["access_token"]
                expires_in = int(token_data.get("expires_in", 7200))
                account.update_token(access_token, expires_in)
                return access_token
            else:
                logger.error(
                    f"Token refresh failed for {account.username}: "
                    f"HTTP {response.status_code} — {response.text[:200]}"
                )
                return None

        except requests.RequestException as e:
            logger.error(f"Token refresh error for {account.username}: {e}")
            return None

    def get_token_for_config(self, config_path: str) -> Optional[str]:
        """
        Get token by config file path (for backward compatibility).

        Args:
            config_path: Full path to account JSON config file.

        Returns:
            Access token string, or None if refresh fails.
        """
        for name, account in self._accounts.items():
            if account.filepath == config_path:
                return self.get_token(name)

        # Try loading directly
        try:
            account = EbayAccountConfig(config_path)
            return self._refresh_token(account)
        except Exception as e:
            logger.error(f"Failed to load config {config_path}: {e}")
            return None
