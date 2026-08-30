import uuid

from django.db import models


class MessageValidation(models.Model):
    class Decision(models.TextChoices):
        ALLOW = "allow", "Allow"
        BLOCK = "block", "Block"
        REVIEW = "review", "Review"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey("accounts.UserProfile", on_delete=models.CASCADE)
    board = models.ForeignKey("boards.Board", on_delete=models.CASCADE)
    represented_school = models.ForeignKey("schools.School", on_delete=models.PROTECT)
    message = models.CharField(max_length=80)
    message_hash = models.CharField(max_length=64)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    category = models.CharField(max_length=50, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    policy_version = models.CharField(max_length=32, default="")
    classifier_version = models.CharField(max_length=64, default="")
    content_retention_until = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["board", "-created_at"]),
            models.Index(fields=["decision", "-created_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.decision} validation for {self.board}"


class DisplayNameValidation(models.Model):
    class Decision(models.TextChoices):
        ALLOW = "allow", "Allow"
        BLOCK = "block", "Block"
        REVIEW = "review", "Review"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey("accounts.UserProfile", on_delete=models.CASCADE)
    display_name = models.CharField(max_length=40, blank=True)
    candidate_hash = models.CharField(max_length=64)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    category = models.CharField(max_length=50, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    policy_version = models.CharField(max_length=32)
    classifier_version = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    content_retention_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["decision", "-created_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.decision} display-name validation for {self.user_id}"


class ModerationActionAudit(models.Model):
    actor = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="moderation_actions"
    )
    target_type = models.CharField(max_length=40)
    target_id = models.CharField(max_length=64)
    action = models.CharField(max_length=64)
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.action} {self.target_type}:{self.target_id}"


class MessageReportCase(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        APPROVED = "approved", "Approved"
        REMOVED = "removed", "Removed"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    takeover = models.OneToOneField(
        "boards.BoardTakeover",
        on_delete=models.PROTECT,
        related_name="report_case",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField(auto_now_add=True)
    last_reported_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_message_report_cases",
    )
    resolution_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "-last_reported_at"]),
            models.Index(fields=["resolved_by", "-resolved_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.status} reports for takeover {self.takeover_id}"


class MessageReport(models.Model):
    class Category(models.TextChoices):
        HATE_SPEECH = "hate_speech", "Hate speech or slur"
        THREATS = "threats_violence", "Threats or violence"
        PERSONAL_INFO = "personal_information", "Personal information or doxxing"
        HARASSMENT = "harassment_sexual", "Harassment or sexual content"
        SPAM = "spam_advertising", "Spam or advertising"
        IMPERSONATION = "impersonation", "Impersonation"
        OTHER = "other_guidelines", "Other community-guideline violation"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    case = models.ForeignKey(MessageReportCase, on_delete=models.PROTECT, related_name="reports")
    reporter = models.ForeignKey(
        "accounts.UserProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="message_reports",
    )
    category = models.CharField(max_length=40, choices=Category.choices)
    reporter_ip_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("case", "reporter"),
                name="unique_reporter_per_message_case",
            )
        ]
        indexes = [models.Index(fields=["case", "category"])]

    def __str__(self) -> str:
        return f"{self.category} report for case {self.case_id}"


class ModerationPaymentAction(models.Model):
    class Operation(models.TextChoices):
        CANCEL_AUTHORIZATION = "cancel_authorization", "Cancel authorization"
        REFUND = "refund", "Refund"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        NOT_REQUIRED = "not_required", "Not required"
        FAILED = "failed", "Failed"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    case = models.ForeignKey(MessageReportCase, on_delete=models.PROTECT, related_name="payment_actions")
    bid = models.OneToOneField(
        "bidding.Bid", on_delete=models.PROTECT, related_name="moderation_payment_action"
    )
    operation = models.CharField(max_length=32, choices=Operation.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    amount_cents = models.PositiveIntegerField(null=True, blank=True)
    provider_reference = models.CharField(max_length=255, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("case", "bid"), name="unique_payment_action_per_case_bid")
        ]

    def __str__(self) -> str:
        return f"{self.operation} for bid {self.bid_id}: {self.status}"
