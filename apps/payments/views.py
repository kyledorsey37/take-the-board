import json
import logging

import stripe
from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.services.session import get_authenticated_profile
from apps.bidding.models import Bid

from .models import StripeEvent


logger = logging.getLogger(__name__)


def bid_status(request: HttpRequest, public_id) -> JsonResponse:
    profile = get_authenticated_profile(request)
    if not profile:
        return JsonResponse({"ok": False, "error": "Authentication required."}, status=401)

    try:
        bid = Bid.objects.select_related("board__school").get(
            public_id=public_id,
            bidder=profile,
        )
    except Bid.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Bid not found."}, status=404)

    return JsonResponse(
        {
            "ok": True,
            "status": bid.status,
            "board_url": reverse("schools:detail", kwargs={"slug": bid.board.school.slug}),
        }
    )


@csrf_exempt
@require_POST
def stripe_webhook(request: HttpRequest) -> HttpResponse:
    """Verify and persist Stripe events; business processing happens asynchronously."""
    if not settings.STRIPE_WEBHOOK_SECRET:
        return JsonResponse({"error": "Stripe webhooks are not configured."}, status=503)

    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(
            request.body,
            signature,
            settings.STRIPE_WEBHOOK_SECRET,
        )
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, stripe.error.SignatureVerificationError):
        return JsonResponse({"error": "Invalid Stripe webhook."}, status=400)

    event_id = event["id"]
    event_type = event["type"]
    try:
        with transaction.atomic():
            _, created = StripeEvent.objects.get_or_create(
                event_id=event_id,
                defaults={
                    "event_type": event_type,
                    "payload": payload,
                },
            )
    except IntegrityError:
        # A concurrent retry can race the unique event_id constraint.
        created = False

    if not created:
        return JsonResponse({"received": True, "duplicate": True})

    logger.info("stripe_webhook_received", extra={"stripe_event_type": event_type})
    return JsonResponse({"received": True})
