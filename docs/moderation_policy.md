# Moderation Policy

Moderation is not implemented in this skeleton. This document defines the intended posture for public user-generated board messages.

## Philosophy

Take the Board is a trash-talk product. It should allow rivalry insults, team mockery, conference mockery, and ordinary profanity while blocking genuinely harmful content.

Generally allowed:

- team insults
- fanbase insults
- rivalry trash talk
- ordinary profanity
- sports arguments

Blocked:

- slurs and hate speech
- credible threats
- doxxing or personal information
- phone numbers, addresses, and email addresses
- targeted sexual harassment
- severe harassment of private individuals
- impersonation of official entities, admins, schools, coaches, athletes, or famous people
- illegal content
- spam and URLs

## Validation Order

Deterministic checks run before any Bedrock/Nova call. Reject empty messages, messages longer than the configured limit, control characters, excessive Unicode abuse, URLs, email addresses, phone numbers, and obvious personal information.

Only after deterministic checks pass should the future Nova classifier run.

## User-Facing Rejection

Do not expose classifier category internals. Use a general rejection such as:

```text
That message doesn't meet the trash-talk guidelines.
Rivalry insults and profanity are fine, but slurs, threats, personal attacks, and personal information aren't allowed.
```

## Records And Retention

Successful moderation creates a short-lived `MessageValidation` record that belongs to the same user, board, represented school, and exact message submitted to checkout. Retention for raw text, model outputs, admin review notes, and blocked attempts must be defined before public launch.

## Admin Operations

Django Admin should support reviewing validation records, removing current messages, disabling bidding on a board, banning users, and preserving an audit trail of who acted and when.
