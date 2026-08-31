"""Render a board's social card locally without starting the web server."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError

from apps.bidding.services.rules import current_board_rules, minimum_takeover_cents
from apps.boards.models import Board
from apps.boards.services.social_card import render_board_social_card


class Command(BaseCommand):
    help = "Render a board social-card PNG without starting Django's web server."

    def add_arguments(self, parser):
        parser.add_argument("slug", nargs="?", default="alabama")
        parser.add_argument("--output", default=None, help="Output PNG path.")
        parser.add_argument(
            "--sample",
            action="store_true",
            help="Render sample values without connecting to the database.",
        )
        parser.add_argument("--school", default=None, help="Override the school label.")
        parser.add_argument("--message", default=None, help="Override the board message.")
        parser.add_argument("--owner", default=None, help="Override the controller name; empty means open.")
        parser.add_argument("--amount", default=None, help="Override the amount spent, in dollars.")
        parser.add_argument("--takeover-price", default=None, help="Override the CTA price, in dollars.")
        parser.add_argument("--accent", default=None, help="Override the six-digit accent color.")

    def handle(self, *args, **options):
        slug = options["slug"]
        if options["sample"]:
            board = self._sample_board(options)
        else:
            try:
                stored_board = Board.objects.select_related("entity", "current_controller", "pending_bid").get(
                    entity__slug=slug,
                    entity__active=True,
                )
            except Board.DoesNotExist as error:
                raise CommandError(
                    f"No active board found for '{slug}'. Use --sample to render without the database."
                ) from error
            board = self._board_with_overrides(stored_board, options)

        output = Path(options["output"] or f"social-card-{slug}.png")
        if not output.parent.exists():
            raise CommandError(f"Output directory does not exist: {output.parent}")
        output.write_bytes(render_board_social_card(board))
        self.stdout.write(self.style.SUCCESS(f"Wrote {output}"))

    @staticmethod
    def _sample_board(options):
        return SimpleNamespace(
            entity=SimpleNamespace(
                name=options["school"] or "Alabama",
                accent_color=options["accent"] or "#b3262f",
            ),
            current_message=options["message"] or "BAMA SUCKS",
            current_controller=(
                SimpleNamespace(display_name=options["owner"])
                if options["owner"]
                else None
            ),
            current_amount_dollars=(current_amount := Command._amount(options["amount"], default="5.00")),
            next_takeover_dollars=Command._amount(
                options["takeover_price"],
                default=str(current_amount),
            ),
            bidding_enabled=True,
        )

    @staticmethod
    def _board_with_overrides(board, options):
        owner = (
            options["owner"]
            if options["owner"] is not None
            else getattr(board.current_controller, "display_name", "")
        )
        rules = current_board_rules()
        next_takeover = Decimal(minimum_takeover_cents(
            board.current_amount_cents,
            rules,
            board.pending_bid.amount_cents if board.pending_bid_id else 0,
        )) / 100
        return SimpleNamespace(
            entity=SimpleNamespace(
                name=options["school"] or board.entity.name,
                accent_color=options["accent"] or board.entity.accent_color,
            ),
            current_message=options["message"] if options["message"] is not None else board.current_message,
            current_controller=SimpleNamespace(display_name=owner) if owner else None,
            current_amount_dollars=Command._amount(
                options["amount"],
                default=str(board.current_amount_dollars),
            ),
            next_takeover_dollars=Command._amount(
                options["takeover_price"],
                default=str(next_takeover),
            ),
            bidding_enabled=board.bidding_enabled,
        )

    @staticmethod
    def _amount(value, *, default):
        try:
            amount = Decimal(value if value is not None else default)
        except (InvalidOperation, TypeError, ValueError) as error:
            raise CommandError("--amount must be a valid dollar amount.") from error
        if amount < 0:
            raise CommandError("--amount cannot be negative.")
        return amount
