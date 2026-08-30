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
- `core`: shared config, activity feed records, health checks, middleware, and management commands.

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

The current public routes and wording remain College Football-specific
(`/schools/<slug>/`, “school,” and “conference”). They resolve through
`TAKEBOARD_DEFAULT_COMPETITION_SLUG=college-football`, so adding a future
competition does not leak its entities into the MVP's board picker, board directory,
leaderboard, reset operation, or moderation name reservation.

## Service Layer

Complex business logic should live in service modules rather than views, models, or signals. Payment authorization, capture, cancellation, checkout creation, bid finalization, moderation validation, board publication, and weekly resets have explicit service boundaries.

## Local Free-Play Loop

`python manage.py seed_demo_data` creates the College Football competition if it is
missing, then fills missing entities, boards, rivalries, and a default game
configuration without overwriting existing records. The public Boards page and
school pages query that competition directly; Django Admin remains the operational
source of truth after seeding.

When `TAKEBOARD_DEMO_BIDDING_ENABLED` is on in local settings, the bid service implements the protected-board state machine without calling Stripe. A published local bid receives a 30-second `guaranteed_until` window. During that period, only one higher `authorized` bid may be pending; a still-higher bid transactionally replaces it and records the prior authorization as canceled. The minimum uses the maximum of the current captured amount and pending amount.

When `TAKEBOARD_STRIPE_ENABLED` is on, authenticated bids create Stripe Embedded Checkout Sessions with manual capture. Stripe webhooks are signature-verified and stored in `StripeEvent`; the local `run_bid_worker` processes authorization and payment events, cancels superseded authorizations, and captures a valid pending bid when its guarantee is due. The worker still polls Postgres locally; SQS FIFO delivery is a production follow-up.

The local `run_bid_worker` command polls Stripe events and due boards. On a successful capture it publishes the pending bid, writes takeover history, and starts a new guarantee. Its callback boundary also models a failed capture: the pending bid becomes `payment_failed`, is cleared, and the current controller remains live. The Compose `demo-finalizer` service runs this command in either local free-play or Stripe sandbox mode, based on the feature flags.

This remains a local integration slice: moderation approval, ledger entries, SQS FIFO delivery, refunds, and disputes are not yet implemented.

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

## Future Workers

SQS FIFO should be used only for bid finalization ordering. Messages should be grouped by board ID so bids for the same board finalize sequentially while unrelated boards can process independently.

The production worker command will be:

```bash
python manage.py run_bid_worker
```

Production finalization must retain the same board-row lock and one-pending-challenger invariant, but use SQS FIFO ordering and Stripe manual capture rather than the local polling simulation.

## Weekly Reset

The weekly reset is implemented by the idempotent `reset_boards` service and
management command:

```bash
python manage.py reset_boards
```

The command should be invoked by EventBridge Scheduler at Sunday 11:59 PM in
`America/New_York`. It marks the completed `(year, week_number)` period, rebuilds
its cached entity stats, creates the next period, cancels any pending authorized
challenger before clearing live board state, and preserves all bids, takeovers,
and ledger entries. Repeating the command for the same period is a no-op.
