from django.urls import path

from . import views


app_name = "schools"

urlpatterns = [
    path("schools/<slug:slug>/", views.school_detail, name="detail"),
]
