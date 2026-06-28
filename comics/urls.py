from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("issues/", views.issue_list, name="issues"),
    path("volumes/", views.volume_list, name="volumes"),
]