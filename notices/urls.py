from django.urls import path

from . import views


app_name = "notices"

urlpatterns = [
    path("", views.public_list, name="public_list"),
    path("<int:pk>/", views.public_detail, name="public_detail"),
]
