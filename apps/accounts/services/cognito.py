"""Cognito passwordless email OTP and Hosted UI helpers.

Tokens only pass through this module into the server-side Django session. They
must never be added to logs, responses, analytics, or templates.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.db import IntegrityError, transaction
from apps.accounts.models import UserProfile


logger = logging.getLogger(__name__)


class CognitoError(Exception):
    pass


class CognitoConfigurationError(CognitoError):
    pass


@dataclass(frozen=True)
class CognitoTokens:
    access_token: str
    id_token: str
    refresh_token: str
    expires_in: int


def _configured() -> bool:
    return bool(
        settings.TAKEBOARD_COGNITO_AUTH_ENABLED
        and settings.COGNITO_REGION
        and settings.COGNITO_USER_POOL_ID
        and settings.COGNITO_CLIENT_ID
    )


def _require_configuration() -> None:
    if not _configured():
        raise CognitoConfigurationError("Cognito email authentication is not configured.")


def client():
    _require_configuration()
    return boto3.client("cognito-idp", region_name=settings.COGNITO_REGION)


def secret_hash(username: str) -> str:
    if not settings.COGNITO_CLIENT_SECRET:
        return ""
    digest = hmac.new(
        settings.COGNITO_CLIENT_SECRET.encode(),
        f"{username}{settings.COGNITO_CLIENT_ID}".encode(),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode()


def _auth_parameters(username: str, **extra: str) -> dict[str, str]:
    parameters = {"USERNAME": username, **extra}
    if hash_value := secret_hash(username):
        parameters["SECRET_HASH"] = hash_value
    return parameters


def _challenge_responses(username: str, **extra: str) -> dict[str, str]:
    responses = {"USERNAME": username, **extra}
    if hash_value := secret_hash(username):
        responses["SECRET_HASH"] = hash_value
    return responses


def _email_filter(email: str) -> str:
    escaped_email = email.replace("\\", "\\\\").replace('"', '\\"')
    return f'email = "{escaped_email}"'


def find_user_by_email(email: str) -> dict[str, Any] | None:
    response = client().list_users(
        UserPoolId=settings.COGNITO_USER_POOL_ID,
        Filter=_email_filter(email),
        Limit=2,
    )
    users = response.get("Users", [])
    if len(users) > 1:
        raise CognitoError("Cognito returned multiple users for one email.")
    return users[0] if users else None


def _start_email_otp(username: str) -> str:
    response = client().initiate_auth(
        ClientId=settings.COGNITO_CLIENT_ID,
        AuthFlow="USER_AUTH",
        AuthParameters=_auth_parameters(username, PREFERRED_CHALLENGE="EMAIL_OTP"),
    )
    if response.get("ChallengeName") == "SELECT_CHALLENGE":
        response = client().respond_to_auth_challenge(
            ClientId=settings.COGNITO_CLIENT_ID,
            ChallengeName="SELECT_CHALLENGE",
            ChallengeResponses=_challenge_responses(username, ANSWER="EMAIL_OTP"),
            Session=response.get("Session", ""),
        )
    if response.get("ChallengeName") != "EMAIL_OTP" or not response.get("Session"):
        raise CognitoError("Cognito did not start an email code challenge.")
    return response["Session"]


def _sign_in_after_signup_confirmation(
    username: str,
    confirmation_session: str,
) -> CognitoTokens:
    """Exchange the signup confirmation session for tokens without another code."""
    if not confirmation_session:
        raise CognitoError("Cognito did not return an automatic sign-in session.")

    response = client().initiate_auth(
        ClientId=settings.COGNITO_CLIENT_ID,
        AuthFlow="USER_AUTH",
        AuthParameters=_auth_parameters(username),
        Session=confirmation_session,
    )
    authentication_result = response.get("AuthenticationResult")
    if not authentication_result:
        raise CognitoError("Cognito did not complete automatic sign-in.")
    return _tokens_from_authentication_result(authentication_result)


def start_email_auth(email: str) -> dict[str, str]:
    """Start sign-in for an existing user or confirmation for a new user."""
    try:
        existing_user = find_user_by_email(email)
        if existing_user:
            username = existing_user["Username"]
            if existing_user.get("UserStatus") != "CONFIRMED":
                client().resend_confirmation_code(
                    ClientId=settings.COGNITO_CLIENT_ID,
                    Username=username,
                    **({"SecretHash": secret_hash(username)} if secret_hash(username) else {}),
                )
                return {"flow": "signup", "username": username, "email": email}
            return {
                "flow": "signin",
                "username": username,
                "email": email,
                "challenge_session": _start_email_otp(username),
            }

        # With an email-only pool, Cognito requires the email as the username.
        username = email
        request: dict[str, Any] = {
            "ClientId": settings.COGNITO_CLIENT_ID,
            "Username": username,
            "UserAttributes": [{"Name": "email", "Value": email}],
        }
        if hash_value := secret_hash(username):
            request["SecretHash"] = hash_value
        response = client().sign_up(**request)
        if response.get("UserConfirmed"):
            return {
                "flow": "signin",
                "username": username,
                "email": email,
                "challenge_session": _start_email_otp(username),
            }
        return {"flow": "signup", "username": username, "email": email}
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code", "Unknown")
        logger.warning("cognito_email_auth_start_failed code=%s", error_code)
        raise CognitoError("Cognito could not start email authentication.") from error


def resend_email_code(pending: dict[str, str]) -> dict[str, str]:
    try:
        if pending["flow"] == "signup":
            username = pending["username"]
            request = {"ClientId": settings.COGNITO_CLIENT_ID, "Username": username}
            if hash_value := secret_hash(username):
                request["SecretHash"] = hash_value
            client().resend_confirmation_code(**request)
            return pending

        pending["challenge_session"] = _start_email_otp(pending["username"])
        return pending
    except (ClientError, KeyError) as error:
        raise CognitoError("Cognito could not resend the email code.") from error


def _tokens_from_authentication_result(result: dict[str, Any]) -> CognitoTokens:
    try:
        return CognitoTokens(
            access_token=result["AccessToken"],
            id_token=result["IdToken"],
            refresh_token=result.get("RefreshToken", ""),
            expires_in=int(result["ExpiresIn"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CognitoError("Cognito did not return a valid authenticated session.") from error


def verify_email_code(pending: dict[str, str], code: str) -> tuple[dict[str, str] | None, CognitoTokens | None]:
    """Return a refreshed pending flow or authenticated tokens after a code entry."""
    try:
        if pending["flow"] == "signup":
            username = pending["username"]
            request = {
                "ClientId": settings.COGNITO_CLIENT_ID,
                "Username": username,
                "ConfirmationCode": code,
            }
            if hash_value := secret_hash(username):
                request["SecretHash"] = hash_value
            confirmation = client().confirm_sign_up(**request)
            return None, _sign_in_after_signup_confirmation(
                username,
                str(confirmation.get("Session") or ""),
            )

        response = client().respond_to_auth_challenge(
            ClientId=settings.COGNITO_CLIENT_ID,
            ChallengeName="EMAIL_OTP",
            ChallengeResponses=_challenge_responses(pending["username"], EMAIL_OTP_CODE=code),
            Session=pending["challenge_session"],
        )
        return None, _tokens_from_authentication_result(response["AuthenticationResult"])
    except (ClientError, KeyError) as error:
        raise CognitoError("That code could not be verified.") from error


def _attributes_to_dict(attributes: list[dict[str, str]]) -> dict[str, str]:
    return {attribute["Name"]: attribute["Value"] for attribute in attributes}


@transaction.atomic
def hydrate_profile(tokens: CognitoTokens) -> UserProfile:
    """Validate the access token with Cognito and map its subject to local state."""
    try:
        response = client().get_user(AccessToken=tokens.access_token)
        attributes = _attributes_to_dict(response.get("UserAttributes", []))
        cognito_sub = attributes["sub"]
        email = attributes["email"].strip().lower()
    except (ClientError, KeyError) as error:
        raise CognitoError("Cognito could not validate the signed-in user.") from error

    profile = UserProfile.objects.filter(cognito_sub=cognito_sub).first()
    if profile:
        if profile.email != email:
            profile.email = email
            try:
                profile.save(update_fields=["email", "updated_at"])
            except IntegrityError as error:
                raise CognitoError("This email is already connected to another account.") from error
        return profile

    try:
        return UserProfile.objects.create(cognito_sub=cognito_sub, email=email)
    except IntegrityError as error:
        raise CognitoError("This email is already connected to another account.") from error


def hosted_login_url(*, screen: str, state: str) -> str:
    if not settings.COGNITO_DOMAIN or not settings.COGNITO_REDIRECT_URI:
        raise CognitoConfigurationError("Cognito Hosted UI is not configured.")
    domain = settings.COGNITO_DOMAIN
    if not domain.startswith("https://"):
        domain = f"https://{domain}"
    query = urlencode({
        'client_id': settings.COGNITO_CLIENT_ID,
        'response_type': 'code',
        'scope': 'openid email',
        'redirect_uri': settings.COGNITO_REDIRECT_URI,
        'state': state,
    })
    return f"{domain}/{screen}?{query}"


def new_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def exchange_authorization_code(code: str) -> CognitoTokens:
    if not settings.COGNITO_DOMAIN or not settings.COGNITO_REDIRECT_URI:
        raise CognitoConfigurationError("Cognito Hosted UI is not configured.")
    domain = settings.COGNITO_DOMAIN
    if not domain.startswith("https://"):
        domain = f"https://{domain}"
    payload = urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": settings.COGNITO_CLIENT_ID,
            "code": code,
            "redirect_uri": settings.COGNITO_REDIRECT_URI,
        }
    ).encode()
    request = Request(f"{domain}/oauth2/token", data=payload, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    if settings.COGNITO_CLIENT_SECRET:
        credential = base64.b64encode(
            f"{settings.COGNITO_CLIENT_ID}:{settings.COGNITO_CLIENT_SECRET}".encode()
        ).decode()
        request.add_header("Authorization", f"Basic {credential}")
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read())
        return CognitoTokens(
            access_token=payload["access_token"],
            id_token=payload["id_token"],
            refresh_token=payload.get("refresh_token", ""),
            expires_in=int(payload["expires_in"]),
        )
    except (KeyError, OSError, ValueError) as error:
        raise CognitoError("Cognito could not complete sign-in.") from error
