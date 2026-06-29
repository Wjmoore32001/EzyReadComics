from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from comics.forms import StyledUserCreationForm


@login_required
def account(request):
    return render(request, "registration/account.html")


def signup(request):
    if request.user.is_authenticated:
        return redirect("account")

    if request.method == "POST":
        form = StyledUserCreationForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Your account has been created.")
            return redirect("account")
    else:
        form = StyledUserCreationForm()

    return render(request, "registration/signup.html", {"form": form})