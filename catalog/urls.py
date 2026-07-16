from django.urls import path

from catalog import browse_views, current_reading_era_views, views


app_name = "catalog"

urlpatterns = [
    path("", views.home, name="home"),
    path("browse/", browse_views.browse, name="browse"),
    path(
        "current-reading-era/",
        current_reading_era_views.current_reading_era,
        name="current_reading_era",
    ),
    path("browse/options/", browse_views.browse_options, name="browse_options"),
    path("browse/items/", browse_views.browse_items, name="browse_items"),
    path("runs/<int:pk>/", views.run_details, name="run_details"),
    path("issues/<int:pk>/", views.issue_details, name="issue_details"),
    path("volumes/<int:pk>/", views.volume_details, name="volume_details"),
    path("one-shots/<int:pk>/", views.one_shot_details, name="one_shot_details"),
]
