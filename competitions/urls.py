from django.urls import path

from . import views


app_name = "competitions"

urlpatterns = [
    path("", views.competition_list, name="list"),
    path("<int:pk>/register/", views.competition_register, name="register"),
]
