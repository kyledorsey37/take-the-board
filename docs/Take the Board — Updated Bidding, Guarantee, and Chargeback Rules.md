# Take the Board — Updated Bidding, Guarantee, and Chargeback Rules

## 1. Core bidding mechanic

Each board has:

- one current controller
- one current live message
- one current captured bid amount
- optionally one pending challenger
- a short guaranteed display window after every successful takeover

The governing rule is:

> Every successfully captured takeover gets at least 30 seconds of guaranteed display time. During that 30-second window, higher bids may still be submitted, but only the highest valid challenger remains pending.

This preserves the most important behavior of the product:

> Higher bids can take over quickly.

The product should feel live and competitive, not like users are reserving future advertising slots.

---

# 2. 30-second guaranteed display window

When a bid successfully wins and is captured:

```text
published_at = now
guaranteed_until = published_at + 30 seconds
```

The message immediately becomes live.

Example:

```text
8:00:00 PM

Oklahoma board
Current bid: $50
Message: FUCK OU
```

That bidder is guaranteed to remain visible until:

```text
8:00:30 PM
```

Even if someone submits a higher bid during those 30 seconds.

The guarantee exists so that every person whose payment is actually captured receives a meaningful minimum deliverable:

- their message appears publicly
- they have time to see it
- they can refresh the page
- they can screenshot it
- they can share it

A successfully captured bid should never disappear immediately because another payment happened milliseconds later.

---

# 3. Challenging during the guarantee window

Higher bids are still allowed while the current controller is protected.

Example:

```text
Current controller:
$50
guaranteed until 8:00:30
```

At 8:00:10:

```text
Bidder B submits $55
```

B's card is authorized through Stripe using manual capture.

B is not yet charged.

B becomes:

```text
Pending Challenger: $55
```

The current $50 message remains live until its guarantee expires.

---

# 4. Only the highest challenger survives

Suppose another person submits:

```text
Bidder C: $60
```

while $55 is already pending.

The new effective high bid becomes:

```text
$60
```

C replaces B as the pending challenger.

B's Stripe authorization should be canceled.

B's payment is never captured.

State becomes:

```text
CURRENT

$50
live message
guaranteed until 8:00:30


PENDING CHALLENGER

$60
authorized
not captured
```

The system does not maintain a queue of $55, $60, $65, etc.

There is only:

```text
one current winner
+
one highest pending challenger
```

This keeps the mechanic understandable and prevents long takeover queues.

---

# 5. Minimum next bid

The minimum valid bid must always be calculated against the highest economically relevant bid.

Use:

```text
effective_high_bid =
max(
    current_captured_bid,
    pending_challenger_bid
)
```

Then:

```text
minimum_next_bid =
effective_high_bid + $1
```

Example:

```text
Current board:
$50

Pending challenger:
$60
```

The next valid bid is:

```text
$61
```

not:

```text
$51
```

The frontend should display the current minimum before Checkout begins.

---

# 6. What happens when the 30 seconds expire

At:

```text
guaranteed_until
```

the system checks whether a pending challenger exists.

If there is no challenger:

```text
current controller remains live
```

There is no maximum duration.

The message may remain live for:

```text
30 seconds
5 minutes
2 hours
several days
```

until somebody successfully outbids it or the weekly reset occurs.

If a pending challenger exists:

```text
capture pending challenger
```

If Stripe capture succeeds:

```text
challenger becomes current controller
message becomes live
new 30-second guarantee begins
```

Example:

```text
8:00:30

$60 challenger captures successfully
↓
$60 message immediately publishes
↓
guaranteed until 8:01:00
```

The cycle repeats.

---

# 7. If pending challenger capture fails

Suppose:

```text
Current = $50
Pending = $60
```

At guarantee expiration, Stripe capture for $60 fails.

Then:

```text
$50 controller remains live
```

The failed challenger does not receive board control.

Mark:

```text
Bid.status = PAYMENT_FAILED
```

Clear the pending challenger.

The board remains available for new challenges.

Never publish a takeover before payment capture succeeds.

---

# 8. Race condition example

Start:

```text
Current:
$50

guaranteed until:
8:00:30
```

Then:

```text
8:00:05 → B authorizes $55
8:00:10 → C authorizes $60
8:00:17 → D authorizes $75
```

Desired outcome:

```text
B → authorization canceled
C → authorization canceled
D → remains pending
```

At 8:00:30:

```text
capture D's $75
```

If capture succeeds:

```text
D goes live
D gets guaranteed until 8:01:00
```

Only:

```text
$50
and
$75
```

are captured.

The intermediate $55 and $60 bidders are not charged.

---

# 9. No future takeover queue

Do not implement:

```text
$50 gets 30 sec
then $55 gets 30 sec
then $60 gets 30 sec
then $75 gets 30 sec
```

That weakens the game's central mechanic.

Higher bids should feel like:

> I paid more, so I took control next.

Not:

> I paid more, so my scheduled slot begins in twelve minutes.

The system therefore keeps only the highest pending challenger.

---

# 10. Message validation occurs before Stripe

No Stripe transaction should be created before the user's message has successfully passed moderation.

Flow:

```text
message entered
↓
deterministic validation
↓
Amazon Nova moderation
↓
approved
↓
price recheck
↓
Stripe Checkout
```

This prevents users from receiving card authorization holds for messages that were never eligible to publish.

---

# 11. Price recheck before Checkout

The board may change while moderation occurs.

Before creating Stripe Checkout:

```text
re-read current board
re-read pending challenger
calculate current minimum
```

If the user's proposed bid is now too low:

```text
do not create Stripe Checkout
```

Tell the user:

```text
Someone raised the board.

Current minimum: $61

Your approved message can still be used.
```

---

# 12. Manual Stripe authorization

Stripe Checkout should use manual capture.

The payment lifecycle is:

```text
authorize
↓
wait for bid outcome
↓
capture only if the user becomes the next valid controller
OR
cancel authorization if outbid
```

This is essential.

A user who never receives a takeover should not have their payment captured.

---

# 13. User-facing explanation for canceled challengers

Do not tell users:

```text
You were never charged.
```

because their bank may temporarily display the authorization.

Use:

```text
You were outbid before your takeover began.

Your payment was not captured.

Any temporary authorization will be released by your card issuer.
```

This is more accurate.

---

# 14. Purchase disclosure before payment

Immediately before sending the user to Stripe, clearly show:

```text
Board:
Oklahoma

Message:
FUCK OU

Bid:
$60

Minimum guaranteed display:
30 seconds
```

Also explain:

> A successful takeover receives at least 30 seconds of guaranteed display. After that, your message remains live until a higher successful bid takes control or the board resets.

The user must affirmatively continue.

This establishes exactly what they are purchasing.

---

# 15. High-value bid confirmation

For larger transactions, introduce additional friction.

Suggested threshold:

```text
$50 or $100
```

Example:

```text
You're about to spend $100 to take Oklahoma.

This is a real-money purchase.

If your bid successfully takes the board, it is final
and includes at least 30 seconds of guaranteed display.

[ CONFIRM $100 BID ]
```

This reduces:

- accidental spending
- intoxicated impulse regret
- mistaken extra zeroes
- buyer's-remorse disputes

---

# 16. New-user spending limits

Initial suggested limits:

```text
New account:
max individual bid = $100
max spend per rolling hour = $250
```

Established users may later have:

```text
max individual bid = $500
```

These limits should be configurable.

They protect against both:

- actual fraud
- reckless legitimate spending

---

# 17. Chargeback prevention philosophy

The biggest expected payment risk may not be stolen cards.

It may be:

```text
friendly fraud
+
buyer remorse
```

Example:

> User spends $100 while drinking Saturday night, regrets it Sunday, and disputes the payment.

No technical system can prevent someone from filing a dispute.

The goal is to create strong evidence that:

```text
the user intentionally made the purchase
+
the product clearly explained the rules
+
the promised service was delivered
```

---

# 18. Evidence retained for every captured bid

For every successful takeover, store:

```text
authenticated user ID
Cognito subject
email
display name

board ID
board name

represented team

message

bid amount

requested_at
authorized_at
captured_at
published_at
guaranteed_until
outbid_at

Stripe Checkout Session ID
Stripe PaymentIntent ID
Stripe Charge ID

IP address where legally/appropriately retained
user agent
request ID

terms/version acknowledged
purchase confirmation timestamp
```

This allows the system to demonstrate:

> The authenticated user intentionally submitted this message, authorized this exact amount, accepted the purchase terms, payment was captured, and the message was publicly displayed for the promised period.

---

# 19. Record actual delivery

For chargeback evidence, retain proof of delivery.

Example:

```text
Bid:
$100

Captured:
11:42:03 PM

Published:
11:42:04 PM

Guaranteed through:
11:42:34 PM

Actually remained live until:
11:57:21 PM
```

That is strong evidence for a digital-service dispute.

A `BoardTakeover` record should therefore store:

```text
published_at
guaranteed_until
ended_at
```

---

# 20. Terms acknowledgement

The purchase page should state that:

- bids involve real money
- successful captured bids are generally final
- every successful takeover receives at least 30 seconds of display
- no display duration beyond 30 seconds is guaranteed
- another user may immediately challenge during the guarantee
- the highest authorized challenger becomes next controller after the guarantee
- intermediate challengers who are outbid are not captured
- moderation-rule violations may result in removal
- board resets also terminate control

Do not bury all of this solely in a Terms page.

The most important rules should be visible at checkout.

---

# 21. Stripe Radar

Enable Stripe Radar.

Use it for:

```text
stolen cards
card testing
unusual payment behavior
velocity anomalies
high-risk transactions
```

Let Radar request stronger authentication where appropriate.

For high-risk or unusually large transactions, 3D Secure may provide additional evidence that the actual cardholder authenticated the purchase.

---

# 22. Large-bid friction

Larger bids should intentionally require slightly more effort.

Potential thresholds:

```text
< $50
normal checkout

$50-$99
explicit confirmation

$100+
explicit confirmation + possible 3DS/Radar scrutiny
```

Avoid making large real-money spending feel like a frictionless game token.

---

# 23. Do not use one-click rebidding initially

Avoid:

```text
ONE CLICK TO TAKE IT BACK FOR $101
```

with a stored card.

Instead require the normal payment confirmation flow.

A small amount of friction is desirable because:

```text
real dollars are being spent
```

This reduces impulsive chargeback behavior.

---

# 24. Refund policy

Suggested default:

```text
Captured winning bids are final.
```

Exceptions may be made administratively for:

```text
technical failure
duplicate capture
service malfunction
administrative error
other exceptional circumstances
```

A user being outbid after their guaranteed period is not grounds for a refund.

Likewise:

```text
I regret spending the money
```

is not normally grounds for a refund.

---

# 25. Moderation removals

If a message violates community rules after publication:

```text
admin may remove the message
```

Terms should explain that content removal for rule violations does not necessarily create a refund entitlement.

The exact refund policy should eventually receive legal review.

---

# 26. Disputes

When Stripe reports:

```text
charge.dispute.created
```

the system should:

```text
mark bid disputed
flag user
store dispute ID
surface dispute in Django Admin
```

Potentially:

```text
temporarily suspend bidding privileges
```

until review.

Use stored takeover evidence when responding to the dispute.

---

# 27. Repeat dispute behavior

Users with repeated disputes should receive stronger restrictions.

Potential rules:

```text
1 dispute
→ review

repeated disputes
→ lower bid limits

multiple suspicious disputes
→ bidding suspension or account ban
```

The platform should not continue allowing someone to generate payment risk indefinitely.

---

# 28. Core bidding invariant

The most important financial rule is:

> A payment is captured only when that bidder actually receives control of the board.

And:

> Every captured takeover receives at least 30 seconds of guaranteed public display.

Those two rules should remain true regardless of:

- concurrency
- webhook retries
- Stripe delays
- multiple challengers
- worker retries
- frontend refreshes

---

# 29. Simplified state model

At any moment:

```text
BOARD
│
├── Current Controller
│      amount
│      message
│      published_at
│      guaranteed_until
│
└── Pending Challenger
       amount
       message
       Stripe authorization
```

There should never be more than:

```text
one pending challenger
```

for a board.

---

# 30. Complete example

Current state:

```text
Oklahoma

"FUCK OU"

Controller:
TexasFan92

Bid:
$50

Guaranteed:
19 seconds remaining
```

User B submits:

```text
$55
```

Stripe:

```text
authorize $55
```

Pending:

```text
$55
```

Then User C submits:

```text
$60
```

Stripe:

```text
authorize $60
```

System:

```text
cancel $55 authorization
```

Pending:

```text
$60
```

UI now shows:

```text
Oklahoma

"FUCK OU"

$50

Guaranteed for:
12 more seconds

🔥 $60 challenge waiting

Minimum next bid:
$61
```

At zero:

```text
capture $60
```

If successful:

```text
publish User C's message
```

New state:

```text
Current:
$60

Guaranteed:
30 seconds

Pending:
none
```

If nobody challenges:

```text
$60 message stays indefinitely
```

If someone submits:

```text
$75
```

during that period:

```text
authorize $75
queue as highest challenger
```

The game repeats.

---

# 31. Final product rule in plain English

The user-facing rules should be understandable in a few sentences:

> Bid higher to take control of a team's board. Every successful takeover gets at least 30 seconds on the board. People can challenge you immediately, but your message stays up for your full guaranteed window. If multiple people challenge during that time, only the highest bidder moves on; lower challengers are not charged. After your 30 seconds, you stay on the board until the highest successful challenger takes it from you.

That should be the foundation of the bidding system.