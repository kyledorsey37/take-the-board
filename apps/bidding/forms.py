from decimal import Decimal
import re

from django import forms
from apps.schools.models import Competition, Entity

from .services.rules import BoardRules


class TakeBoardForm(forms.Form):
    board_slug = forms.SlugField(widget=forms.HiddenInput())
    display_name = forms.CharField(
        max_length=40,
        error_messages={"required": "Choose a name for the board."},
        widget=forms.TextInput(
            attrs={
                "autocomplete": "nickname",
                "placeholder": "Your display name",
            }
        ),
    )
    represented_entity = forms.ModelChoiceField(
        queryset=Entity.objects.none(),
        empty_label="Choose a school",
        widget=forms.Select(
            attrs={
                "class": "school-picker-native",
                "tabindex": "-1",
                "aria-hidden": "true",
            }
        ),
    )
    amount = forms.DecimalField(
        decimal_places=2,
        max_digits=7,
        error_messages={
            "min_value": "Enter a takeover amount greater than $0.00.",
        },
        widget=forms.TextInput(
            attrs={
                "inputmode": "decimal",
                "autocomplete": "off",
                "data-bid-amount": "",
            }
        ),
    )
    message = forms.CharField(
        error_messages={"required": "Write a message for the board."},
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "What should the board say?",
                "autocomplete": "off",
                "data-bid-message": "",
            }
        ),
    )
    age_acknowledged = forms.BooleanField(
        required=False,
        error_messages={
            "required": "Confirm that you are 18 or older before placing a paid bid.",
        },
        widget=forms.CheckboxInput(attrs={"data-age-acknowledgement": "true"}),
    )

    def __init__(
        self,
        *args,
        rules: BoardRules,
        competition: Competition,
        require_display_name: bool = True,
        require_age_acknowledgement: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.rules = rules
        if not require_display_name:
            self.fields.pop("display_name")
        if not require_age_acknowledgement:
            self.fields.pop("age_acknowledged")
        else:
            self.fields["age_acknowledged"].required = True
        self.fields["represented_entity"].queryset = Entity.objects.filter(
            competition=competition,
            active=True,
        ).order_by("name")
        self.fields["amount"].min_value = Decimal("0.01")
        self.fields["amount"].max_value = Decimal(rules.maximum_bid_cents) / 100
        self.fields["amount"].widget.attrs["min"] = "0.01"
        self.fields["amount"].widget.attrs["max"] = f"{rules.maximum_bid_cents / 100:.2f}"
        self.fields["message"].max_length = rules.message_max_length
        self.fields["message"].widget.attrs["maxlength"] = rules.message_max_length

    def clean_amount(self) -> Decimal:
        raw_amount = str(self.data.get(self.add_prefix("amount"), "")).strip()
        if raw_amount.startswith("-"):
            raise forms.ValidationError("Enter a takeover amount greater than $0.00.")
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", raw_amount):
            raise forms.ValidationError("Enter a valid takeover amount.")

        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Enter a takeover amount greater than $0.00.")
        if amount != amount.to_integral_value():
            raise forms.ValidationError("Use whole dollar amounts.")
        return amount

    def clean_display_name(self) -> str:
        display_name = self.cleaned_data["display_name"].strip()
        if not display_name:
            raise forms.ValidationError("Choose a name for the board.")
        return display_name

    def clean_message(self) -> str:
        message = self.cleaned_data["message"].strip()
        if not message:
            raise forms.ValidationError("Write a message for the board.")
        return message
