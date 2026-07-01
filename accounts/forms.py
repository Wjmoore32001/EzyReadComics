from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm


class StyledAuthenticationForm(AuthenticationForm):
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)

        self.fields["username"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "username",
                "placeholder": "Username",
            }
        )
        self.fields["password"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "current-password",
                "placeholder": "Password",
            }
        )


class StyledUserCreationForm(UserCreationForm):
    email = forms.EmailField(
        required=False,
        label="Email (optional)",
        help_text=(
            "Optional. You can leave this blank. It may be used later for "
            "account recovery, but no verification email is required right now."
        ),
    )

    website = forms.CharField(
        required=False,
        label="Website",
        help_text="Leave this field blank.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.order_fields(["username", "email", "password1", "password2", "website"])

        self.fields["username"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "username",
                "placeholder": "Choose a username",
            }
        )
        self.fields["email"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "email",
                "placeholder": "Email address (optional)",
            }
        )
        self.fields["password1"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "Choose a password",
            }
        )
        self.fields["password2"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "Confirm your password",
            }
        )
        self.fields["website"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "off",
                "tabindex": "-1",
            }
        )

    def clean_website(self):
        website = self.cleaned_data.get("website", "")

        if website:
            raise forms.ValidationError(
                "There was a problem creating this account. Please try again."
            )

        return website

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get("email", "").strip()

        if commit:
            user.save()

        return user


class StyledUsernameChangeForm(forms.Form):
    username = forms.CharField(
        label="New username",
        help_text="Choose a username that is not already being used.",
    )
    current_password = forms.CharField(
        label="Current password",
        widget=forms.PasswordInput,
        help_text="Required before your username can be changed.",
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        username_field = user._meta.get_field(user.USERNAME_FIELD)

        self.fields["username"].max_length = username_field.max_length
        self.fields["username"].validators = username_field.validators
        self.fields["username"].initial = user.get_username()
        self.fields["username"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "username",
                "placeholder": "New username",
                "maxlength": username_field.max_length,
            }
        )

        self.fields["current_password"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "current-password",
                "placeholder": "Current password",
            }
        )

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        User = get_user_model()

        if not username:
            raise forms.ValidationError("Enter a username.")

        if username == self.user.get_username():
            raise forms.ValidationError("That is already your current username.")

        username_taken = (
            User.objects
            .filter(username=username)
            .exclude(pk=self.user.pk)
            .exists()
        )

        if username_taken:
            raise forms.ValidationError("That username is already taken.")

        return username

    def clean_current_password(self):
        current_password = self.cleaned_data.get("current_password", "")

        if not self.user.check_password(current_password):
            raise forms.ValidationError("Your current password was incorrect.")

        return current_password

    def save(self):
        self.user.username = self.cleaned_data["username"]
        self.user.save(update_fields=["username"])

        return self.user


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)

        self.fields["old_password"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "current-password",
                "placeholder": "Current password",
            }
        )
        self.fields["new_password1"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "New password",
            }
        )
        self.fields["new_password2"].widget.attrs.update(
            {
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "Confirm new password",
            }
        )