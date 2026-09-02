from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .middleware.admin_security import ADMIN_MFA_SESSION_KEY


def _staff(request):
    return request.user.is_authenticated and request.user.is_staff


@user_passes_test(_staff)
@require_http_methods(["GET", "POST"])
def mfa_gate(request):
    try:
        from django_otp.plugins.otp_totp.models import TOTPDevice
    except ImportError:
        return render(request, "admin/mfa_gate.html", {"error": "Staff MFA is not installed."}, status=503)

    device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
    if not device:
        device = TOTPDevice.objects.filter(user=request.user, confirmed=False).first()
        if not device:
            device = TOTPDevice.objects.create(user=request.user, name="admin", confirmed=False)
        if request.method == "POST":
            if device.verify_token(request.POST.get("token", "")):
                device.confirmed = True
                device.save(update_fields=["confirmed"])
                request.session[ADMIN_MFA_SESSION_KEY] = True
                return redirect("admin:index")
            return render(request, "admin/mfa_gate.html", {"device": device, "error": "Enter the current code from your authenticator."}, status=400)
        return render(request, "admin/mfa_gate.html", {"device": device})
    if request.method == "POST" and device.verify_token(request.POST.get("token", "")):
        request.session[ADMIN_MFA_SESSION_KEY] = True
        return redirect("admin:index")
    return render(request, "admin/mfa_gate.html", {"error": "That code was not accepted." if request.method == "POST" else ""}, status=400 if request.method == "POST" else 200)
