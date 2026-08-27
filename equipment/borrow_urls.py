from django.urls import path

from . import views


app_name = "equipment_borrows"

urlpatterns = [
    path("", views.borrow_list, name="list"),
    path("<int:pk>/return/", views.borrow_return, name="return"),
]
