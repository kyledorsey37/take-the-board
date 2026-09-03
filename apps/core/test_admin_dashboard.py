from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.boards.models import Board, BoardTakeover
from apps.bidding.models import Bid
from apps.moderation.models import MessageReportCase, MessageValidation
from apps.payments.models import PaymentCapture
from apps.schools.models import Competition, Entity


class AdminDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            username="dashboard-admin",
            password="dashboard-password",
        )
        competition = Competition.objects.create(
            name="College Football",
            slug="dashboard-college-football",
            sport="Football",
        )
        entity = Entity.objects.create(
            competition=competition,
            name="Alabama",
            slug="alabama",
            short_name="Alabama",
            group_name="SEC",
            accent_color="#9E1B32",
        )
        cls.board = Board.objects.create(entity=entity)
        cls.profile = UserProfile.objects.create(
            cognito_sub="dashboard-user",
            email="dashboard@example.com",
            display_name="DashboardFan",
        )
        bid = Bid.objects.create(
            board=cls.board,
            bidder=cls.profile,
            represented_entity=entity,
            message="ROLL TIDE.",
            amount_cents=2_500,
            status=Bid.Status.WON,
            captured_at=timezone.now(),
        )
        BoardTakeover.objects.create(
            board=cls.board,
            bid=bid,
            controller=cls.profile,
            controller_display_name=cls.profile.display_name,
            represented_entity=entity,
            message=bid.message,
            amount_cents=bid.amount_cents,
        )
        PaymentCapture.objects.create(
            bid=bid,
            stripe_payment_intent_id="pi_dashboard",
            gross_amount_cents=bid.amount_cents,
            currency="usd",
            captured_at=timezone.now(),
        )
        MessageValidation.objects.create(
            user=cls.profile,
            board=cls.board,
            represented_entity=entity,
            message="BLOCKED MESSAGE",
            message_hash="a" * 64,
            decision=MessageValidation.Decision.BLOCK,
            category="other",
            policy_version="test",
            classifier_version="test",
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        MessageReportCase.objects.create(
            takeover=BoardTakeover.objects.first(),
            last_reported_at=timezone.now(),
        )

    def test_admin_index_renders_operations_home_with_live_data(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Action needed")
        self.assertContains(response, "Resolve reported messages")
        self.assertContains(response, "Audit recent blocks")
        self.assertContains(response, "Captured volume")
        self.assertContains(response, "$25.00")
        self.assertContains(response, "Alabama")
        self.assertContains(response, 'viewBox="0 0 300 155"')
        self.assertContains(response, "/static/css/admin_dashboard.")

        dashboard = response.context["admin_dashboard"]
        self.assertEqual(dashboard["metrics"]["takeover_count"], "1")
        self.assertEqual(dashboard["action_items"][0]["count"], 1)

    def test_admin_index_remains_protected_for_anonymous_users(self):
        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])
