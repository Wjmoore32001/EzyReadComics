"""
URL configuration for config project.

The project is currently being restructured into permanent apps.
During this phase, routes should point only to the new app structure.
"""
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", include("catalog.urls")),
]