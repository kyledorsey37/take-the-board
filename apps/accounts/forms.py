from django import forms


class EmailStartForm(forms.Form):
    email = forms.EmailField()

    def clean_email(self) -> str:
        return self.cleaned_data["email"].strip().lower()


class EmailVerifyForm(forms.Form):
    code = forms.RegexField(r"^\d{6,20}$", error_messages={"invalid": "Enter the code."})


class DisplayNameForm(forms.Form):
    display_name = forms.CharField(
        max_length=40,
        error_messages={"required": "Choose a board name."},
        widget=forms.TextInput(
            attrs={
                "autocomplete": "nickname",
                "placeholder": "Your board name",
            }
        ),
    )

    def clean_display_name(self) -> str:
        display_name = self.cleaned_data["display_name"].strip()
        if not display_name:
            raise forms.ValidationError("Choose a board name.")
        return display_name
