from django.urls import path

from . import views


app_name = "content"

urlpatterns = [
    path("about/", views.about, name="about"),
    path("pages/<slug:slug>/", views.page_detail, name="page_detail"),
    path("awards/", views.awards, name="awards"),
    path("showcase/", views.showcase, name="showcase"),
]
