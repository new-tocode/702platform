from django.urls import path

from . import views


app_name = "competitions"

urlpatterns = [
    path("", views.competition_list, name="list"),
    path("<int:pk>/register/", views.competition_register, name="register"),
    path(
        "registrations/<int:pk>/edit/",
        views.competition_registration_edit,
        name="registration_edit",
    ),
    path(
        "registrations/<int:pk>/withdraw/",
        views.competition_registration_withdraw,
        name="registration_withdraw",
    ),
]
