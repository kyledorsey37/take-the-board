# Frontend Overview

Take the Board uses Django templates, HTMX, and minimal vanilla JavaScript. Do not introduce React or a client-side application shell for the MVP unless explicitly requested.

## Template Structure

- `templates/base.html`: global layout, metadata, navigation, legal disclaimer, static includes.
- `templates/home.html`: public entry point with a takeover-focused featured board and board discovery links.
- `templates/boards/`: school board pages.
- `templates/rivalries/`: rivalry discovery and detail pages.
- `templates/accounts/`: future account/profile templates.
- `templates/components/`: future HTMX fragments and reusable template partials.

## Static Assets

- `static/css/app.css`: starter CSS.
- `static/js/app.js`: minimal JavaScript namespace and fail-silent analytics helper.

The visual system should be independent from official school brands. Use plain school names and generic accent colors. Do not use official logos, mascot art, seals, athletics typography, or university lockups.

## Pre-Launch Navigation

The public header links to Boards, Rivalries, and Leaderboard. Django Admin remains available only at its direct operational URL and must not be linked in fan-facing navigation.

The current board and rivalry content is public, while the local environment can also run the authenticated Stripe sandbox takeover flow.

## Landing Page Board Selection

The home page leads with one live board card and a direct route into that board's
existing takeover flow. A signed-out visitor sees the active board with the highest
current takeover amount. A
signed-in visitor sees their most-visited active board instead. Visits are stored as
a private per-profile counter with a most-visits, then most-recent tie-break; no
unsigned visitor history or board-message content is collected for this feature.

The landing hero uses a stable per-session A/B assignment (`a` or `b`) so a visitor
sees the same copy while their session is active. A `hero_viewed` event records the
low-cardinality `hero_variant` assignment, and hero navigation events carry that same
parameter. The featured “Take over this board” link emits `takeover_cta_clicked`
with `surface`, `school_slug`, `cta`, and `hero_variant` parameters for GA4
conversion analysis.

## Local Free-Play Takeovers

Local development enables a CSRF-protected board-takeover modal. It uses a school dropdown, display name, amount, and board message to persist a `Bid`, `BoardTakeover`, current board state, and activity record in PostgreSQL. The school page distinguishes a message that is live under its display guarantee from a pending higher challenger, and shows the next minimum based on both amounts.

This is intentionally guarded by `TAKEBOARD_DEMO_BIDDING_ENABLED`, which defaults to `true` only in local settings. It uses a session-backed local player identity. A local winner records `demo_won`; a challenger records `authorized` until the local finalizer simulates capture. It creates no payment records, never calls Bedrock, and must remain disabled in staging and production.

The authenticated flow replaces the local player identity with Cognito, accepts
whole-dollar bid amounts, validates a board message before payment, rechecks the
price, and creates Stripe Embedded Checkout with manual capture. After Stripe
reports completion, the checkout instance is destroyed, the browser polls the
bidder-owned status endpoint while the webhook worker finalizes the bid, and the
user returns to the board with a live, pending, or still-processing state.

## HTMX Contract

HTMX is available from the base template. Future dynamic fragments should keep state server-owned and return escaped template output.

Expected dynamic fragments:

- current board
- top boards
- recent activity
- leaderboard
- bid result/status

The payment status endpoint must disclose a bid only to its authenticated bidder. It
returns lifecycle state and the owning board URL, not payment identifiers or message
content.

The leaderboard shows fanbase backing by represented school, conference standings,
top spender accounts, most-attacked boards, and the largest successful takeovers.
All-time standings are available immediately; a `SeasonWeek` configured in the admin
also enables a This week view. The page uses successful published takeovers only, so
uncaptured authorizations and rejected bids do not inflate public totals.

Rivalry pages are a focused scoreboard view over two existing boards. The directory
shows active matchups, while each matchup page shows the leading side, takeover wins,
backing, rival-board attacks, current board messages, recent moves, and the biggest
move. “Back” actions link to the opponent's school board with the selected side
preselected in the existing takeover modal; they do not introduce a separate bid
flow.

## UGC Rendering

Escape user-generated board messages and display names everywhere, including page content, metadata, activity feeds, admin previews, and sharing text. Keep board messages length-limited and avoid exposing moderation internals to users.

## Analytics

Analytics loads only in production when `GOOGLE_ANALYTICS_MEASUREMENT_ID` contains a valid GA4 measurement ID (`G-...`). The standard Google tag sits in the shared document head, so GA4 receives page views for all server-rendered public pages. It is deliberately absent in local and staging settings.

The `window.takeTheBoard.trackEvent()` helper fails silently when analytics is unavailable. The current events are `hero_viewed`, `navigation_click`, `board_opened`, `takeover_cta_clicked`, and `rivalry_opened`; each is limited to the documented parameters below.

Do not send board messages, moderation text, payment identifiers, emails, or full display names to analytics. Prefer low-cardinality parameters such as `school_slug`, `surface`, `status`, `result`, `amount_bucket`, `auth_state`, `hero_variant`, and `cta`.

Before enabling production collection, create the GA4 web data stream for the production domain, add its measurement ID to the production environment, and ensure the public privacy notice and consent approach meet the jurisdictions in which the product is offered. GA4's optional Enhanced Measurement can supply scroll and outbound-link measurements without adding new application event payloads.
