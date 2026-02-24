"""
eBay listing creation pipeline.

Handles the full lifecycle of creating a new eBay listing:
    1. Resolve business policies (shipping, payment, return)
    2. Calculate package specs from shipping tier
    3. Apply psychological pricing (configurable snap endings)
    4. Enforce minimum price floor (configurable)
    5. Build description HTML with hero images
    6. Construct AddFixedPriceItem XML payload
    7. Submit to eBay Trading API
    8. Return new item ID

Includes UPS dimensional weight cap enforcement to prevent
listings with package dimensions that exceed carrier limits.
"""

import os
import re
import html
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from xml.sax.saxutils import escape as xml_escape

import requests

from .description import build_description
from .trading_api import TRADING_API_URL, _build_headers, _check_success

logger = logging.getLogger(__name__)

# Minimum listing price — configure for your margin requirements
# Set this based on your fee structure (FVF + promo + shipping cost)
PRICE_FLOOR = float(os.environ.get("PRICE_FLOOR", "4.99"))

# UPS Ground dimensional weight cap: L×W×H÷139 must not exceed 150 lbs
DIM_WEIGHT_DIVISOR = 139.0
DIM_WEIGHT_MAX_LBS = 150

# Shipping tier → default package dimensions mapping
# Configure these for your product category's typical package sizes
# Shipping tier package specs — configure for your product line.
# Override via TIER_SPECS_PATH env var pointing to a JSON file,
# or modify defaults below. Dimensions in inches, weight in lbs/oz.
TIER_PACKAGE_SPECS = {
    "small":      {"weight_lbs": 1, "weight_oz": 0,
                   "length": 8, "width": 6, "height": 3},
    "medium":     {"weight_lbs": 3, "weight_oz": 0,
                   "length": 12, "width": 10, "height": 6},
    "large":      {"weight_lbs": 8, "weight_oz": 0,
                   "length": 18, "width": 12, "height": 8},
    "extra_large": {"weight_lbs": 15, "weight_oz": 0,
                    "length": 24, "width": 16, "height": 12},
    "calculated": {"weight_lbs": 3, "weight_oz": 0,
                   "length": 12, "width": 10, "height": 6},
}


def snap_to_psychological_price(raw_price: float) -> str:
    """
    Snap a price to psychological pricing endings.

    Standard retail pricing psychology — prices ending in certain
    values convert better than arbitrary decimal amounts.

    The snap thresholds and target endings are configurable via
    PRICE_SNAP_HIGH and PRICE_SNAP_LOW environment variables.

    Also enforces the minimum price floor.

    Args:
        raw_price: Raw calculated price.

    Returns:
        Price string with psychological ending.
    """
    snap_high = os.environ.get("PRICE_SNAP_HIGH", "95")
    snap_low = os.environ.get("PRICE_SNAP_LOW", "50")
    snap_threshold = float(os.environ.get("PRICE_SNAP_THRESHOLD", "0.50"))

    if raw_price < PRICE_FLOOR:
        raw_price = PRICE_FLOOR

    dollars = int(raw_price)
    cents = raw_price - dollars
    snapped = f"{dollars}.{snap_high if cents >= snap_threshold else snap_low}"

    if float(snapped) < PRICE_FLOOR:
        snapped = str(PRICE_FLOOR)

    return snapped


def bake_price(base_price: float, bake_rate: float = None) -> str:
    """
    Bake promotional discount coverage into the listing price.

    If you run sales or coupon promotions, the listing price needs
    to be higher than your target net price to maintain margins.

    Args:
        base_price: Target net price after discounts.
        bake_rate: Total discount rate to absorb.
            Defaults to BAKE_RATE env var or 0.0 (no bake).

    Returns:
        Baked and psychologically-snapped price string.
    """
    if bake_rate is None:
        bake_rate = float(os.environ.get("BAKE_RATE", "0.0"))
    baked = round(base_price / (1.0 - bake_rate), 2)
    return snap_to_psychological_price(baked)


def get_package_specs(shipping_tier: str) -> dict:
    """
    Get package dimensions for a shipping tier.

    Args:
        shipping_tier: Tier name (small, medium, large, etc.)

    Returns:
        Dict with weight_lbs, weight_oz, length, width, height.
    """
    tier_key = shipping_tier.lower().strip().replace(" ", "_")
    return TIER_PACKAGE_SPECS.get(tier_key, TIER_PACKAGE_SPECS["calculated"])


def _enforce_dim_weight_cap(specs: dict) -> dict:
    """
    Enforce UPS dimensional weight cap.

    If L×W×H÷139 exceeds 150 lbs, scale dimensions down uniformly.

    Args:
        specs: Package specs dict with length, width, height.

    Returns:
        Possibly adjusted specs dict.
    """
    length = int(specs.get("length", 12))
    width = int(specs.get("width", 12))
    height = int(specs.get("height", 6))

    dim_weight = (length * width * height) / DIM_WEIGHT_DIVISOR

    if dim_weight > DIM_WEIGHT_MAX_LBS:
        scale = (DIM_WEIGHT_MAX_LBS * DIM_WEIGHT_DIVISOR
                 / (length * width * height)) ** (1 / 3)
        specs = dict(specs)  # Don't mutate original
        specs["length"] = max(1, int(length * scale))
        specs["width"] = max(1, int(width * scale))
        specs["height"] = max(1, int(height * scale))

        logger.warning(
            f"Dim weight cap enforced: {length}x{width}x{height} → "
            f"{specs['length']}x{specs['width']}x{specs['height']}"
        )

    return specs


def build_listing_xml(
    title: str,
    price: str,
    sku: str,
    image_urls: List[str],
    category_id: str = "0",
    brand: str = "Unbranded",
    mpn: str = "Does Not Apply",
    fulfillment_policy_id: str = "",
    payment_policy_id: str = "",
    return_policy_id: str = "",
    package_specs: Optional[dict] = None,
    condition: str = "Used - Good",
    quality_grade: str = "B",
) -> str:
    """
    Build complete AddFixedPriceItem XML payload.

    Constructs the full XML including:
    - Item details (title, price, quantity, SKU)
    - Description HTML with hero images
    - Picture URLs (up to 24)
    - Business policy references
    - Shipping package details
    - Item specifics (brand, MPN)
    - Category (configurable — set DEFAULT_CATEGORY_ID for your niche)

    Args:
        title: Listing title (max 80 chars).
        price: Listing price string.
        sku: Custom label (used as eBay Custom Label / SKU field).
        image_urls: List of eBay EPS-hosted image URLs.
        category_id: eBay category ID for your product niche.
        brand: Product brand.
        mpn: Manufacturer part number.
        fulfillment_policy_id: eBay shipping policy ID.
        payment_policy_id: eBay payment policy ID.
        return_policy_id: eBay return policy ID.
        package_specs: Package dimensions dict.
        condition: eBay condition string.
        quality_grade: Quality grade (A/B/C/D).

    Returns:
        Complete XML string ready for submission.
    """
    if package_specs is None:
        package_specs = TIER_PACKAGE_SPECS["calculated"]

    package_specs = _enforce_dim_weight_cap(package_specs)

    # Build description HTML
    description_html = build_description(
        title=title,
        brand=brand,
        mpn=mpn,
        condition=condition,
        quality_grade=quality_grade,
        image_urls=image_urls,
    )
    desc_cdata = f"<![CDATA[{description_html}]]>"

    # Build PictureURL tags (max 24)
    picture_urls_xml = ""
    for url in image_urls[:24]:
        picture_urls_xml += (
            f"      <PictureURL>{html.escape(url)}</PictureURL>\n"
        )

    # Map condition string to eBay condition ID
    condition_map = {
        "New": "1000",
        "Used - Excellent": "3000",
        "Used - Very Good": "3000",
        "Used - Good": "3000",
        "Used - Fair": "3000",
        "For Parts": "7000",
    }
    condition_id = condition_map.get(condition, "3000")

    # Package dimensions
    weight_lbs = int(package_specs.get("weight_lbs", 2))
    weight_oz = int(package_specs.get("weight_oz", 0))
    pkg_length = int(package_specs.get("length", 12))
    pkg_width = int(package_specs.get("width", 12))
    pkg_height = int(package_specs.get("height", 6))

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<AddFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <ErrorLanguage>en_US</ErrorLanguage>
  <WarningLevel>High</WarningLevel>
  <Item>
    <Title>{xml_escape(title[:80])}</Title>
    <Description>{desc_cdata}</Description>
    <PrimaryCategory>
      <CategoryID>{xml_escape(str(category_id))}</CategoryID>
    </PrimaryCategory>
    <StartPrice currencyID="USD">{xml_escape(str(price))}</StartPrice>
    <ConditionID>{condition_id}</ConditionID>
    <Country>US</Country>
    <Currency>USD</Currency>
    <ListingDuration>GTC</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    <Location>PA</Location>
    <Quantity>1</Quantity>
    <SKU>{xml_escape(sku)}</SKU>
    <PictureDetails>
{picture_urls_xml}    </PictureDetails>
    <ItemSpecifics>
      <NameValueList>
        <Name>Brand</Name>
        <Value>{xml_escape(brand)}</Value>
      </NameValueList>
      <NameValueList>
        <Name>Manufacturer Part Number</Name>
        <Value>{xml_escape(mpn)}</Value>
      </NameValueList>
    </ItemSpecifics>
    <SellerProfiles>
      <SellerShippingProfile>
        <ShippingProfileID>{xml_escape(fulfillment_policy_id)}</ShippingProfileID>
      </SellerShippingProfile>
      <SellerPaymentProfile>
        <PaymentProfileID>{xml_escape(payment_policy_id)}</PaymentProfileID>
      </SellerPaymentProfile>
      <SellerReturnProfile>
        <ReturnProfileID>{xml_escape(return_policy_id)}</ReturnProfileID>
      </SellerReturnProfile>
    </SellerProfiles>
    <ShippingPackageDetails>
      <WeightMajor unit="lbs">{weight_lbs}</WeightMajor>
      <WeightMinor unit="oz">{weight_oz}</WeightMinor>
      <PackageLength unit="in">{pkg_length}</PackageLength>
      <PackageWidth unit="in">{pkg_width}</PackageWidth>
      <PackageDepth unit="in">{pkg_height}</PackageDepth>
    </ShippingPackageDetails>
  </Item>
</AddFixedPriceItemRequest>"""

    return xml
