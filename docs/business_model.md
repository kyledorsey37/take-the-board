# Business Model

Take the Board sells temporary control of a public, user-generated message on a school board.

## Core Loop

1. A fan sees a rival message.
2. They write an allowed rivalry message.
3. The message passes validation before payment.
4. They authorize a bid through Stripe Checkout.
5. The bid is captured only if it is still winning at finalization.
6. The board changes until another qualifying bid wins, an admin removes it, or the weekly reset occurs.

## Purchase Meaning

A successful bid purchases temporary control of the message displayed by Take the Board. It does not purchase ownership, sponsorship, affiliation, endorsement, or guaranteed display time.

Control can last days, hours, minutes, or seconds. The transaction is not payment for a fixed duration.

## Pricing Rules

- Minimum bid is `max($1, current bid + $1)`.
- Users may overbid.
- Initial maximum bid is configurable and currently defaults to `$500`.
- Weekly reset returns current board amounts to `$0`; first takeover after reset costs `$1`.

## No Stored Value

Do not introduce credits, tokens, stored balances, prepaid wallets, or "Board Bucks" for the MVP. Use direct USD payments to reduce accounting, refund, and user-confusion risk.

## Trademark Posture

The product is independent fan entertainment. School names are used to identify subjects of fan discussion. The app should avoid official logos, mascot artwork, seals, helmet art, copied typefaces, and sponsorship language.
