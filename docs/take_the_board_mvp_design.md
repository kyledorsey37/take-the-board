# Take the Board — MVP Technical Design Document

## 1. Product Summary

Take the Board is a college-football fan rivalry game where each school has one public message controlled by the highest successful bidder.

Example:

**OKLAHOMA**

> TEXAS SUCKS.

Controlled by **SoonerSteve**

Current bid: **$47**

**Take Control — $48**

A user can outbid the current controller, replace the message, and temporarily control the school's board until somebody successfully outbids them.

The primary product loop is:

**see rival message → want to respond → write trash talk → validate message → pay → take board → share → rival retaliates**

The product should feel like a digital version of a rivalry-bar whiteboard, not like an official college athletics product.

---

# 2. Core Product Principles

## 2.1 Simple game mechanic

Every school has one current board.

The highest successful bidder controls:

- the public message
- their display name beneath the message
- their represented fanbase

Control lasts until:

- another user successfully places a higher bid
- the weekly reset occurs
- an administrator removes the message
- the board is administratively reset

The user is not buying ownership, sponsorship, affiliation, or any guaranteed amount of display time.

---

## 2.2 Weekly resets

Boards reset every Sunday at:

```text
11:59 PM America/New_York
```

At reset:

```text
current_bid = $0
current_controller = null
current_message = default
```

The first takeover afterward costs:

```text
$1
```

Historical statistics do not reset.

Examples:

```text
all-time fanbase spend
total takeovers
largest bid
user spend
rivalry totals
historical messages
```

This keeps the game financially accessible every week.

---

# 3. Trademark-Conscious Product Design

The MVP should intentionally avoid official university intellectual property wherever possible.

Use:

- plain school names
- generic accent colors inspired by the school
- completely original Take the Board typography
- completely original card layouts
- completely original icons

Do not use:

- official school logos
- mascot artwork
- helmet logos
- school seals
- athletics artwork
- copied official typography
- official graphical lockups
- claims of sponsorship or ownership

The entire interface should visually belong to Take the Board.

Each school may have a color accent for recognition, but the card structure, fonts, buttons, layout, navigation, and icons should all remain identical.

Example:

```text
Take the Board visual system
+
crimson accent
+
OKLAHOMA
```

rather than recreating Oklahoma's official athletics identity.

Global disclaimer:

```text
Take the Board is an independent fan-made entertainment platform.

We are not affiliated with, endorsed by, sponsored by, or otherwise
associated with any university, athletic department, conference, or the NCAA.

School names are used solely to identify the subjects of fan discussion.
```

Final legal language should eventually be reviewed by counsel.

---

# 4. MVP Technology Stack

The application should be built primarily as a Django monolith.

## Core stack

| Concern | Technology |
|---|---|
| Main application | Django |
| HTML/UI | Django Templates |
| Dynamic UI | HTMX + minimal JavaScript |
| Authentication | Amazon Cognito User Pool |
| Database | Amazon RDS PostgreSQL |
| Payments | Stripe Checkout |
| Payment capture | Stripe manual capture |
| Message moderation | Amazon Bedrock / Amazon Nova |
| Bid finalization | Amazon SQS FIFO |
| Worker | Django management-command worker |
| Hosting | Amazon ECS Fargate |
| Static assets | S3 + CloudFront |
| Scheduled reset | EventBridge Scheduler |
| Admin tooling | Django Admin |
| Logging | CloudWatch |
| Secrets | AWS Secrets Manager |
| Error monitoring | Sentry recommended |
| CI/CD | GitHub Actions + ECR + ECS |

The application should **not** be decomposed into Lambda functions and API Gateway endpoints for ordinary application behavior.

Django should own:

- page rendering
- business logic
- user profiles
- schools
- boards
- bidding
- leaderboards
- Stripe Checkout creation
- Stripe webhook endpoint
- moderation requests
- admin operations
- public history pages

AWS services should be used where they provide clear infrastructure value, not merely because the application is hosted in AWS.

---

# 5. High-Level Architecture

```text
                             Amazon Cognito
                                  |
                                  |
                                  v
User Browser ---------------- Authentication
     |
     v
CloudFront
     |
     v
Application Load Balancer
     |
     v
+------------------------------------------+
|                Django                    |
|                                          |
| Server-rendered pages                    |
| HTMX endpoints                           |
| User profiles                            |
| Board logic                              |
| Moderation orchestration                 |
| Stripe Checkout creation                 |
| Stripe webhook endpoint                  |
| Leaderboards                             |
| Rivalries                                |
| Django Admin                             |
+---------+----------------+---------------+
          |                |
          |                |
          v                v
   RDS PostgreSQL      Amazon Bedrock
                      Amazon Nova
                           |
                           |
                      moderation only


Stripe
  |
  | webhook
  v
Django
  |
  v
SQS FIFO
  |
  v
Django Worker on ECS
  |
  +------ Stripe capture/cancel
  |
  +------ PostgreSQL update


EventBridge Scheduler
        |
        v
Weekly reset task
```

---

# 6. Django Application Structure

Recommended repository:

```text
take-the-board/
│
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── local.py
│   │   ├── staging.py
│   │   └── production.py
│   ├── urls.py
│   └── wsgi.py
│
├── apps/
│   ├── accounts/
│   ├── schools/
│   ├── boards/
│   ├── bidding/
│   ├── payments/
│   ├── moderation/
│   ├── rivalries/
│   ├── leaderboard/
│   └── core/
│
├── templates/
│   ├── base.html
│   ├── home.html
│   ├── boards/
│   ├── rivalries/
│   ├── accounts/
│   └── components/
│
├── static/
├── infrastructure/
├── tests/
├── Dockerfile
├── docker-compose.yml
├── manage.py
└── pyproject.toml
```

---

# 7. Authentication

Use an Amazon Cognito User Pool.

Cognito is the identity provider and owns:

- passwords
- email verification
- forgot-password flow
- account recovery
- optional MFA
- social federation later
- authentication tokens

Amazon Cognito User Pools operate as an OIDC identity provider and issue JWTs for authenticated users. Django must verify Cognito tokens before trusting them.

Django should not store user passwords.

---

# 8. Local User Profile

Django still needs a local application profile.

Cognito owns identity.

Postgres owns application behavior.

Example:

```python
class UserProfile(models.Model):
    cognito_sub = models.UUIDField(unique=True)

    email = models.EmailField()

    display_name = models.CharField(
        max_length=40,
        unique=True,
    )

    favorite_school = models.ForeignKey(
        "schools.School",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    is_banned = models.BooleanField(default=False)

    total_spend_cents = models.BigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

The Cognito `sub` claim is the stable external identity key.

---

# 9. Authentication Flow

```text
User clicks Sign In
      |
      v
Cognito login
      |
      v
Cognito issues token
      |
      v
Django validates token
      |
      v
Lookup UserProfile by cognito_sub
      |
      +-- exists → continue
      |
      +-- missing → create local profile
```

For MVP, bidding requires authentication.

Browsing does not.

---

# 10. Competition and Entity Models

```python
class Competition(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    sport = models.CharField(max_length=50)
    active = models.BooleanField(default=True)


class Entity(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    slug = models.SlugField()
    short_name = models.CharField(max_length=50)
    group_name = models.CharField(
        max_length=50,
        blank=True,
    )

    accent_color = models.CharField(
        max_length=7,
    )

    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
```

Example:

```text
competition = College Football
name = Oklahoma
slug = oklahoma
accent_color = #8B1D2C
```

Do not store official logos.

---

# 11. Board Model

Each entity has exactly one active board. College Football entities are schools;
future NFL or NBA entities can be clubs without changing board, bid, payment, or
moderation relationships. Entity slugs are unique within their competition.

```python
class Board(models.Model):
    entity = models.OneToOneField(
        Entity,
        on_delete=models.CASCADE,
    )

    current_bid = models.ForeignKey(
        "bidding.Bid",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    current_controller = models.ForeignKey(
        "accounts.UserProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    current_amount_cents = models.PositiveIntegerField(
        default=0,
    )

    current_message = models.CharField(
        max_length=80,
        blank=True,
    )

    version = models.PositiveBigIntegerField(default=0)

    bidding_enabled = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)
```

`version` increments whenever board state changes.

This can later support:

- cache invalidation
- optimistic frontend updates
- polling efficiency

---

# 12. Represented Fanbase

A bidder chooses which fanbase they are representing.

This is independent from the board being attacked.

Example:

```text
Board:
Texas

Representing:
Oklahoma

Message:
49-0. NEVER FORGET.

Bid:
$58
```

The transaction contributes to Oklahoma's fanbase statistics even though it occurs on Texas's board.

---

# 13. Bid Rules

Minimum bid:

```text
max($1, current_bid + $1)
```

Examples:

```text
Current: $0
Minimum: $1

Current: $47
Minimum: $48
```

Users may overbid.

Example buttons:

```text
$48
$50
$60
$75
Custom
```

Initial maximum individual bid:

```text
$500
```

This should be configurable through application settings.

---

# 14. Bid Model

```python
class Bid(models.Model):

    class Status(models.TextChoices):
        CREATED = "created"
        MODERATION_APPROVED = "moderation_approved"
        CHECKOUT_CREATED = "checkout_created"
        AUTHORIZED = "authorized"
        PROCESSING = "processing"
        WON = "won"
        OUTBID = "outbid"
        PAYMENT_FAILED = "payment_failed"
        AUTH_CANCELED = "auth_canceled"
        REFUNDED = "refunded"
        DISPUTED = "disputed"

    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="bids",
    )

    bidder = models.ForeignKey(
        UserProfile,
        on_delete=models.PROTECT,
        related_name="bids",
    )

    represented_school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="fan_bids",
    )

    message = models.CharField(max_length=80)

    amount_cents = models.PositiveIntegerField()

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
    )

    stripe_checkout_session_id = models.CharField(
        max_length=255,
        blank=True,
    )

    stripe_payment_intent_id = models.CharField(
        max_length=255,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    authorized_at = models.DateTimeField(null=True)
    captured_at = models.DateTimeField(null=True)
```

---

# 15. Message Validation Before Payment

Message validation MUST occur before any Stripe Checkout Session or card authorization is created.

This is a deliberate product decision.

We do not want this flow:

```text
User enters bad message
      ↓
Stripe authorization
      ↓
Moderation rejection
      ↓
Authorization canceled
      ↓
User sees bank hold
      ↓
User complains
```

Instead:

```text
Message
  ↓
Validation
  ↓
Nova moderation
  ↓
Approved
  ↓
Payment
```

---

# 16. Message Validation Endpoint

Endpoint:

```text
POST /api/boards/{slug}/validate-message/
```

Input:

```json
{
  "message": "TEXAS SUCKS.",
  "represented_school": "oklahoma"
}
```

Requirements:

- authenticated user
- board must exist
- board must allow bidding
- represented school must exist
- message must be <= 80 characters
- deterministic validation must pass
- Nova moderation must pass

---

# 17. Deterministic Validation

Before calling the LLM:

Reject:

- empty message
- message > 80 characters
- URLs
- email addresses
- phone numbers
- obvious attempts to expose personal information
- excessive Unicode abuse
- control characters
- excessive repeated characters
- known severe slurs if convenient to detect deterministically

Do not reject ordinary profanity.

Examples that should generally be allowed:

```text
FUCK OU
TEXAS SUCKS
BAMA BLOWS
HORNS DOWN
```

---

# 18. Amazon Nova Moderation

Use Amazon Nova through Amazon Bedrock.

Amazon Nova models support inference through Bedrock's Converse API.

The moderation task should be a strict classifier rather than a conversational response.

Suggested decisions:

```text
ALLOW
BLOCK
REVIEW
```

Suggested categories:

```text
TEAM_TRASH_TALK
GENERAL_PROFANITY
HATE
THREAT
SEXUAL
TARGETED_HARASSMENT
PERSONAL_ATTACK
DEFAMATION_RISK
PII
SPAM
OTHER
```

---

# 19. Moderation Philosophy

This is a trash-talk product.

Moderation should allow hostility toward teams and fanbases while blocking genuinely harmful content.

Generally allowed:

```text
FUCK TEXAS
OU SUCKS
ALABAMA IS OVERRATED
MICHIGAN CHEATS
```

Generally blocked:

- racial slurs
- religious slurs
- anti-LGBT slurs
- credible threats
- doxxing
- phone numbers
- addresses
- targeted sexual harassment
- harassment directed at private individuals
- severe targeted harassment of named athletes
- defamatory factual accusations against identifiable individuals
- encouragement of violence

---

# 20. Structured Nova Output

Prompt Nova to return JSON only.

Example:

```json
{
  "decision": "ALLOW",
  "category": "TEAM_TRASH_TALK",
  "confidence": 0.98
}
```

Do not expose these internals to the user.

User-facing rejection:

```text
That message doesn't meet the trash-talk guidelines.

Rivalry insults and profanity are fine, but slurs, threats,
personal attacks, and personal information aren't allowed.
```

Do not tell the user exactly which classifier rule was triggered.

---

# 21. Message Validation Record

Successful moderation should produce a short-lived server-side approval record.

```python
class MessageValidation(models.Model):
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    user = models.ForeignKey(UserProfile)

    board = models.ForeignKey(Board)

    represented_school = models.ForeignKey(School)

    message = models.CharField(max_length=80)

    message_hash = models.CharField(max_length=64)

    decision = models.CharField(max_length=20)

    category = models.CharField(max_length=50)

    confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
    )

    expires_at = models.DateTimeField()

    consumed_at = models.DateTimeField(null=True)

    created_at = models.DateTimeField(auto_now_add=True)
```

Recommended expiration:

```text
10 minutes
```

---

# 22. Why Validation Tokens Exist

The user may validate:

```text
TEXAS SUCKS.
```

Then manually modify a request and try to submit:

```text
something completely different
```

The Checkout endpoint therefore accepts:

```text
validation_id
```

rather than accepting an arbitrary message.

The server verifies:

```text
same authenticated user
same board
same represented school
validation still approved
validation not expired
validation not consumed
message unchanged
```

---

# 23. Validation Rate Limiting

Moderation requests must be rate-limited.

Initial suggested limits:

```text
10 validations per minute per authenticated user
30 validations per hour per authenticated user
```

Also apply IP-based protection.

Users generating repeated BLOCK decisions may receive stricter temporary throttling.

This protects:

- Bedrock spend
- classifier probing
- automated abuse
- denial-of-service attempts

---

# 24. Pre-Payment UI Flow

User clicks:

```text
TAKE CONTROL FOR $48
```

Modal:

```text
TAKE OKLAHOMA

Your Message

[ TEXAS SUCKS.                  ]

Representing

[ Oklahoma ▼ ]

[ CONTINUE ]
```

User clicks Continue.

Server validates.

If successful:

```text
✓ Message approved

Current board: $47

Your bid:
$48

You will control Oklahoma until someone
successfully places a higher bid.

[ PAY $48 & TAKE THE BOARD ]
```

Only this second button begins the Stripe flow.

---

# 25. Recheck Price Before Checkout

The board may change during moderation.

Example:

```text
User begins at $48

Nova validates message

Meanwhile current board becomes $51
```

Before creating Stripe Checkout, Django must re-read the board.

If:

```text
requested_amount <= current_amount
```

do not create Checkout.

Return:

```text
Someone already took the board.

Current bid: $51

Minimum bid: $52
```

Allow the user to reuse the same validated message while its validation token remains active.

---

# 26. Stripe Checkout

Use Stripe Checkout in payment mode.

Use manual capture.

Stripe documents that Checkout can create a payment authorization without immediately capturing funds by setting `capture_method` to `manual`; the resulting PaymentIntent can later be captured by the application.

Conceptually:

```python
stripe.checkout.Session.create(
    mode="payment",

    line_items=[...],

    payment_intent_data={
        "capture_method": "manual",
        "metadata": {
            "bid_id": str(bid.public_id),
            "board_id": str(board.id),
        },
    },

    metadata={
        "bid_id": str(bid.public_id),
    },

    success_url=...,
    cancel_url=...,
)
```

Initially restrict payment methods to options compatible with the required authorization/capture behavior.

---

# 27. Why Manual Capture Is Required

Example:

```text
Oklahoma current bid = $47
```

User A opens Checkout for:

```text
$48
```

While A enters card information:

```text
User B successfully takes Oklahoma for $55
```

When A finishes Checkout:

```text
$48 is no longer a valid winning bid
```

With automatic capture, A could be charged even though the bid is invalid.

Manual capture allows:

```text
authorize
↓
recheck board
↓
capture if valid
OR
cancel authorization if already beaten
```

---

# 28. Stripe Webhook

Endpoint:

```text
POST /webhooks/stripe/
```

The webhook must:

1. verify the Stripe webhook signature
2. use the raw request body
3. store the event
4. remain idempotent
5. enqueue relevant bid-finalization work
6. return quickly

Do not rely on the browser success redirect for payment state.

---

# 29. Stripe Event Model

```python
class StripeEvent(models.Model):
    event_id = models.CharField(
        max_length=255,
        unique=True,
    )

    event_type = models.CharField(max_length=100)

    payload = models.JSONField()

    received_at = models.DateTimeField(auto_now_add=True)

    processed_at = models.DateTimeField(null=True)
```

Duplicate event:

```text
event_id already exists
→ return 200
```

---

# 30. SQS FIFO

Use:

```text
takeboard-bid-finalization.fifo
```

Each authorized bid produces:

```json
{
  "bid_id": "UUID",
  "board_id": 17,
  "payment_intent_id": "pi_..."
}
```

Use:

```text
MessageGroupId = board_id
```

SQS FIFO preserves ordering within a message group, allowing bids for the same board to be processed sequentially while unrelated boards process independently.

Example:

```text
Oklahoma bids
MessageGroupId = 17

Texas bids
MessageGroupId = 22
```

They may process concurrently.

Two Oklahoma bids will process in sequence.

---

# 31. Bid Finalization Worker

Run a long-lived Django worker on ECS.

Example:

```bash
python manage.py run_bid_worker
```

Worker responsibilities:

```text
receive SQS message
↓
load bid
↓
verify idempotency
↓
lock board
↓
compare bid against current board
↓
capture OR cancel authorization
↓
update Postgres
↓
record takeover/history
↓
acknowledge SQS message
```

---

# 32. Finalization Logic

Conceptual logic:

```python
def finalize_bid(bid_id):

    with transaction.atomic():

        bid = (
            Bid.objects
            .select_for_update()
            .get(public_id=bid_id)
        )

        if bid.status in FINAL_STATES:
            return

        board = (
            Board.objects
            .select_for_update()
            .get(pk=bid.board_id)
        )

        if bid.amount_cents <= board.current_amount_cents:
            bid.status = Bid.Status.OUTBID
            bid.save()

            transaction.on_commit(
                lambda: cancel_authorization(bid)
            )

            return

        bid.status = Bid.Status.PROCESSING
        bid.save()

    capture_payment(bid)

    with transaction.atomic():

        board = (
            Board.objects
            .select_for_update()
            .get(pk=bid.board_id)
        )

        bid = (
            Bid.objects
            .select_for_update()
            .get(pk=bid.id)
        )

        # validate state again

        publish_takeover(board, bid)
```

The exact implementation must carefully handle Stripe failures and retries.

---

# 33. Concurrency Example

Current Oklahoma:

```text
$47
```

Authorized bids:

```text
A = $48
B = $55
```

If B processes first:

```text
$55 > $47
capture B
board = $55
```

Then A:

```text
$48 <= $55
cancel A authorization
A pays $0
```

Correct.

If A processes first:

```text
capture A
board = $48
```

Then B:

```text
capture B
board = $55
```

A briefly controlled the board and legitimately paid.

Correct.

---

# 34. Payment Success Page

Browser redirect does not equal bid victory.

After Checkout:

```text
/bids/{public_id}/result/
```

Page initially says:

```text
Confirming your takeover...
```

HTMX polls:

```text
GET /api/bids/{public_id}/status/
```

Possible states:

```text
authorized
processing
won
outbid
payment_failed
```

---

# 35. Successful Bid UX

```text
YOU TOOK OKLAHOMA.

"TEXAS SUCKS."

Current bid:
$48

[ SHARE ON X ]
[ COPY LINK ]
```

---

# 36. Outbid-During-Checkout UX

```text
YOU GOT BEAT TO IT.

Someone took Oklahoma before your bid finalized.

Your payment was not captured.

Current bid:
$55

[ TAKE IT FOR $56 ]
```

Avoid saying:

```text
Your card was never touched
```

because an authorization may temporarily appear as pending.

Better:

```text
Your payment was not captured.
Any temporary authorization should be released by your card issuer.
```

---

# 37. Board Takeover History

Create an immutable takeover record.

```python
class BoardTakeover(models.Model):
    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="takeovers",
    )

    bid = models.OneToOneField(
        Bid,
        on_delete=models.PROTECT,
    )

    previous_bid = models.ForeignKey(
        Bid,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    controller = models.ForeignKey(
        UserProfile,
        on_delete=models.PROTECT,
    )

    represented_school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
    )

    message = models.CharField(max_length=80)

    amount_cents = models.PositiveIntegerField()

    occurred_at = models.DateTimeField(auto_now_add=True)
```

Example history:

```text
12m ago    SoonerSteve    TEXAS SUCKS.         $47
38m ago    HookEmHater    HORNS DOWN.           $46
1h ago     SoonerSteve    BOOMER SOONER.        $44
```

---

# 38. Financial Ledger

Do not rely only on mutable totals.

Create ledger entries.

```python
class LedgerEntry(models.Model):

    class Type(models.TextChoices):
        BID_CAPTURE = "bid_capture"
        REFUND = "refund"
        CHARGEBACK = "chargeback"
        ADJUSTMENT = "adjustment"

    type = models.CharField(
        max_length=30,
        choices=Type.choices,
    )

    amount_cents = models.IntegerField()

    user = models.ForeignKey(
        UserProfile,
        null=True,
        on_delete=models.SET_NULL,
    )

    school = models.ForeignKey(
        School,
        null=True,
        on_delete=models.SET_NULL,
    )

    bid = models.ForeignKey(
        Bid,
        null=True,
        on_delete=models.SET_NULL,
    )

    created_at = models.DateTimeField(auto_now_add=True)
```

Captured payment:

```text
+5000
```

Refund:

```text
-5000
```

Chargeback:

```text
-5000
```

This provides a reliable financial audit trail.

---

# 39. Fanbase Leaderboards

When a user represents Oklahoma while attacking Texas:

```text
represented_school = Oklahoma
board.school = Texas
```

The captured bid contributes to:

```text
Oklahoma weekly fanbase spending
Oklahoma all-time fanbase spending
```

Leaderboard:

```text
MOST UNHINGED FANBASES

1. Ohio State       $9,822
2. Michigan         $9,317
3. Texas            $8,901
4. Alabama          $7,732
5. Oklahoma         $6,945
```

---

# 40. Season Week

```python
class SeasonWeek(models.Model):
    year = models.IntegerField()

    week_number = models.IntegerField()

    starts_at = models.DateTimeField()

    ends_at = models.DateTimeField()

    active = models.BooleanField(default=False)
```

The `(year, week_number)` pair is the durable identity of a weekly period. Use the
ISO week-year for the year marker so Week 1 remains unique across calendar years;
yearly rollup statistics are not required.

Do not hardcode all-time logic around calendar week numbers.

This gives flexibility for:

```text
Week 0
Week 1
Conference Championships
Bowls
Playoffs
Offseason
```

---

# 41. Weekly Statistics

```python
class SchoolWeekStats(models.Model):
    school = models.ForeignKey(School)

    week = models.ForeignKey(SeasonWeek)

    total_spend_cents = models.BigIntegerField(default=0)

    takeovers = models.PositiveIntegerField(default=0)

    boards_attacked = models.PositiveIntegerField(default=0)

    biggest_bid_cents = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "week"],
                name="unique_school_week",
            )
        ]
```

These are cached aggregates.

The ledger remains the financial source of truth.

---

# 42. Rivalries

Explicit model:

```python
class Rivalry(models.Model):
    name = models.CharField(max_length=100)

    slug = models.SlugField(unique=True)

    school_a = models.ForeignKey(
        School,
        related_name="rivalries_a",
        on_delete=models.CASCADE,
    )

    school_b = models.ForeignKey(
        School,
        related_name="rivalries_b",
        on_delete=models.CASCADE,
    )

    active = models.BooleanField(default=True)
```

Examples:

```text
Oklahoma ↔ Texas
Michigan ↔ Ohio State
Alabama ↔ Auburn
Florida ↔ Georgia
Army ↔ Navy
```

---

# 43. Rivalry Page

Example:

```text
OKLAHOMA vs TEXAS

THIS WEEK

Oklahoma
$718

Texas
$691

Texas needs $28 to take the lead.
```

Later:

```text
all-time spending
weekly winners
largest takeover
total board attacks
top contributors
```

MVP does not require all advanced statistics.

---

# 44. Homepage

Route:

```text
/
```

Sections:

```text
hero

top boards right now

fanbase leaderboard

rivalry watch

recent activity

browse schools

how it works

legal disclaimer
```

Primary headline:

```text
COLLEGE FOOTBALL'S
PETTIEST FAN WARS.
```

Supporting copy:

```text
Fans battle for control of each school's message.

Highest bidder runs the board.

Until somebody outbids them.
```

---

# 45. School Page

Route:

```text
/schools/oklahoma/
```

Contents:

```text
school name
current message
current controller
current bid
take-control button

message history

weekly fanbase statistics

top attackers

biggest takeover

times taken
```

---

# 46. Leaderboard Page

Route:

```text
/leaderboard/
```

Tabs:

```text
THIS WEEK
ALL TIME
```

MVP rankings:

```text
Fanbase Spend
Most Attacked Schools
Most Takeovers
Biggest Individual Bids
```

---

# 47. User Profiles

Route:

```text
/u/soonersteve/
```

Public profile:

```text
SoonerSteve

Oklahoma fan

Boards Taken: 21
Total Spent: $382
Biggest Takeover: $72
Favorite Target: Texas
```

Display recent takeovers.

---

# 48. Frontend Strategy

Use:

```text
Django Templates
HTMX
minimal vanilla JavaScript
```

Do not use React for MVP.

Reasons:

- server-rendered pages
- easier authentication
- fewer API endpoints
- better SEO
- simpler deployment
- faster development
- fewer client-state concerns

---

# 49. HTMX Polling

Initially poll dynamic components every:

```text
5-10 seconds
```

Examples:

```text
current board
recent activity
leaderboard
rivalry totals
```

Endpoints:

```text
/fragments/boards/{slug}/current/
/fragments/top-boards/
/fragments/recent-activity/
/fragments/leaderboard/
```

Do not implement WebSockets initially.

---

# 50. Django Admin

Django Admin is the operational dashboard.

It should support:

## Boards

```text
view board
current controller
current message
current bid
disable bidding
reset board
remove message
```

## Users

```text
search user
view total spend
view bids
ban user
unban user
```

## Moderation

```text
message
decision
Nova category
confidence
user
board
remove
ban
```

## Payments

```text
bid
Stripe PaymentIntent ID
amount
status
refund state
dispute state
```

## Schools

```text
enable/disable
edit accent color
edit conference
```

Do not build a custom admin dashboard for MVP.

---

# 51. Administrative Message Removal

Admin may remove inappropriate messages after publication.

Recommended behavior:

```text
current_message = "THIS BOARD IS OPEN."
```

Do not automatically restore the previous controller's message.

The current paid controller may remain controller unless policy requires removing the takeover entirely.

Exact refund policy should be documented separately.

---

# 52. Abuse Protection

Use layered controls.

## User limits

Initial account:

```text
max bid = $100
max spend/hour = $250
```

Established account:

```text
max bid = $500
```

Configurable later.

## Rate-limit:

```text
message validation
login attempts
signup attempts
checkout creation
bid-status polling
```

Use application-level limits plus AWS WAF where useful.

---

# 53. Stripe Fraud Protection

Enable Stripe Radar.

Monitor:

```text
card testing
rapid payment failures
stolen-card behavior
chargebacks
high-velocity bidding
```

On:

```text
charge.dispute.created
```

mark associated bid:

```text
DISPUTED
```

Potentially suspend user automatically pending review.

---

# 54. Refunds and Disputes

Refunds should create ledger entries.

Do not delete historical bid records.

Example:

```text
Bid:
$50

Ledger:
+5000 capture
-5000 refund
```

Historical board history can remain, while financial statistics exclude refunded amounts.

---

# 55. Weekly Reset

Use EventBridge Scheduler.

At:

```text
Sunday 11:59 PM America/New_York
```

run:

```bash
python manage.py reset_boards
```

Command:

```text
close active SeasonWeek
create new SeasonWeek

for each board:
    current_bid = null
    current_controller = null
    current_amount_cents = 0
    current_message = default
    version += 1
```

Historical data remains untouched.

The reset command must be idempotent.

---

# 56. Game Configuration

Use database-backed settings.

```python
class GameConfig(models.Model):
    minimum_bid_increment_cents = models.PositiveIntegerField(
        default=100,
    )

    maximum_bid_cents = models.PositiveIntegerField(
        default=50000,
    )

    message_max_length = models.PositiveIntegerField(
        default=80,
    )

    message_validation_expiration_minutes = models.PositiveIntegerField(
        default=10,
    )

    bidding_enabled = models.BooleanField(default=True)

    moderation_enabled = models.BooleanField(default=True)
```

Avoid hardcoding game rules throughout the codebase.

---

# 57. Important Database Indexes

Growing tables:

```text
Bid
BoardTakeover
LedgerEntry
MessageValidation
StripeEvent
```

Examples:

```python
class Meta:
    indexes = [
        models.Index(
            fields=["board", "-created_at"],
        ),
        models.Index(
            fields=["bidder", "-created_at"],
        ),
        models.Index(
            fields=["represented_school", "-created_at"],
        ),
    ]
```

Takeover history:

```python
models.Index(
    fields=["board", "-occurred_at"]
)
```

Ledger:

```python
models.Index(
    fields=["school", "-created_at"]
)
```

---

# 58. PostgreSQL Scaling Philosophy

RDS PostgreSQL is the primary datastore.

This architecture is expected to comfortably support the product well beyond MVP scale.

The number of boards is extremely small:

```text
~30 initially
possibly ~130 later
```

The tables that grow are historical/event tables.

Scaling path:

```text
proper indexes
↓
larger RDS instance
↓
cached aggregate tables
↓
Redis if needed
↓
read replicas if needed
↓
partition extremely large historical tables if ever necessary
```

No alternative database should be introduced before there is evidence it is needed.

---

# 59. No DynamoDB for Core Game State

Do not use DynamoDB for:

```text
Boards
Bids
Payments
Takeovers
Ledger
```

The application benefits from:

```text
relational queries
foreign keys
transactions
SELECT FOR UPDATE
unique constraints
historical querying
```

PostgreSQL is the better fit.

---

# 60. Static Assets

Use:

```text
S3
+
CloudFront
```

for:

```text
CSS
JavaScript
fonts owned/licensed by the project
site imagery
generated social images later
```

---

# 61. ECS Services

Production should have at least:

```text
takeboard-web
takeboard-worker
```

## Web

```text
Gunicorn
Django
```

## Worker

```text
python manage.py run_bid_worker
```

Both can use the same Docker image.

Different ECS commands.

---

# 62. Local Development

Use Docker Compose:

```yaml
services:
  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000

  worker:
    build: .
    command: python manage.py run_bid_worker

  postgres:
    image: postgres:17
```

Use Stripe test mode.

Use either:

- real development AWS SQS/Bedrock resources
- mocked Bedrock for unit tests

No need for LocalStack unless specifically desired.

---

# 63. Secrets

Store production secrets in AWS Secrets Manager.

Examples:

```text
DJANGO_SECRET_KEY

DATABASE_URL

COGNITO_USER_POOL_ID
COGNITO_CLIENT_ID
COGNITO_REGION

STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET

BEDROCK_REGION
BEDROCK_MODEL_ID
```

Use ECS task roles for AWS service access wherever possible instead of static AWS credentials.

---

# 64. Logging

Use structured logging.

Every payment-related log should include where available:

```text
request_id
user_id
board_id
bid_id
stripe_payment_intent_id
stripe_event_id
```

Important events:

```text
message_validation_started
message_validation_allowed
message_validation_blocked

checkout_created

payment_authorized

bid_finalization_started

bid_outbid_before_capture

payment_capture_success

payment_capture_failure

board_takeover_published

refund_created

dispute_created
```

---

# 65. Error Monitoring

Add Sentry early.

Alert on:

```text
Stripe webhook failures
capture failures
SQS processing failures
moderation failures
database integrity errors
weekly reset failures
```

Payment errors should never disappear only into CloudWatch logs.

---

# 66. Social Sharing

Every school page should have Open Graph metadata.

Example:

```text
Oklahoma has been taken over.

"TEXAS SUCKS."

Current bid: $48
```

URL:

```text
/schools/oklahoma/
```

Successful takeover page:

```text
YOU TOOK OKLAHOMA.

[ SHARE ON X ]
[ COPY LINK ]
```

Suggested share text:

```text
I just took Oklahoma on Take the Board 😂

Someone beat $48 if they want it back.
```

---

# 67. Recent Activity

Track:

```text
SoonerSteve took Texas for $72
HookEmHater took Oklahoma for $61
Michigan passed Ohio State this week
```

A lightweight `Activity` model may be used.

```python
class Activity(models.Model):
    type = models.CharField(max_length=50)

    user = models.ForeignKey(
        UserProfile,
        null=True,
        on_delete=models.SET_NULL,
    )

    board = models.ForeignKey(
        Board,
        null=True,
        on_delete=models.SET_NULL,
    )

    metadata = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
```

---

# 68. Initial School Set

Launch with approximately:

```text
30-40 schools
```

Do not seed every FBS team initially.

Prioritize large and rivalry-heavy fanbases.

Examples:

```text
Alabama
Auburn
Georgia
Florida
Tennessee
LSU
Texas
Oklahoma
Texas A&M
Ole Miss

Michigan
Ohio State
Penn State
USC
Oregon
Nebraska
Iowa
Wisconsin

Notre Dame
Clemson
Florida State
Miami
Colorado
Army
Navy
```

---

# 69. Initial Rivalry Set

Start with approximately:

```text
10-15 rivalries
```

Examples:

```text
Oklahoma vs Texas

Michigan vs Ohio State

Alabama vs Auburn

Florida vs Georgia

USC vs Notre Dame

Army vs Navy
```

---

# 70. Community Guidelines

Public community guidelines should clearly state:

Allowed:

```text
profanity
team insults
conference insults
rivalry trash talk
mockery
sports arguments
```

Not allowed:

```text
slurs
hate speech
credible threats
doxxing
personal information
targeted sexual harassment
severe targeted harassment
impersonation
illegal content
```

---

# 71. Terms of Purchase

The terms should clearly state what a successful bid purchases.

Suggested concept:

```text
A successful bid purchases temporary control of a user-generated
message displayed on Take the Board.

Control remains until another qualifying bid successfully takes the
board, the board resets, or Take the Board removes the content under
its rules.
```

Every successful takeover receives at least 30 seconds of guaranteed display time.

A message may remain visible for:

```text
days
hours
minutes
seconds
```

The transaction is not payment for a fixed amount of time beyond the guaranteed 30-second display window.

---

# 72. MVP Payment Policy

Suggested product behavior:

```text
Winning bid captured
→ final unless refund granted administratively

Bid invalid before capture
→ authorization canceled

Payment failure
→ board unchanged

Message blocked before payment
→ no Stripe transaction created
```

This policy significantly reduces unnecessary authorization holds.

---

# 73. No Credits System

Do not introduce:

```text
Board Bucks
credits
tokens
stored balance
prepaid wallet
```

Use direct USD payments.

This reduces:

- conversion friction
- accounting complexity
- stored-value complexity
- refund confusion

---

# 74. Features Explicitly Deferred

Do not build these in initial MVP:

```text
React SPA

WebSockets

Redis

DynamoDB

API Gateway application API

Lambda-per-endpoint architecture

mobile application

user-created rivalries

fanbase crowdfunding

defensive bid top-ups

push notifications

SMS

complex badges

achievements

custom avatars

full FBS coverage

dynamic social images

native comments

private messaging
```

These can be considered after product validation.

---

# 75. Testing Priorities

## Message validation

Test:

```text
normal trash talk → ALLOW

profanity → ALLOW

slur → BLOCK

threat → BLOCK

phone number → BLOCK

URL → BLOCK

message > 80 chars → BLOCK
```

---

# 76. Validation Token Testing

Test:

```text
approved validation works

expired validation rejected

validation from another user rejected

modified message rejected

modified board rejected

already-consumed token rejected
```

---

# 77. Bid Validation

Test:

```text
board $47
bid $47
→ reject

board $47
bid $48
→ allow
```

---

# 78. Race Conditions

Scenario:

```text
board = $47

A authorized = $48
B authorized = $55
```

If B processes first:

```text
B captured
B wins

A authorization canceled
A not captured
```

If A processes first:

```text
A captured
A temporarily wins

B captured
B wins
```

---

# 79. Duplicate Stripe Events

Same webhook delivered twice:

```text
capture happens once
takeover happens once
ledger entry created once
```

---

# 80. Capture Failure

```text
authorization succeeds
capture fails
```

Expected:

```text
board unchanged
bid marked payment_failed
no takeover created
no ledger capture entry
```

---

# 81. Weekly Reset Tests

Ensure:

```text
board current state clears

historical bids remain

takeovers remain

ledger remains

all-time totals remain

new weekly stats start cleanly
```

---

# 82. Core Service Layer

Business logic should live in explicit service modules.

Suggested structure:

```text
bidding/
  services/
    create_bid.py
    finalize_bid.py
    cancel_bid.py

payments/
  services/
    create_checkout.py
    capture_payment.py
    cancel_authorization.py
    refund_payment.py

moderation/
  services/
    validate_message.py
    nova_classifier.py

boards/
  services/
    publish_takeover.py
    reset_boards.py
```

Avoid putting complex business logic primarily in:

```text
views
models
signals
```

---

# 83. Minimal Endpoint Set

Public:

```text
GET /
GET /schools/{slug}/
GET /rivalries/{slug}/
GET /leaderboard/
GET /u/{display_name}/
```

Authenticated:

```text
POST /api/boards/{slug}/validate-message/

POST /api/boards/{slug}/create-checkout/

GET /api/bids/{public_id}/status/
```

Infrastructure:

```text
POST /webhooks/stripe/
```

HTMX:

```text
GET /fragments/boards/{slug}/
GET /fragments/top-boards/
GET /fragments/recent-activity/
GET /fragments/leaderboard/
```

---

# 84. MVP Build Order

## Phase 1 — Core Django App

Build:

```text
Django project
Postgres
School
Board
UserProfile
Bid
Takeover
Django Admin
homepage
school page
fake takeovers
```

No real payments yet.

---

## Phase 2 — Cognito

Implement:

```text
Cognito User Pool
login
logout
JWT verification
local UserProfile creation
authenticated bidding requirement
```

---

## Phase 3 — Moderation

Implement:

```text
message modal
deterministic validation
Nova classification
MessageValidation records
expiration
rate limiting
```

No Stripe transaction should occur before this works reliably.

---

## Phase 4 — Stripe Checkout

Implement:

```text
create Bid
create Checkout Session
manual capture
Stripe test mode
webhook verification
StripeEvent idempotency
```

---

## Phase 5 — SQS Finalization

Implement:

```text
FIFO queue
MessageGroupId = board_id
worker ECS service
capture/cancel logic
board transaction
takeover record
ledger entry
```

---

## Phase 6 — Full User Flow

Complete:

```text
school page
↓
Take Control
↓
validate message
↓
message approved
↓
price recheck
↓
Stripe Checkout
↓
authorization
↓
SQS
↓
capture
↓
board update
↓
success page
```

---

## Phase 7 — Rivalries and Leaderboards

Build:

```text
SchoolWeekStats
fanbase leaderboard
rivalry model
rivalry pages
recent activity
```

---

## Phase 8 — Launch Hardening

Add:

```text
WAF
rate limits
Radar
Sentry
CloudWatch alarms
terms
privacy
community guidelines
refund policy
trademark disclaimer
admin moderation workflow
```

---

# 85. First Vertical Slice

The first end-to-end feature should involve only one school:

```text
Oklahoma board
```

Flow:

```text
load Oklahoma page

sign in through Cognito

click Take Control

enter message

Nova approves message

price rechecked

Stripe test Checkout

card authorized

Stripe webhook received

SQS message created

worker processes bid

Stripe captured

Postgres updated

Oklahoma changes controller

success page displays
```

Do not build 40 schools before this entire flow works.

Once this primitive is reliable, most of the product becomes reusable presentation around it.

---

# 86. MVP Success Criterion

The technical question the MVP must answer is:

```text
Can multiple real users repeatedly fight over one board,
using real payments, without payment state, moderation,
or concurrent bidding becoming inconsistent?
```

The business question is:

```text
Do college football fans find this funny enough
to spend money and retaliate when rival fans take their board?
```

The architecture should optimize for learning that answer quickly.

---

# 87. Final Architecture Summary

The MVP architecture is:

```text
Django monolith
+
Django Templates
+
HTMX
+
Amazon Cognito
+
RDS PostgreSQL
+
Amazon Bedrock / Nova message pre-validation
+
Stripe Checkout with manual capture
+
Stripe webhooks
+
SQS FIFO grouped by board
+
Django ECS worker
+
Django Admin
+
EventBridge weekly reset
+
S3 / CloudFront
+
CloudWatch
```

The intentional design philosophy is:

```text
Use Django for application complexity.

Use AWS managed services for infrastructure complexity.

Use Stripe for payment complexity.

Keep the number of moving pieces low until the product proves
that additional infrastructure is necessary.
```

The most important invariant is:

```text
NO MESSAGE THAT HAS NOT PASSED MODERATION
SHOULD REACH THE PAYMENT FLOW.

NO BID SHOULD BE CAPTURED UNLESS IT IS STILL
A VALID WINNING BID WHEN FINALIZED.
```

Everything else should be optimized around those two rules.
