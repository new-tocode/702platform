from django.urls import path

from . import views


app_name = "reviews"

urlpatterns = [
    path("", views.review_queue, name="queue"),
    path("<int:pk>/complete/", views.complete_assignment, name="complete"),
]
