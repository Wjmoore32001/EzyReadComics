from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("browse/", views.browse, name="browse"),

    # Old routes kept for now so existing links/bookmarks do not break.
    # They now use the new Browse behavior instead of separate pages.
    path("issues/", views.issue_list, name="issues"),
    path("volumes/", views.volume_list, name="volumes"),
]