from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bidding.models import BidRiskConfig
from apps.bidding.services.risk import RiskReason, recalculate_risk_tier, validate_bid_risk
from apps.payments.models import LedgerEntry


class BidRiskTests(TestCase):
    def setUp(self) -> None:
        self.user = UserProfile.objects.create(
            cognito_sub="risk-subject", email="risk@example.com", display_name="RiskFan"
        )

    def test_new_user_bid_cap_and_rolling_spend_are_enforced(self) -> None:
        self.assertEqual(validate_bid_risk(self.user, 5000).allowed, True)
        oversized = validate_bid_risk(self.user, 5001)
        self.assertFalse(oversized.allowed)
        self.assertEqual(oversized.reason, RiskReason.BID_TOO_LARGE)

        LedgerEntry.objects.create(
            type=LedgerEntry.Type.BID_CAPTURE, amount_cents=8000, user=self.user
        )
        limited = validate_bid_risk(self.user, 2500)
        self.assertFalse(limited.allowed)
        self.assertEqual(limited.reason, RiskReason.HOURLY_LIMIT_EXCEEDED)

    def test_captured_history_promotes_an_account_and_open_dispute_suspends_it(self) -> None:
        self.user.successful_bid_count = 3
        self.user.created_at = timezone.now() - timedelta(hours=25)
        self.user.save(update_fields=["successful_bid_count", "created_at"])
        self.assertEqual(recalculate_risk_tier(self.user), UserProfile.RiskTier.ESTABLISHED)

        self.user.has_open_dispute = True
        self.user.save(update_fields=["has_open_dispute"])
        self.assertEqual(recalculate_risk_tier(self.user), UserProfile.RiskTier.SUSPENDED)
        decision = validate_bid_risk(self.user, 100)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, RiskReason.ACCOUNT_SUSPENDED)

    def test_high_value_confirmation_thresholds_are_configurable(self) -> None:
        BidRiskConfig.objects.create(
            high_value_confirmation_threshold_cents=5000,
            very_high_value_confirmation_threshold_cents=10000,
        )
        normal = validate_bid_risk(self.user, 4900)
        high = validate_bid_risk(self.user, 5000)
        very_high = validate_bid_risk(self.user, 10000)
        self.assertFalse(normal.requires_extra_confirmation)
        self.assertTrue(high.requires_extra_confirmation)
        self.assertFalse(high.requires_typed_confirmation)
        self.assertTrue(very_high.requires_typed_confirmation)
