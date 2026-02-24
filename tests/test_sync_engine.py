"""Tests for the unified field-level sync engine."""

from unittest.mock import MagicMock, patch
import pytest

from ebay_automation.sync_engine import SyncEngine


@pytest.fixture
def mock_auth():
    """Create a mock auth manager."""
    auth = MagicMock()
    auth.account_names = ["TestAccount1", "TestAccount2"]
    auth.get_token.return_value = "mock_token_abc123"
    return auth


@pytest.fixture
def engine(mock_auth):
    """Create a SyncEngine with mocked auth."""
    return SyncEngine(mock_auth)


@pytest.fixture
def sample_entry():
    """Sample metadata entry for testing."""
    return {
        "ebay_item_id": "123456789012",
        "title": "Replacement Exhaust Manifold Assembly 2004-2008",
        "brand": "OEM",
        "mpn": "ABC-12345-00-00",
        "condition": "Used - Good",
        "quality_grade": "B",
        "ebay_account": "TestAccount1",
    }


class TestSyncField:
    """Tests for the main sync_field entry point."""

    def test_missing_item_id_skips(self, engine):
        entry = {"title": "Test"}
        result = engine.sync_field(entry, "title", "New Title")
        assert result["success"] is False
        assert "skipped" in result

    def test_empty_item_id_skips(self, engine):
        entry = {"ebay_item_id": "", "title": "Test"}
        result = engine.sync_field(entry, "title", "New Title")
        assert result["success"] is False

    def test_no_token_fails(self, engine, sample_entry):
        engine.auth.get_token.return_value = None
        result = engine.sync_field(sample_entry, "price", "29.95")
        assert result["success"] is False
        assert "token" in result["message"].lower()

    @patch('ebay_automation.sync_engine.revise_item')
    def test_price_sync(self, mock_revise, engine, sample_entry):
        mock_revise.return_value = {"success": True, "message": "OK"}
        result = engine.sync_field(sample_entry, "price", "49.95", "39.95")
        assert result["success"] is True
        mock_revise.assert_called_once()

    @patch('ebay_automation.sync_engine.revise_item')
    def test_sku_sync(self, mock_revise, engine, sample_entry):
        mock_revise.return_value = {"success": True, "message": "OK"}
        result = engine.sync_field(sample_entry, "sku", "BIN-A12", "BIN-A10")
        assert result["success"] is True

    @patch('ebay_automation.sync_engine.revise_item')
    def test_inventory_sync_converts_to_int(self, mock_revise, engine, sample_entry):
        mock_revise.return_value = {"success": True, "message": "OK"}
        engine.sync_field(sample_entry, "inventory", "5", "1")
        call_kwargs = mock_revise.call_args
        assert call_kwargs[1].get('quantity') == 5 or call_kwargs.kwargs.get('quantity') == 5

    def test_unknown_field_fails(self, engine, sample_entry):
        result = engine.sync_field(sample_entry, "nonexistent", "value")
        assert result["success"] is False
        assert "Unknown" in result["message"]

    @patch('ebay_automation.sync_engine.revise_item')
    def test_account_name_in_result(self, mock_revise, engine, sample_entry):
        mock_revise.return_value = {"success": True, "message": "OK"}
        result = engine.sync_field(sample_entry, "price", "29.95")
        assert "account" in result


class TestSyncTitle:
    """Tests for title sync with description rebuild."""

    @patch('ebay_automation.sync_engine.revise_item')
    @patch('ebay_automation.sync_engine.get_item')
    def test_title_fetches_photos_first(self, mock_get, mock_revise,
                                        engine, sample_entry):
        mock_get.return_value = {
            "success": True,
            "picture_urls": ["https://i.ebayimg.com/test.jpg"],
        }
        mock_revise.return_value = {"success": True, "message": "OK"}

        engine.sync_field(sample_entry, "title", "New Title", "Old Title")
        mock_get.assert_called_once()

    @patch('ebay_automation.sync_engine.revise_item')
    @patch('ebay_automation.sync_engine.get_item')
    def test_title_falls_back_on_getitem_failure(self, mock_get, mock_revise,
                                                  engine, sample_entry):
        mock_get.return_value = {"success": False, "message": "Not found"}
        mock_revise.return_value = {"success": True, "message": "OK"}

        engine.sync_field(sample_entry, "title", "New Title")
        # Should still call revise_item (title-only fallback)
        mock_revise.assert_called_once()


class TestAccountResolution:
    """Tests for multi-account token resolution."""

    def test_uses_stored_account(self, engine, sample_entry):
        token, name = engine._resolve_account_token(sample_entry)
        assert name == "TestAccount1"

    def test_falls_back_when_stored_fails(self, engine, sample_entry):
        # First call (stored account) fails, second succeeds
        engine.auth.get_token.side_effect = [None, "fallback_token"]
        token, name = engine._resolve_account_token(sample_entry)
        assert token == "fallback_token"

    def test_returns_none_when_all_fail(self, engine, sample_entry):
        engine.auth.get_token.return_value = None
        token, name = engine._resolve_account_token(sample_entry)
        assert token is None
        assert name is None
