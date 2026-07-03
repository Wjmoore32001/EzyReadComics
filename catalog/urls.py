from django.urls import path

from catalog import views


app_name = "catalog"

urlpatterns = [
    path("", views.home, name="home"),
    path("browse/", views.browse, name="browse"),
    path("runs/<int:pk>/", views.run_details, name="run_details"),
    path("issues/<int:pk>/", views.issue_details, name="issue_details"),
    path("volumes/<int:pk>/", views.volume_details, name="volume_details"),
]