import hashlib

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.core.cache import cache
from django.shortcuts import redirect, render

from accounts.forms import StyledUserCreationForm


def _get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR", "unknown")


def _signup_rate_limit_key(request):
    client_ip = _get_client_ip(request)
    ip_digest = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()

    return f"signup_attempts:{ip_digest}"


def _signup_is_rate_limited(request):
    attempt_limit = getattr(settings, "SIGNUP_ATTEMPT_LIMIT", 10)
    window_seconds = getattr(settings, "SIGNUP_ATTEMPT_WINDOW_SECONDS", 3600)

    if attempt_limit <= 0:
        return False

    cache_key = _signup_rate_limit_key(request)
    current_attempts = cache.get(cache_key, 0)

    if current_attempts >= attempt_limit:
        return True

    cache.set(cache_key, current_attempts + 1, timeout=window_seconds)

    return False


def signup(request):
    if request.user.is_authenticated:
        return redirect("account")

    if request.method == "POST":
        if _signup_is_rate_limited(request):
            form = StyledUserCreationForm()
            form.add_error(
                None,
                "Too many signup attempts from this connection. Please try again later.",
            )
        else:
            form = StyledUserCreationForm(request.POST)

            if form.is_valid():
                user = form.save()
                login(request, user)
                messages.success(request, "Your account has been created.")
                return redirect("account")
    else:
        form = StyledUserCreationForm()

    return render(request, "registration/signup.html", {"form": form})