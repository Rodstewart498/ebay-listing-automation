"""
eBay listing description builder.

Generates professional HTML descriptions with:
- Title, brand, MPN, and condition details
- Quality grade mapping (A/B/C/D scale)
- Hero product images embedded in description
- Return policy and disclaimer sections
- Compatibility verification notice

The same builder is used for both new listings (AddFixedPriceItem)
and title-change revisions (ReviseItem), ensuring consistency.
"""

import html
from datetime import datetime
from typing import List, Optional


# Quality grade → condition description mapping
QUALITY_GRADES = {
    'A': (
        "Excellent condition. Minimal signs of use — clean, fully functional, "
        "and ready for installation. May have very light surface marks consistent "
        "with brief use."
    ),
    'B': (
        "Good condition. Shows normal signs of use including minor scratches, "
        "scuffs, or wear. Fully functional and ready for installation."
    ),
    'C': (
        "Fair condition. Shows moderate signs of use including scratches, scuffs, "
        "fading, or cosmetic wear. Functional but may have cosmetic imperfections."
    ),
    'D': (
        "Rough condition. Shows heavy signs of use, significant cosmetic wear, "
        "or minor damage. Sold as-is — may need cleaning or minor repair."
    ),
}

# Fallback condition descriptions when no quality grade is set
CONDITION_DESCRIPTIONS = {
    'Used - Excellent': "Used item in excellent condition with minimal signs of wear.",
    'Used - Good': "Used item in good working condition with normal signs of wear.",
    'Used - Fair': "Used item in fair condition. Functional but shows wear.",
    'For Parts': "Sold for parts or not working. No guarantee of functionality.",
}

LISTING_DISCLAIMER = """
<div style="margin-top: 30px; padding: 20px; background-color: #f9f9f9;
     border: 1px solid #ddd; border-radius: 8px; font-size: 14px; color: #555;">
<h3 style="color: #333; margin-top: 0;">📋 Return Policy & Buyer Information</h3>
<p>We stand behind our products. If the item does not match the description
or arrives damaged, we'll make it right.</p>
<ul>
<li><strong>Returns accepted within 30 days</strong> of delivery for items
that are not as described or arrive damaged.</li>
<li>Buyer is responsible for return shipping costs unless the return is
due to our error.</li>
<li>Items must be returned in the same condition as received.</li>
<li>We reserve the right to deny a return if the item shows signs of
damage, tampering, or use not related to our mistake.</li>
</ul>
<p>Thank you for choosing us! If you have any questions about your order
or our policies, please don't hesitate to reach out.</p>
<p style="color: #888; font-size: 12px;">Listed: {date}</p>
</div>
"""


def build_description(
    title: str,
    brand: str = "Unbranded",
    mpn: str = "Does Not Apply",
    condition: str = "Used - Good",
    quality_grade: str = "B",
    image_urls: Optional[List[str]] = None,
) -> str:
    """
    Build a complete HTML listing description.

    This is the single source of truth for all listing descriptions —
    used by both new listing creation and title-change revisions.

    Args:
        title: Listing title (max 80 chars for eBay).
        brand: Product brand name.
        mpn: Manufacturer part number.
        condition: eBay condition string.
        quality_grade: Quality grade (A, B, C, D, or N/A).
        image_urls: List of eBay-hosted image URLs for hero section.

    Returns:
        Complete HTML string ready for CDATA wrapping in XML payload.
    """
    # Resolve condition description from quality grade or condition string
    if quality_grade and quality_grade.upper() in QUALITY_GRADES:
        condition_desc = QUALITY_GRADES[quality_grade.upper()]
    else:
        condition_desc = CONDITION_DESCRIPTIONS.get(
            condition, "Used item in functional condition."
        )

    # Build the base description section
    base_html = f"""<div style="font-family: Arial, sans-serif; padding: 20px;">
<h2 style="color: #333; border-bottom: 2px solid #0066cc; padding-bottom: 10px;">
    {html.escape(title)}
</h2>
<p style="font-size: 16px; margin: 15px 0;">
    <strong>Brand:</strong> {html.escape(brand)}
</p>
<p style="font-size: 16px; margin: 15px 0;">
    <strong>Manufacturer Part Number:</strong> {html.escape(mpn)}
</p>
<p style="font-size: 16px; margin: 15px 0;">
    <strong>Condition:</strong> {html.escape(condition_desc)}
</p>
<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
<p style="color: #666;">Please verify compatibility with your specific
make, model, and year before purchasing.</p>
</div>
"""

    # Build hero images section
    hero_html = _build_hero_images(image_urls or [])

    # Build disclaimer with current date
    disclaimer_html = LISTING_DISCLAIMER.format(
        date=datetime.now().strftime("%B %d, %Y")
    )

    return base_html + hero_html + disclaimer_html


def _build_hero_images(image_urls: List[str], max_images: int = 12) -> str:
    """
    Build responsive hero image gallery HTML.

    Images are displayed in a centered grid with consistent sizing
    and rounded corners. Limited to max_images to keep description
    length reasonable.

    Args:
        image_urls: List of eBay EPS-hosted image URLs.
        max_images: Maximum number of images to include.

    Returns:
        HTML string for the hero image section.
    """
    if not image_urls:
        return ""

    image_tags = []
    for url in image_urls[:max_images]:
        safe_url = html.escape(url)
        image_tags.append(
            f'<img src="{safe_url}" '
            f'style="max-width: 500px; width: 100%; height: auto; '
            f'border-radius: 8px; margin: 10px auto; display: block;" '
            f'alt="Product photo" />'
        )

    images_html = "\n".join(image_tags)

    return f"""
<div style="margin: 20px 0; text-align: center;">
<h3 style="color: #333;">📸 Product Photos</h3>
{images_html}
</div>
"""
