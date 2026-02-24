"""
eBay Trading API client.

Handles XML/SOAP communication with eBay's Trading API for:
    - ReviseItem (update existing listings)
    - GetItem (fetch listing details including photos)
    - AddFixedPriceItem (create new listings)
    - EndItem (archive/end listings)

All calls include error handling for common eBay API responses
including rate limiting (Error 518), invalid tokens, and item-not-found.
"""

import re
import html
import logging
from typing import Optional, Dict, Any, List
from xml.sax.saxutils import escape as xml_escape

import requests

logger = logging.getLogger(__name__)

# eBay Trading API endpoint (production)
TRADING_API_URL = "https://api.ebay.com/ws/api.dll"

# API compatibility level — update periodically
COMPAT_LEVEL = "1225"


def _build_headers(call_name: str, token: str) -> dict:
    """
    Build HTTP headers for a Trading API call.

    Args:
        call_name: eBay API call name (e.g., 'ReviseItem', 'GetItem').
        token: Valid OAuth access token.

    Returns:
        Headers dict ready for requests.post().
    """
    return {
        "X-EBAY-API-SITEID": "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT_LEVEL,
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-IAF-TOKEN": token,
        "Content-Type": "text/xml; charset=utf-8",
    }


def _check_success(response_text: str) -> Dict[str, Any]:
    """
    Parse an eBay Trading API XML response for success/failure.

    Checks for Ack=Success or Ack=Warning (both are OK), and
    extracts error details on failure.

    Args:
        response_text: Raw XML response body.

    Returns:
        Dict with 'success', 'ack', 'errors', and 'warnings'.
    """
    ack_match = re.search(r'<Ack>(.*?)</Ack>', response_text)
    ack = ack_match.group(1) if ack_match else "Unknown"

    result = {
        "success": ack in ("Success", "Warning"),
        "ack": ack,
        "errors": [],
        "warnings": [],
    }

    # Extract errors
    for error_match in re.finditer(
        r'<Errors>(.*?)</Errors>', response_text, re.DOTALL
    ):
        error_block = error_match.group(1)
        severity = re.search(r'<SeverityCode>(.*?)</SeverityCode>', error_block)
        code = re.search(r'<ErrorCode>(.*?)</ErrorCode>', error_block)
        message = re.search(r'<LongMessage>(.*?)</LongMessage>', error_block)

        entry = {
            "severity": severity.group(1) if severity else "Unknown",
            "code": code.group(1) if code else "0",
            "message": message.group(1) if message else "Unknown error",
        }

        if entry["severity"] == "Error":
            result["errors"].append(entry)
        else:
            result["warnings"].append(entry)

    if result["errors"]:
        result["success"] = False
        result["message"] = result["errors"][0]["message"]
    elif not result["success"]:
        result["message"] = f"API returned Ack={ack}"
    else:
        result["message"] = "Success"

    return result


def get_item(item_id: str, token: str) -> Dict[str, Any]:
    """
    Fetch an existing eBay listing's details via GetItem.

    Used primarily to retrieve PictureURLs before rebuilding
    descriptions on title changes.

    Args:
        item_id: eBay item ID.
        token: Valid OAuth access token.

    Returns:
        Dict with 'success', 'picture_urls', 'title', etc.
    """
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <ErrorLanguage>en_US</ErrorLanguage>
  <WarningLevel>High</WarningLevel>
  <ItemID>{xml_escape(str(item_id))}</ItemID>
  <OutputSelector>Item.PictureDetails</OutputSelector>
  <OutputSelector>Item.Title</OutputSelector>
  <OutputSelector>Item.SKU</OutputSelector>
</GetItemRequest>"""

    try:
        response = requests.post(
            TRADING_API_URL,
            headers=_build_headers("GetItem", token),
            data=xml.encode('utf-8'),
            timeout=30,
        )

        result = _check_success(response.text)

        if result["success"]:
            # Extract PictureURLs
            urls = re.findall(
                r'<PictureURL>(.*?)</PictureURL>', response.text
            )
            result["picture_urls"] = urls

            title_match = re.search(r'<Title>(.*?)</Title>', response.text)
            if title_match:
                result["title"] = html.unescape(title_match.group(1))

        return result

    except requests.RequestException as e:
        logger.error(f"GetItem request failed for {item_id}: {e}")
        return {"success": False, "message": str(e)}


def revise_item(item_id: str, token: str,
                title: str = None,
                price: str = None,
                quantity: int = None,
                sku: str = None,
                description_html: str = None,
                picture_urls: List[str] = None,
                item_specifics: Dict[str, str] = None) -> Dict[str, Any]:
    """
    Revise an existing eBay listing via ReviseItem.

    Only includes fields that are explicitly provided — eBay's API
    only updates fields present in the XML payload.

    Args:
        item_id: eBay item ID to revise.
        token: Valid OAuth access token.
        title: New title (triggers description rebuild upstream).
        price: New price string.
        quantity: New quantity.
        sku: New SKU/custom label.
        description_html: Full HTML description (for title changes).
        picture_urls: List of picture URLs to re-attach.
        item_specifics: Dict of name→value pairs for Item Specifics.

    Returns:
        Dict with 'success' and 'message'.
    """
    # Build only the XML elements for fields being updated
    fields_xml = ""

    if title is not None:
        fields_xml += f"    <Title>{xml_escape(title[:80])}</Title>\n"

    if price is not None:
        fields_xml += (
            f'    <StartPrice currencyID="USD">'
            f'{xml_escape(str(price))}</StartPrice>\n'
        )

    if quantity is not None:
        fields_xml += f"    <Quantity>{int(quantity)}</Quantity>\n"

    if sku is not None:
        fields_xml += f"    <SKU>{xml_escape(sku)}</SKU>\n"

    if description_html is not None:
        desc_cdata = f"<![CDATA[{description_html}]]>"
        fields_xml += f"    <Description>{desc_cdata}</Description>\n"

    if picture_urls:
        fields_xml += "    <PictureDetails>\n"
        for url in picture_urls[:24]:
            fields_xml += (
                f"      <PictureURL>{html.escape(url)}</PictureURL>\n"
            )
        fields_xml += "    </PictureDetails>\n"

    if item_specifics:
        fields_xml += "    <ItemSpecifics>\n"
        for name, value in item_specifics.items():
            fields_xml += (
                f"      <NameValueList>\n"
                f"        <Name>{xml_escape(name)}</Name>\n"
                f"        <Value>{xml_escape(value)}</Value>\n"
                f"      </NameValueList>\n"
            )
        fields_xml += "    </ItemSpecifics>\n"

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <ErrorLanguage>en_US</ErrorLanguage>
  <WarningLevel>High</WarningLevel>
  <Item>
    <ItemID>{xml_escape(str(item_id))}</ItemID>
{fields_xml}  </Item>
</ReviseItemRequest>"""

    try:
        response = requests.post(
            TRADING_API_URL,
            headers=_build_headers("ReviseItem", token),
            data=xml.encode('utf-8'),
            timeout=30,
        )

        result = _check_success(response.text)

        # Check for rate limiting (Error 518)
        for error in result.get("errors", []):
            if error.get("code") == "518":
                result["rate_limited"] = True
                logger.warning(f"Rate limited on ReviseItem for {item_id}")

        return result

    except requests.RequestException as e:
        logger.error(f"ReviseItem request failed for {item_id}: {e}")
        return {"success": False, "message": str(e)}
