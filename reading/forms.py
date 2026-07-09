from django import forms

from reading.models import IssueProgress, VolumeProgress


class IssueProgressForm(forms.Form):
    status = forms.ChoiceField(
        choices=IssueProgress.STATUS_CHOICES,
        widget=forms.Select(
            attrs={
                "class": "form-select form-select-sm",
            }
        ),
    )


class VolumeProgressForm(forms.Form):
    status = forms.ChoiceField(
        choices=VolumeProgress.STATUS_CHOICES,
        widget=forms.Select(
            attrs={
                "class": "form-select form-select-sm",
            }
        ),
    )