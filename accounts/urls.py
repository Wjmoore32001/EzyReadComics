from django.contrib.auth import views as auth_views
from django.urls import path

from accounts.forms import StyledAuthenticationForm
from accounts.views import account, signup


urlpatterns = [
    path("", account, name="account"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            authentication_form=StyledAuthenticationForm,
        ),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
    path("signup/", signup, name="signup"),
]