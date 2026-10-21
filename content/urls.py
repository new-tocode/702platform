from django.urls import path

from . import views


app_name = "content"

urlpatterns = [
    path("about/", views.about, name="about"),
    path("pages/", views.page_index, name="page_index"),
    path("pages/<slug:slug>/", views.page_detail, name="page_detail"),
    path("achievements/", views.achievements, name="achievements"),
    path("awards/", views.awards, name="awards"),
    path("awards/new/", views.award_create, name="award_create"),
    path(
        "awards/certificates.zip",
        views.award_certificates,
        name="award_certificates",
    ),
    path("papers/", views.papers, name="papers"),
    path("papers/new/", views.paper_create, name="paper_create"),
    path("patents/", views.patents, name="patents"),
    path("patents/new/", views.patent_create, name="patent_create"),
    path("showcase/", views.showcase, name="showcase"),
]
