from django.urls import path

from . import views


app_name = "member_notices"

urlpatterns = [
    path("", views.internal_list, name="internal_list"),
    path("<int:pk>/", views.internal_detail, name="internal_detail"),
]
