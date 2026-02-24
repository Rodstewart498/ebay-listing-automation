"""
Unified field-level sync engine.

The core pipeline that ensures any field edit from any UI surface
flows through the same code path:

    editField() → /update_metadata_field → sync_item_to_ebay()

Title changes trigger automatic description rebuilds:
    1. GetItem to fetch existing PictureURLs from eBay
    2. Rebuild description with new title + existing images
    3. ReviseItem with title + description + re-attached PictureURLs

All other field changes (price, SKU, MPN, brand, quantity, weight,
shipping) are pushed via ReviseItem with only the changed field.

Account auto-detection: tries the account stored in metadata first,
falls back to scanning all configured accounts.
"""

import re
import html
import logging
from typing import Optional, Dict, Any

from .auth import EbayAuthManager
from .trading_api import get_item, revise_item
from .description import build_description

logger = logging.getLogger(__name__)


class SyncEngine:
    """
    Manages field-level synchronization between local metadata and eBay.

    Provides a single entry point (sync_field) that handles all field types,
    with special logic for title changes that require description rebuilds.
    """

    def __init__(self, auth_manager: EbayAuthManager):
        """
        Args:
            auth_manager: Configured EbayAuthManager for token retrieval.
        """
        self.auth = auth_manager

    def sync_field(self, entry: dict, field: str,
                   new_value: str, old_value: str = "") -> Dict[str, Any]:
        """
        Sync a single field change to eBay.

        This is the unified entry point — every field edit from every
        UI surface (main results, Compare Competitors modal, View All
        Verified modal, checklist cards) calls this same method.

        Args:
            entry: Full metadata entry dict for the item.
            field: Field name being changed (title, price, sku, mpn,
                   brand, inventory, weight, shipping_tier).
            new_value: New field value.
            old_value: Previous field value (for logging).

        Returns:
            Dict with 'success', 'message', and 'account' used.
        """
        ebay_item_id = str(entry.get('ebay_item_id', '')).strip()
        if not ebay_item_id:
            return {
                "success": False,
                "message": "No ebay_item_id — cannot sync",
                "skipped": True,
            }

        # Resolve the eBay account and get a valid token
        token, account_name = self._resolve_account_token(entry)
        if not token:
            return {
                "success": False,
                "message": "Could not obtain eBay token for any account",
            }

        # Route to the appropriate sync handler
        if field == "title":
            result = self._sync_title(entry, ebay_item_id, new_value, token)
        elif field == "price":
            result = self._sync_simple_field(
                ebay_item_id, token, price=new_value
            )
        elif field == "sku":
            result = self._sync_simple_field(
                ebay_item_id, token, sku=new_value
            )
        elif field == "mpn":
            result = self._sync_item_specifics(
                ebay_item_id, token, entry, mpn=new_value
            )
        elif field == "brand":
            result = self._sync_item_specifics(
                ebay_item_id, token, entry, brand=new_value
            )
        elif field == "inventory":
            try:
                qty = int(new_value)
            except (ValueError, TypeError):
                qty = 1
            result = self._sync_simple_field(
                ebay_item_id, token, quantity=qty
            )
        else:
            result = {
                "success": False,
                "message": f"Unknown sync field: {field}",
            }

        # Attach account info to result
        result["account"] = account_name

        if result.get("success"):
            logger.info(
                f"✅ Synced [{field}] for {ebay_item_id} "
                f"'{old_value}' → '{new_value}' ({account_name})"
            )
            result["message"] = f"Synced ({account_name})"
        else:
            logger.error(
                f"❌ Sync failed [{field}] for {ebay_item_id}: "
                f"{result.get('message')}"
            )

        return result

    def _sync_title(self, entry: dict, item_id: str,
                    new_title: str, token: str) -> Dict[str, Any]:
        """
        Handle title change with automatic description rebuild.

        Process:
            1. GetItem to fetch existing PictureURLs from eBay
            2. Rebuild full HTML description with new title
            3. ReviseItem with title + description + PictureDetails

        The description rebuild ensures the listing description always
        matches the current title, and re-attaching PictureURLs prevents
        eBay from orphaning images when Description is revised.
        """
        logger.info(f"Title change for {item_id} — rebuilding description")

        # Step 1: Fetch existing photos from eBay
        get_result = get_item(item_id, token)
        if not get_result.get("success"):
            # Fall back to title-only revision if GetItem fails
            logger.warning(
                f"GetItem failed for {item_id}, revising title only"
            )
            return revise_item(item_id, token, title=new_title)

        existing_photos = get_result.get("picture_urls", [])
        logger.info(
            f"Retrieved {len(existing_photos)} existing photo(s) from eBay"
        )

        # Step 2: Rebuild description with new title + existing images
        brand = entry.get("brand", "Unbranded") or "Unbranded"
        mpn = entry.get("mpn", "Does Not Apply") or "Does Not Apply"
        condition = entry.get("condition", "Used - Good") or "Used - Good"
        quality_grade = entry.get("quality_grade", "B") or "B"

        revised_description = build_description(
            title=new_title,
            brand=brand,
            mpn=mpn,
            condition=condition,
            quality_grade=quality_grade,
            image_urls=existing_photos,
        )

        # Step 3: Push title + rebuilt description + photos in one call
        return revise_item(
            item_id,
            token,
            title=new_title,
            description_html=revised_description,
            picture_urls=existing_photos,
        )

    def _sync_simple_field(self, item_id: str, token: str,
                           price: str = None, quantity: int = None,
                           sku: str = None) -> Dict[str, Any]:
        """Push a simple field update via ReviseItem."""
        return revise_item(
            item_id, token,
            price=price, quantity=quantity, sku=sku,
        )

    def _sync_item_specifics(self, item_id: str, token: str,
                             entry: dict, brand: str = None,
                             mpn: str = None) -> Dict[str, Any]:
        """Push brand/MPN updates via Item Specifics."""
        specifics = {}
        if brand is not None:
            specifics["Brand"] = brand
        if mpn is not None:
            specifics["Manufacturer Part Number"] = mpn
        return revise_item(item_id, token, item_specifics=specifics)

    def _resolve_account_token(self, entry: dict):
        """
        Determine which eBay account owns this listing and get a token.

        Priority:
            1. Account stored in metadata (entry['ebay_account'])
            2. First configured account (fallback)

        Returns:
            Tuple of (token, account_name) or (None, None) on failure.
        """
        # Try the account recorded in metadata first
        stored_account = entry.get("ebay_account", "").strip()

        if stored_account:
            token = self.auth.get_token(stored_account)
            if token:
                return token, stored_account
            logger.warning(
                f"Stored account '{stored_account}' failed, trying others"
            )

        # Fall back to scanning all accounts
        for account_name in self.auth.account_names:
            token = self.auth.get_token(account_name)
            if token:
                logger.info(f"Using fallback account: {account_name}")
                return token, account_name

        return None, None
