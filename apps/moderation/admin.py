from django.contrib import admin, messages
from django.db.models import Count, F
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from apps.bidding.models import Bid

from .models import (
    DisplayNameValidation,
    MessageReport,
    MessageReportCase,
    ModerationActionAudit,
    ModerationPaymentAction,
    MessageValidation,
)
from .services.operations import audit_action
from .services.payment_actions import process_payment_action
from .services.report_cases import approve_case, remove_case


@admin.register(MessageValidation)
class MessageValidationAdmin(ModelAdmin):
    list_display = ("public_id", "user", "board", "represented_entity", "decision", "category", "expires_at")
    list_filter = ("decision", "category", "represented_entity", "expires_at")
    search_fields = ("public_id", "user__display_name", "board__entity__name", "message_hash")
    readonly_fields = ("public_id", "created_at", "consumed_at", "message_hash", "policy_version", "classifier_version")


@admin.register(DisplayNameValidation)
class DisplayNameValidationAdmin(ModelAdmin):
    list_display = ("public_id", "user", "decision", "category", "expires_at")
    list_filter = ("decision", "category", "expires_at")
    search_fields = ("public_id", "user__display_name", "candidate_hash")
    readonly_fields = ("public_id", "created_at", "consumed_at", "candidate_hash", "policy_version", "classifier_version")


@admin.register(ModerationActionAudit)
class ModerationActionAuditAdmin(ModelAdmin):
    list_display = ("action", "target_type", "target_id", "actor", "created_at")
    list_filter = ("action", "target_type")
    search_fields = ("target_id", "reason", "actor__username")
    readonly_fields = ("actor", "target_type", "target_id", "action", "reason", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class IsCurrentTakeoverFilter(admin.SimpleListFilter):
    title = "target is currently live"
    parameter_name = "is_current"

    def lookups(self, request, model_admin):
        return (("yes", "Yes"), ("no", "No"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(takeover__board__current_bid_id=F("takeover__bid_id"))
        if self.value() == "no":
            return queryset.exclude(takeover__board__current_bid_id=F("takeover__bid_id"))
        return queryset


@admin.register(MessageReportCase)
class MessageReportCaseAdmin(ModelAdmin):
    change_form_template = "admin/moderation/messagereportcase/change_form.html"
    list_display = (
        "opened_at",
        "last_reported_at",
        "board_school",
        "takeover_occurred_at",
        "message_preview",
        "status",
        "report_count",
        "category_summary",
    )
    list_filter = (
        "status",
        "takeover__board__entity",
        "reports__category",
        "opened_at",
        "resolved_at",
        IsCurrentTakeoverFilter,
    )
    search_fields = (
        "public_id",
        "takeover__public_id",
        "takeover__board__entity__name",
        "takeover__controller_display_name",
        "takeover__bid__public_id",
    )
    readonly_fields = (
        "public_id",
        "takeover",
        "reported_message",
        "review_context",
        "payment_context",
        "status",
        "opened_at",
        "last_reported_at",
        "resolved_at",
        "resolved_by",
        "resolution_reason",
        "created_at",
        "updated_at",
    )
    fields = readonly_fields

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "takeover__board__entity",
            "takeover__bid",
            "takeover__bid__payment_capture",
            "takeover__represented_entity",
            "takeover__controller",
        ).annotate(_report_count=Count("reports", distinct=True))

    @admin.display(description="Board / school")
    def board_school(self, obj):
        return obj.takeover.board.entity.name

    @admin.display(description="Takeover at")
    def takeover_occurred_at(self, obj):
        return obj.takeover.occurred_at

    @admin.display(description="Message")
    def message_preview(self, obj):
        return obj.takeover.message

    @admin.display(description="Reports", ordering="_report_count")
    def report_count(self, obj):
        return obj._report_count

    @admin.display(description="Categories")
    def category_summary(self, obj):
        counts = obj.reports.values("category").annotate(total=Count("id")).order_by("category")
        return ", ".join(f"{item['category']}: {item['total']}" for item in counts)

    @admin.display(description="Reported message")
    def reported_message(self, obj):
        return format_html(
            '<div class="border border-base-200 rounded-default px-3 py-2 dark:border-base-700">{}</div>',
            obj.takeover.message,
        )

    @admin.display(description="Review context")
    def review_context(self, obj):
        takeover = obj.takeover
        current = takeover.board.current_bid_id == takeover.bid_id
        prior = takeover.previous_bid_id or "None"
        return format_html(
            "<p><strong>Controller:</strong> {}</p><p><strong>Representing:</strong> {}</p>"
            "<p><strong>Takeover amount:</strong> ${}</p>"
            "<p><strong>Current:</strong> {} &middot; <strong>Prior bid:</strong> {}</p>",
            takeover.controller_display_name,
            takeover.represented_entity.name,
            f"{takeover.amount_cents / 100:.2f}",
            "Yes" if current else "No",
            prior,
        )

    @admin.display(description="Bid and payment")
    def payment_context(self, obj):
        bid = obj.takeover.bid
        bid_url = reverse("admin:bidding_bid_change", args=[bid.pk])
        payment_intent = bid.stripe_payment_intent_id or "No Stripe PaymentIntent (local free-play)"
        checkout_session = bid.stripe_checkout_session_id or "—"
        try:
            capture = bid.payment_capture
        except Bid.payment_capture.RelatedObjectDoesNotExist:
            capture_context = "No successful Stripe capture recorded."
        else:
            capture_url = reverse("admin:payments_paymentcapture_change", args=[capture.pk])
            if capture.fee_status == "available":
                capture_summary = format_html(
                    "${} gross &middot; ${} Stripe fee &middot; ${} net",
                    f"{capture.gross_amount_cents / 100:.2f}",
                    f"{capture.stripe_fee_cents / 100:.2f}",
                    f"{capture.net_amount_cents / 100:.2f}",
                )
            else:
                capture_summary = "Stripe fee data pending reconciliation"
            capture_context = format_html('<a href="{}">{}</a>', capture_url, capture_summary)
        action = obj.payment_actions.order_by("-created_at", "-id").first()
        if action:
            action_url = reverse("admin:moderation_moderationpaymentaction_change", args=[action.pk])
            remediation = format_html(
                '<a href="{}">{} — {}</a>',
                action_url,
                action.get_operation_display(),
                action.get_status_display(),
            )
        else:
            remediation = "No payment remediation required."
        return format_html(
            '<p><strong>Bid:</strong> <a href="{}">{}</a> (${}; {})</p>'
            '<p><strong>PaymentIntent:</strong> {}</p>'
            '<p><strong>Checkout session:</strong> {}</p>'
            '<p><strong>Captured payment:</strong> {}</p>'
            '<p><strong>Remediation:</strong> {}</p>',
            bid_url,
            bid.public_id,
            f"{bid.amount_cents / 100:.2f}",
            bid.get_status_display(),
            payment_intent,
            checkout_session,
            capture_context,
            remediation,
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def response_change(self, request, obj):
        action = request.POST.get("report_case_action")
        if action not in {"approve", "remove", "retry"}:
            return super().response_change(request, obj)
        target_url = reverse("admin:moderation_messagereportcase_change", args=[obj.pk])
        try:
            if action == "approve":
                approve_case(case_id=obj.pk, actor=request.user, reason=request.POST.get("resolution_reason", ""))
                self.message_user(request, "Message reports dismissed; the message remains visible.", messages.SUCCESS)
            elif action == "remove":
                result = remove_case(case_id=obj.pk, actor=request.user, reason=request.POST.get("resolution_reason", ""))
                self.message_user(
                    request,
                    "Message removed and payment remediation queued." if result.changed else "This case was already resolved.",
                    messages.SUCCESS,
                )
            else:
                payment_actions = obj.payment_actions.filter(
                    status__in=[
                        ModerationPaymentAction.Status.PENDING,
                        ModerationPaymentAction.Status.FAILED,
                    ]
                )
                for payment_action in payment_actions:
                    process_payment_action(payment_action.id)
                    audit_action(actor=request.user, action="retry_payment_remediation", target=payment_action)
                self.message_user(request, "Payment remediation retry requested.", messages.SUCCESS)
        except ValueError as error:
            self.message_user(request, str(error), messages.ERROR)
        return redirect(target_url)


@admin.register(MessageReport)
class MessageReportAdmin(ModelAdmin):
    list_display = ("case", "reporter", "category", "created_at")
    list_filter = ("category", "created_at")
    search_fields = ("case__public_id", "reporter__display_name")
    readonly_fields = ("public_id", "case", "reporter", "category", "reporter_ip_hash", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ModerationPaymentAction)
class ModerationPaymentActionAdmin(ModelAdmin):
    list_display = ("operation", "status", "case", "bid", "amount_cents", "attempts", "completed_at")
    list_filter = ("operation", "status")
    search_fields = ("public_id", "case__public_id", "bid__public_id")
    readonly_fields = (
        "public_id", "case", "bid", "operation", "status", "amount_cents", "provider_reference",
        "attempts", "last_error_code", "created_at", "updated_at", "completed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
