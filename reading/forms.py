from django import forms

from reading.models import FollowedRun, IssueProgress, OneShotProgress, VolumeProgress


class RunProgressForm(forms.Form):
    status = forms.ChoiceField(
        choices=FollowedRun.STATUS_CHOICES,
        widget=forms.Select(
            attrs={
                "class": "form-select form-select-sm",
            }
        ),
    )


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


class OneShotProgressForm(forms.Form):
    status = forms.ChoiceField(
        choices=OneShotProgress.STATUS_CHOICES,
        widget=forms.Select(
            attrs={
                "class": "form-select form-select-sm",
            }
        ),
    )