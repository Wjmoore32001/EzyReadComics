from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import StyledAuthenticationForm


urlpatterns = [
    path("", views.home, name="home"),
    path("browse/", views.browse, name="browse"),

    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            authentication_form=StyledAuthenticationForm,
        ),
        name="login",
    ),
    path(
        "accounts/logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/", views.account, name="account"),

    # Old routes kept for now so existing links/bookmarks do not break.
    # They now use the new Browse behavior instead of separate pages.
    path("issues/", views.issue_list, name="issues"),
    path("volumes/", views.volume_list, name="volumes"),
]