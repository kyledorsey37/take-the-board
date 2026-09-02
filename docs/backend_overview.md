# Backend Overview

Take the Board is a Django monolith. Django owns page rendering, game state, bidding, moderation records, payment records, leaderboards, history, and admin operations.

## Project Layout

```text
config/
  settings/
    base.py
    local.py
    staging.py
    production.py
apps/
  accounts/
  schools/
  boards/
  bidding/
  payments/
  moderation/
  rivalries/
  leaderboard/
  core/
templates/
static/
docs/
tests/
```

## App Ownership

- `accounts`: local `UserProfile` records linked to Cognito identity later.
- `schools`: competition and entity catalog metadata. The app name remains for URL and MVP compatibility; its models are generic.
- `boards`: one active board per entity, current board state, takeover history, board publishing and reset service boundaries.
- `bidding`: bid records and bid lifecycle service boundaries.
- `payments`: Stripe event storage, ledger entries, and payment service boundaries.
- `moderation`: message validation records and deterministic/Nova moderation service boundaries.
- `rivalries`: explicit rivalry pairs.
- `leaderboard`: public standings, season weeks, and cached school-week statistics.
- `core`: shared config, private board-visit preference counters, activity feed records, health checks, middleware, and management commands.

## Data Store

PostgreSQL is the primary datastore for production and Docker-based local development. SQLite exists only as a convenience fallback for local framework checks before services are running.

Core game state should not move to DynamoDB. The product needs relational constraints, transactions, foreign keys, historical queries, and row locks for bid finalization.

## Competition and Entity Scope

The game engine is structured for more than one sport without exposing a multi-sport
product surface before it is needed:

- `Competition` is the top-level game scope, such as College Football, NFL, or NBA.
- `Entity` is the fanbase that owns a board within that competition. For College
  Football, entities are schools; for the NFL, they would be clubs. Entity slugs
  are unique within a competition, and `group_name` carries competition-specific
  groupings such as a conference or division.
- Every board belongs to one entity. Bids, takeovers, ledger entries, moderation
  records, favorite fanbases, rivalries, and cached statistics refer to entities.
- A bid service only accepts a represented entity from the board's competition.
  Rivalries are likewise limited to two entities from the same competition.
- `CompetitionPeriod` scopes active periods and cached `EntityPeriodStats` to one
  competition. The current weekly schedule remains the College Football MVP's
  policy, not a cross-sport schema assumption.
- The public weekly reset schedule is derived from the active period's `ends_at`.
  If that deadline passes before the reset command completes, public surfaces show
  that the reset is due rather than advancing the displayed week. The command is
  still responsible for clearing live board state and rebuilding period stats.

The current public routes and wording remain College Football-specific
(`/schools/<slug>/`, “school,” and “conference”). They resolve through
`TAKEBOARD_DEFAULT_COMPETITION_SLUG=college-football`, so adding a future
competition does not leak its entities into the MVP's board picker, board directory,
leaderboard, reset operation, or moderation name reservation.

## Service Layer

Complex business logic should live in service modules rather than views, models, or signals. Payment authorization, capture, cancellation, checkout creation, bid finalization, moderation validation, board publication, and weekly resets have explicit service boundaries.

## Automatic social publishing

Automatic posts to the Take the Board X/Twitter account are a separate outbound
side effect of a successful takeover. The trigger must run only after the server
has captured payment and published the `BoardTakeover`; an authorization,
pending challenger, browser redirect, or failed capture must never create a
post. The post should use the canonical public board URL and already-public,
escaped board data, with no email, payment identifier, bid identifier, or
moderation details.

Social publishing must be retryable and idempotent so a worker retry cannot post
the same takeover repeatedly. X API credentials belong in the production secret
store, and rate limits, provider errors, a manual retry/disable control, and
operator visibility into failed posts must be handled without changing board or
payment state. This integration is not wired yet; see
`docs/launch_readiness.md`.

## Local Free-Play Loop

`python manage.py seed_demo_data` creates the College Football competition if it is
missing, then fills missing entities, boards, rivalries, and a default game
configuration without overwriting existing records. The public Boards page and
school pages query that competition directly; Django Admin remains the operational
source of truth after seeding.

When `TAKEBOARD_DEMO_BIDDING_ENABLED` is on in local settings, the bid service implements the protected-board state machine without calling Stripe. A published local bid receives a 30-second `guaranteed_until` window. During that period, only one higher `authorized` bid may be pending; a still-higher bid transactionally replaces it and records the prior authorization as canceled. The minimum uses the maximum of the current captured amount and pending amount.

When `TAKEBOARD_STRIPE_ENABLED` is on, authenticated bids create Stripe Embedded Checkout Sessions with manual capture. Stripe webhooks are signature-verified and stored in `StripeEvent`; authorization processing cancels superseded authorizations and enqueues an opaque bid identifier to the configured SQS FIFO queue when queue mode is selected. The `run_bid_worker` consumer captures a valid pending bid when its guarantee is due. Local settings deliberately use the Postgres polling path.

The `run_bid_worker` command always processes stored Stripe events, then either
long-polls SQS FIFO or polls due boards according to
`TAKEBOARD_BID_FINALIZATION_MODE`. On a successful capture it publishes the
pending bid, writes takeover history, and starts a new guarantee. Its callback
boundary also models a failed capture: the pending bid becomes `payment_failed`,
is cleared, and the current controller remains live. The Compose `demo-finalizer`
service remains local polling for free-play and sandbox development.

The local integration slice includes moderation approval records, ledger entries,
refund handling, and dispute handling. Those paths have service boundaries and
automated tests. The Bedrock/Nova provider remains fail-closed until its AWS
configuration is enabled.

## Public Standings

The public leaderboard currently aggregates `BoardTakeover` records, which represent
successful published takeovers. Pending, canceled, failed, and refunded bids do not
count. A takeover contributes its amount to three independent views:

- the entity selected by the bidder (`represented_entity`), for fanbase backing;
- the bidder's stable board name, for the fan leaderboard;
- the board's entity, for most-attacked-board statistics.

College Football conference standings roll up the represented entity's `group_name`. The page supports
all-time totals and an active `SeasonWeek` period when one has been configured in the
admin. These read-time aggregates are intentionally derived from historical takeover
records until the weekly cached-statistics rebuild is added.

## Rivalry Scoreboards

Rivalries are a scoreboard layer over two existing school boards, not a second
bidding or payment mechanism. A rivalry only counts successful takeovers where
the represented school is one of the two schools in the matchup. The represented
school receives the move and backing credit; the board school determines whether
that move was an attack on the rival's board. Refunded, failed, pending, and
outside-school moves are excluded from rivalry totals.

The public matchup page shows each side's takeover wins, backing, rival-board
attacks, biggest move, current board state, and recent successful moves. Its
action links route to the existing school board page with the represented school
preselected, so all validation, authentication, checkout, and finalization rules
remain centralized in the normal takeover flow.

Each `SeasonWeek` is identified by its year and week number. The year is the ISO
week-year, so Week 1 in a new year is distinct from Week 1 in the prior year even
though yearly rollup statistics are not required.

## Finalization Worker and Queue

SQS FIFO is used only for bid finalization ordering, with messages grouped by
board ID so bids for the same board finalize sequentially while unrelated boards
can process independently. The queue consumer retains the existing board-row
lock and one-pending-challenger invariant; FIFO ordering is defense in depth and
never replaces transactional validation. See the [SQS finalization runbook](sqs_bid_finalization_runbook.md)
for queue/DLQ and IAM requirements.

The production worker command will be:

```bash
python manage.py run_bid_worker
```

Production finalization retains the same board-row lock and one-pending-
challenger invariant, using SQS FIFO ordering and Stripe manual capture rather
than polling. A dev/staging queue should be exercised before the production queue
is enabled so ordering, retries, visibility timeouts, and a dead-letter path are
observable.

## Weekly Reset

The weekly reset is implemented by the idempotent `reset_boards` service and
management command:

```bash
python manage.py reset_boards
```

The command is ready to be invoked by EventBridge Scheduler at Sunday 11:59 PM
in `America/New_York`, but that schedule and its alerting still need to be
configured in AWS. It marks the completed `(year, week_number)` period, rebuilds
its cached entity stats, creates the next period, cancels any pending authorized
challenger before clearing live board state, and preserves all bids, takeovers,
and ledger entries. Repeating the command for the same period is a no-op. The
command was manually exercised against the local Docker database on 2026-08-31;
it reset the current boards while preserving historical takeovers, bids, and
all-time totals, and a second invocation was a no-op.

## Payment and moderation operations

The following operational commands are implemented:

```bash
python manage.py reconcile_payment_captures
python manage.py purge_moderation_content
```

`reconcile_payment_captures` backfills missing Stripe capture snapshots and
attaches delayed fee data when Stripe makes it available. The reconciliation
logic is idempotent, but a production schedule, alert, and owner still need to
be configured. `purge_moderation_content` clears expired blocked/review
moderation text while retaining decision metadata. Its production schedule and
monitoring also need to be configured.
