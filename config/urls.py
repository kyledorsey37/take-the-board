from django.contrib import admin
from django.urls import include, path
from apps.core.admin_mfa import mfa_gate


urlpatterns = [
    path("admin/mfa/", mfa_gate, name="admin_mfa"),
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.schools.urls")),
    path("", include("apps.boards.urls")),
    path("", include("apps.bidding.urls")),
    path("", include("apps.payments.urls")),
    path("", include("apps.rivalries.urls")),
    path("", include("apps.leaderboard.urls")),
]

handler400 = "apps.core.error_views.bad_request"
handler403 = "apps.core.error_views.permission_denied"
handler404 = "apps.core.error_views.page_not_found"
handler500 = "apps.core.error_views.server_error"
