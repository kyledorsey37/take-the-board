# Frontend Overview

Take the Board uses Django templates, HTMX, and minimal vanilla JavaScript. Do not introduce React or a client-side application shell for the MVP unless explicitly requested.

## Template Structure

- `templates/base.html`: global layout, metadata, navigation, legal/support links, affiliation disclaimer, and static includes.
- `templates/legal/` and `templates/contact.html`: public policy and support pages. Keep policy copy aligned with live payment, moderation, privacy, and support behavior.
- `templates/home.html`: public entry point with a takeover-focused featured board and board discovery links.
- `templates/how_it_works.html`: public, plain-language explainer for the takeover loop, settlement, moderation boundaries, and weekly reset.
- `templates/boards/`: school board pages.
- `templates/rivalries/`: rivalry discovery and detail pages.
- `templates/accounts/`: account/profile templates. A post-purchase history and
  support view remains a launch requirement; it should be authenticated and
  expose only the signed-in user's own bids, takeovers, payment states, and
  safe support references.
- `templates/components/`: future HTMX fragments and reusable template partials.

## Static Assets

- `static/css/app.css`: starter CSS.
- `static/js/app.js`: minimal JavaScript namespace and fail-silent analytics helper.
- `static/vendor/htmx-1.9.12.min.js`: the exact official HTMX 1.9.12 release,
  served locally with a versioned path and query string. Provenance, checksum,
  and license text are recorded beside the asset. Stripe.js is intentionally
  not vendored and remains conditional on the official Stripe origin; Google
  Analytics remains consent-gated as described below.

The visual system should be independent from official school brands. Use plain school names and generic accent colors. Do not use official logos, mascot art, seals, athletics typography, or university lockups.

The board directory uses each entity's validated accent as a compact card masthead
behind the school name. This creates an immediate board identity without implying
official school branding. Each card is one accessible board link; on mobile its
content area grows with its message while the footer stays directly beneath it.

## Board Sharing and Social Previews

Each school board has one canonical public URL, a general Share button, and a
separate board-level Share on X intent button. Browsers with the Web Share API
open the native share sheet; desktop browsers copy the canonical URL to the
clipboard. Share on X opens a server-built, URL-encoded `https://x.com/intent/tweet`
link in a new tab with concise, low-risk copy and the canonical board URL. It does
not post automatically or require X API credentials. The post-takeover success
state also offers its own X/Twitter share link. Both paths use canonical URLs and
escaped public-content rules.

Board pages emit Open Graph and X/Twitter Card metadata. Their `summary_large_image`
card points to the versioned `social/boards/<slug>/card.png` endpoint, which renders
the school name as the primary identity, the current public message as the emotional
hook, a takeover CTA with the next price, and generic product branding. The board
version is included in the image URL so a newly published or reset board gets a fresh
social-image cache key. Social-card text follows the same public, escaped-content
rules as the board page and must not include official school logos or lockups.

## Pre-Launch Navigation

The public header links to Boards, Rivalries, Leaderboard, and How it works. Django Admin remains available only at its direct operational URL and must not be linked in fan-facing navigation.

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
reports completion, the checkout instance is destroyed, and the browser briefly
polls the bidder-owned status endpoint while the webhook worker finalizes the bid.
An `authorized` response is shown as a queued challenger immediately only when
the bid is behind an active guaranteed takeover; it is never shown as a completed
takeover while that current message's window is active. An open board is captured
and published by the worker so the browser observes `won` instead. Only a
server-observed `won` response receives the success treatment. A short polling
timeout becomes a non-claiming delayed state, and queued, won, and delayed states
link back to the safe board URL with `move=pending`, `move=live`, or
`move=processing` respectively.

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

School board takeover history is grouped by the persisted Sunday-to-Sunday
competition period. The latest period is open on first load; older periods are
visually separated and collapsed, while all published takeover records remain
available in the public history.

The leaderboard shows fanbase backing by represented school, conference standings,
top spender accounts, most-attacked boards, and the largest successful takeovers.
The game runs Sunday-to-Sunday: the This week view starts fresh with each reset,
while All time preserves the full record. A server-rendered reset timestamp powers a
shared passive weekly-status rail directly beneath navigation on public gameplay
surfaces (board directory, school boards, rivalries, and standings). It displays the
server-derived college-football week number and reset countdown. The rail's help
dialog records `round_help_opened`; the server reset command remains authoritative.
The page uses successful published takeovers only, so uncaptured authorizations and
rejected bids do not inflate public totals.

Rivalry pages are a focused scoreboard view over two existing boards. The directory
shows active matchups, while each matchup page shows the leading side, takeover wins,
backing, rival-board attacks, current board messages, recent moves, and the biggest
move. “Back” actions link to the opponent's school board with the selected side
preselected in the existing takeover modal; they do not introduce a separate bid
flow.

## UGC Rendering

Escape user-generated board messages and display names everywhere, including page content, metadata, activity feeds, admin previews, and sharing text. Keep board messages length-limited and avoid exposing moderation internals to users.

## Analytics

Analytics loads only in production when `GOOGLE_ANALYTICS_MEASUREMENT_ID` contains a valid GA4 measurement ID (`G-...`) and the visitor has accepted optional analytics. The standard Google tag sits in the shared document head, so GA4 receives page views for public pages after consent. A first-party `ttb_analytics_consent` cookie stores only the accepted/declined choice; it is not tied to an account or database record. It is deliberately absent in local and staging settings.

On narrow screens, the first-load cookie prompt is a compact bottom bar with
equally prominent Accept and Decline actions. It keeps the initial board CTA
visible while presenting the optional analytics-cookie choice. Local development
can render the prompt without loading GA4 by setting
`TAKEBOARD_ANALYTICS_CONSENT_PREVIEW=true`.

The `window.takeTheBoard.trackEvent()` helper fails silently when analytics is unavailable. Event attributes cover public navigation and discovery, board shares, modal open/close behavior, authentication steps, backing and amount choices, bid validation, paid checkout, takeover outcomes, reporting, FAQs, and leaderboard/rivalry periods. The complete event catalog and GA4 setup checklist live in `docs/analytics_tracking.md`.

Do not send board messages, moderation text, payment identifiers, emails, or full display names to analytics. Prefer low-cardinality parameters such as `school_slug`, `surface`, `status`, `result`, `amount_bucket`, `hero_variant`, and `cta`.

Before enabling production collection, create the GA4 web data stream for the production domain, add its measurement ID to the production environment, and ensure the public privacy notice and consent approach meet the jurisdictions in which the product is offered. GA4's optional Enhanced Measurement can supply scroll and outbound-link measurements without adding new application event payloads.
