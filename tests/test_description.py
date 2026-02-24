"""Tests for the HTML description builder."""

import pytest

from ebay_automation.description import (
    build_description, _build_hero_images,
    QUALITY_GRADES, CONDITION_DESCRIPTIONS,
)


class TestBuildDescription:
    """Tests for the main description builder."""

    def test_includes_title(self):
        html = build_description(title="Replacement Water Pump Assembly")
        assert "Replacement Water Pump Assembly" in html

    def test_includes_brand(self):
        html = build_description(title="Test Part", brand="OEM")
        assert "OEM" in html

    def test_includes_mpn(self):
        html = build_description(title="Test Part", mpn="ABC-12345")
        assert "ABC-12345" in html

    def test_quality_grade_a(self):
        html = build_description(title="Test", quality_grade="A")
        assert "Excellent condition" in html

    def test_quality_grade_b(self):
        html = build_description(title="Test", quality_grade="B")
        assert "Good condition" in html

    def test_quality_grade_c(self):
        html = build_description(title="Test", quality_grade="C")
        assert "Fair condition" in html

    def test_quality_grade_d(self):
        html = build_description(title="Test", quality_grade="D")
        assert "Rough condition" in html

    def test_fallback_condition_no_grade(self):
        html = build_description(
            title="Test", quality_grade="", condition="Used - Good"
        )
        assert "good working condition" in html

    def test_includes_disclaimer(self):
        html = build_description(title="Test")
        assert "Return Policy" in html

    def test_includes_compatibility_notice(self):
        html = build_description(title="Test")
        assert "verify compatibility" in html

    def test_escapes_html_in_title(self):
        html = build_description(title='Test <script>alert("xss")</script>')
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_with_images(self):
        urls = ["https://i.ebayimg.com/images/test1.jpg"]
        html = build_description(title="Test", image_urls=urls)
        assert "test1.jpg" in html
        assert "Product Photos" in html

    def test_without_images(self):
        html = build_description(title="Test", image_urls=[])
        assert "Product Photos" not in html

    def test_returns_string(self):
        result = build_description(title="Test")
        assert isinstance(result, str)
        assert len(result) > 100


class TestBuildHeroImages:
    """Tests for the hero image gallery builder."""

    def test_empty_list_returns_empty(self):
        assert _build_hero_images([]) == ""

    def test_single_image(self):
        html = _build_hero_images(["https://example.com/img.jpg"])
        assert "img.jpg" in html

    def test_max_images_cap(self):
        urls = [f"https://example.com/img{i}.jpg" for i in range(20)]
        html = _build_hero_images(urls, max_images=12)
        assert "img11.jpg" in html
        assert "img12.jpg" not in html

    def test_escapes_urls(self):
        html = _build_hero_images(["https://example.com/img?a=1&b=2"])
        assert "&amp;" in html


class TestQualityGrades:
    """Tests for quality grade configuration."""

    def test_all_grades_present(self):
        assert 'A' in QUALITY_GRADES
        assert 'B' in QUALITY_GRADES
        assert 'C' in QUALITY_GRADES
        assert 'D' in QUALITY_GRADES

    def test_all_conditions_present(self):
        assert 'Used - Excellent' in CONDITION_DESCRIPTIONS
        assert 'Used - Good' in CONDITION_DESCRIPTIONS
        assert 'For Parts' in CONDITION_DESCRIPTIONS
