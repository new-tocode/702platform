from django.urls import path

from . import views


app_name = "content"

urlpatterns = [
    path("about/", views.about, name="about"),
    path("pages/", views.page_index, name="page_index"),
    path("pages/<slug:slug>/", views.page_detail, name="page_detail"),
    path("awards/", views.awards, name="awards"),
    path(
        "awards/certificates.zip",
        views.award_certificates,
        name="award_certificates",
    ),
    path("showcase/", views.showcase, name="showcase"),
]
