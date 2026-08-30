"""Audited moderation operations used by Django Admin only."""

from apps.moderation.models import ModerationActionAudit


def audit_action(*, actor, action: str, target, reason: str = "") -> None:
    ModerationActionAudit.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        target_type=target._meta.label_lower,
        target_id=str(target.pk),
        reason=reason[:500],
    )
