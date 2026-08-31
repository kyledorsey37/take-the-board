from django.urls import path

from . import views


app_name = "accounts"

urlpatterns = [
    path("api/auth/email/start/", views.email_start, name="email_start"),
    path("api/auth/email/verify/", views.email_verify, name="email_verify"),
    path("api/auth/email/resend/", views.email_resend, name="email_resend"),
    path("api/auth/display-name/", views.set_display_name, name="set_display_name"),
    path("login/", views.hosted_login, {"screen": "login"}, name="login"),
    path("signup/", views.hosted_login, {"screen": "signup"}, name="signup"),
    path("auth/callback/", views.oauth_callback, name="oauth_callback"),
    path("logout/", views.logout, name="logout"),
    path("account/", views.account_detail, name="account_detail"),
    path("u/<str:display_name>/", views.profile_detail, name="profile_detail"),
]
