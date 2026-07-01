from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from accounts.forms import StyledPasswordChangeForm, StyledUsernameChangeForm


@login_required
def account(request):
    username_form = StyledUsernameChangeForm(request.user)
    password_form = StyledPasswordChangeForm(request.user)

    if request.method == "POST":
        account_action = request.POST.get("account_action", "")

        if account_action == "change_username":
            username_form = StyledUsernameChangeForm(request.user, request.POST)

            if username_form.is_valid():
                username_form.save()
                messages.success(request, "Your username has been updated.")
                return redirect("account")

        elif account_action == "change_password":
            password_form = StyledPasswordChangeForm(request.user, request.POST)

            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Your password has been updated.")
                return redirect("account")

        else:
            messages.error(request, "Unknown account action.")

    return render(
        request,
        "registration/account.html",
        {
            "username_form": username_form,
            "password_form": password_form,
        },
    )