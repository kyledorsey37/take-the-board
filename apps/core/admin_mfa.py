from base64 import b64encode
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import qrcode
from qrcode.image.svg import SvgPathImage
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .middleware.admin_security import ADMIN_MFA_SESSION_KEY


def _staff(user):
    return user.is_authenticated and user.is_staff


def _enrollment_context(device):
    config_url = device.config_url
    qr_code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
        image_factory=SvgPathImage,
    )
    qr_code.add_data(config_url)
    qr_code.make(fit=True)
    image = qr_code.make_image()
    output = BytesIO()
    image.save(output)
    manual_key = parse_qs(urlparse(config_url).query).get("secret", [""])[0]
    return {
        "qr_code_data": b64encode(output.getvalue()).decode("ascii"),
        "manual_key": manual_key,
    }


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
        return render(request, "admin/mfa_gate.html", {**_enrollment_context(device), "device": device})
    if request.method == "POST" and device.verify_token(request.POST.get("token", "")):
        request.session[ADMIN_MFA_SESSION_KEY] = True
        return redirect("admin:index")
    return render(request, "admin/mfa_gate.html", {"error": "That code was not accepted." if request.method == "POST" else ""}, status=400 if request.method == "POST" else 200)
