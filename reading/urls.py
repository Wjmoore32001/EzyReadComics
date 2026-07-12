from django.urls import path

from reading import views


app_name = "reading"

urlpatterns = [
    path("", views.my_comics, name="my_comics"),
    path("runs/<int:run_id>/follow/", views.follow_run, name="follow_run"),
    path("runs/<int:run_id>/follow-options/", views.run_follow_options, name="run_follow_options"),
    path("runs/<int:run_id>/status/", views.set_run_status, name="set_run_status"),
    path("runs/<int:run_id>/unfollow/", views.unfollow_run, name="unfollow_run"),
    path("issues/<int:issue_id>/status/", views.set_issue_status, name="set_issue_status"),
    path("issues/<int:issue_id>/remove/", views.remove_issue_status, name="remove_issue_status"),
    path("volumes/<int:volume_id>/status/", views.set_volume_status, name="set_volume_status"),
    path("volumes/<int:volume_id>/remove/", views.remove_volume_status, name="remove_volume_status"),
]