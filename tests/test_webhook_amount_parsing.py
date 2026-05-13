"""Unit tests for webhook amount-parsing in _extract_gift_fields.

Regression coverage for the contribution_purchased minor-unit bug:
  Throne sends contribution_purchased.data.amount in cents (minor units)
  for ALL currencies, not just USD.  gift_purchased uses major units (USD).
"""

import sys
import os
import unittest

# Ensure the repo root is on the path so bot.* imports resolve.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bot.webhook_server import _extract_gift_fields


class TestGiftPurchasedAmountParsing(unittest.TestCase):
    """gift_purchased: Throne sends amountCents (already in minor units)."""

    def test_gift_purchased_amount_cents_field(self):
        """gift_purchased with amountCents:2999 → amount_cents=2999, amount_usd≈29.99

        Throne includes an explicit amountCents field in gift_purchased webhooks;
        the raw_cents path handles this correctly via integer division.
        """
        payload = {
            "event_type": "gift_purchased",
            "data": {
                "gifter_username": "testuser",
                "item_name": "Test Gift",
                "amountCents": 2999,
                "currency": "USD",
            },
        }
        fields = _extract_gift_fields(payload)
        self.assertEqual(fields["amount_cents"], 2999)
        self.assertAlmostEqual(fields["amount_usd"], 29.99, places=2)

    def test_gift_purchased_major_unit_fallback(self):
        """gift_purchased with amount:29.99 (major units) → amount_cents=2999, amount_usd≈29.99

        Fallback for payloads that carry amount in major units instead of amountCents.
        """
        payload = {
            "event_type": "gift_purchased",
            "data": {
                "gifter_username": "testuser",
                "item_name": "Test Gift",
                "amount": 29.99,
                "currency": "USD",
            },
        }
        fields = _extract_gift_fields(payload)
        self.assertEqual(fields["amount_cents"], 2999)
        self.assertAlmostEqual(fields["amount_usd"], 29.99, places=2)


class TestContributionPurchasedAmountParsing(unittest.TestCase):
    """contribution_purchased: amount field is always in minor units (cents)."""

    def _contribution_payload(self, amount, currency):
        return {
            "event_type": "contribution_purchased",
            "data": {
                "creator_username": "angel2adore",
                "gifter_username": "briansadplobo",
                "item_name": "Birthday Presents",
                "amount": amount,
                "currency": currency,
            },
        }

    def test_contribution_eur_minor_units(self):
        """contribution_purchased amount:1500, currency:EUR → amount_cents=1500, amount_usd≈15.00

        This is the exact payload from the production bug report.  The wrong
        behaviour produced amount_cents=150000 and amount_usd=1500.0 because
        the code treated EUR amounts as major units and multiplied by 100.
        """
        fields = _extract_gift_fields(self._contribution_payload(1500, "EUR"))
        self.assertEqual(fields["event_type"], "contribution_purchased")
        self.assertEqual(fields["currency"], "EUR")
        # Key invariant: we must NOT be off by 100×
        self.assertEqual(fields["amount_cents"], 1500)
        self.assertAlmostEqual(fields["amount_usd"], 15.00, places=2)

    def test_contribution_usd_minor_units(self):
        """contribution_purchased amount:999, currency:USD → amount_cents=999, amount_usd≈9.99"""
        fields = _extract_gift_fields(self._contribution_payload(999, "USD"))
        self.assertEqual(fields["amount_cents"], 999)
        self.assertAlmostEqual(fields["amount_usd"], 9.99, places=2)

    def test_contribution_gbp_minor_units(self):
        """contribution_purchased amount:500, currency:GBP → amount_cents=500, amount_usd≈5.00"""
        fields = _extract_gift_fields(self._contribution_payload(500, "GBP"))
        self.assertEqual(fields["amount_cents"], 500)
        self.assertAlmostEqual(fields["amount_usd"], 5.00, places=2)


if __name__ == "__main__":
    unittest.main()
