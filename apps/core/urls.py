from django.urls import path

from . import views


app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("how-it-works/", views.how_it_works, name="how_it_works"),
    path("privacy/", views.privacy, name="privacy"),
    path("terms/", views.terms, name="terms"),
    path("refunds/", views.refunds, name="refunds"),
    path("community-guidelines/", views.community_guidelines, name="community_guidelines"),
    path("contact/", views.contact, name="contact"),
    path("healthz/", views.healthz, name="healthz"),
]
