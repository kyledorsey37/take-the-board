# Authentication

Take the Board uses Amazon Cognito User Pools as the identity provider and Django sessions as the browser-facing application session.

## Primary Flow: Email Code

The normal sign-in experience stays inside Django templates. The browser submits CSRF-protected form posts to Django; it never receives Cognito tokens.

1. A fan enters an email address in the sign-in modal.
2. Django normalizes the email and finds the Cognito username with `ListUsers`.
3. Existing confirmed users start Cognito `USER_AUTH` with `PREFERRED_CHALLENGE=EMAIL_OTP`.
4. New users use their email as Cognito's email-only username, then confirm the email with Cognito's sign-up code.
5. Cognito returns an automatic sign-in session from `ConfirmSignUp`; Django passes it to `USER_AUTH` so the same code signs the fan in without a second email.
6. Django validates the resulting Cognito access token with `GetUser`, maps the Cognito `sub` to `UserProfile`, rotates the Django session ID, and stores tokens only in the server-side Django session.

The browser receives only success/error state. Do not log email addresses, Cognito sessions, OTPs, tokens, or raw Cognito responses.

## Hosted UI Fallback

`/login/` and `/signup/` retain Cognito Hosted UI fallback routes. Django generates and validates an OAuth `state`, exchanges the authorization code server-side, and hydrates the same Django session as the email-code path.

## Cognito Setup

Create an email-only pool: enable **Email** as the sole sign-in identifier, enable self-registration, and leave additional sign-up attributes optional. Do not require Cognito `preferred_username`. After a verified first sign-in, Take the Board collects one stable public board name in `UserProfile.display_name`; authenticated bids always use that stored name. Cognito's immutable opaque `sub` is the account key.

Configure the user pool and app client to allow passwordless email OTP (`USER_AUTH` and `EMAIL_OTP`). The Django execution role needs `cognito-idp:ListUsers` for the email lookup. The user pool must permit passwordless API `SignUp` with email as an attribute. The app client needs the callback URI exactly matching `COGNITO_REDIRECT_URI` for the Hosted UI fallback.

Required configuration when auth is enabled:

- `COGNITO_REGION`
- `COGNITO_USER_POOL_ID`
- `COGNITO_CLIENT_ID`
- `COGNITO_CLIENT_SECRET` only when the app client has a secret
- `COGNITO_DOMAIN` and `COGNITO_REDIRECT_URI` for Hosted UI fallback
- `REDIS_URL` in production for shared email-code rate limits

Local Compose can forward short-lived `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN` from the developer environment. Production must use an ECS task role, never static AWS credentials.

## Bidding Gate

Set both `TAKEBOARD_COGNITO_AUTH_ENABLED=true` and `TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING=true` to make the board CTA open sign-in for guests and attach bids to the authenticated `UserProfile`. Local free-play stays available until those flags are enabled.
