# Queued Paid-Bid Checkout UX

## Purpose

Make the paid-takeover experience truthful and calm when Stripe Checkout has
completed but the bidder's takeover cannot yet be published. This is most
visible when the current board message has a longer guaranteed display window
(for example, a 600-second development configuration), but it is a real state
in the normal 30-second game as well.

This work changes the post-Checkout client experience only. It does not change
the server-authoritative bid, authorization, capture, publishing, or guarantee
rules.

## Problem

The game uses Stripe manual capture. Completing Embedded Checkout can create an
authorized bid that becomes the board's pending challenger, but that bid is not
yet captured or published while the current takeover is still guaranteed.

Today the browser continues polling after Checkout completion. When the bid is
authorized but cannot win yet, the customer can remain on a spinning treatment
and eventually see language such as "Payment successful" and "still
processing." That makes the moment feel like a completed takeover even though
a higher bid can still replace the pending challenger before the guarantee
expires.

The existing server state is correct. An authorized payment on an open board is
captured and published immediately; only an authorized bid behind an active
guaranteed takeover is a queued challenger. The presentation needs to distinguish:

- Checkout completed / authorization pending;
- bid queued as the current next challenger;
- published, captured takeover; and
- payment or authorization failure.

## Product story

As a fan who has completed checkout while another message is still in its
guaranteed display window, I want to know that my bid is next in line without
being told I have won prematurely. I should understand that a higher bid can
still move ahead of me and that I am charged only if my takeover actually wins.
I should then return naturally to the board rather than wait in a payment modal
for the guarantee window to end.

## Design principles

1. **Only a published `won` bid owns the board.** Never say "the board is
   yours," show the winner share treatment, or imply a captured charge for an
   `authorized` bid.
2. **Be concise.** Explain the queue in one short paragraph and one small
   charge clarification. Do not show internal webhook, Stripe, worker, or
   guarantee-calculation terminology.
3. **Do not make people wait for the game clock.** Once the browser knows a bid
   is queued, stop polling and leave the modal shortly. The board page is the
   right place to watch the broader game state.
4. **The server remains authoritative.** Browser polling and GA4 are display
   signals only. A delayed, duplicate, or out-of-order response must never
   publish a takeover or determine whether a card is charged.
5. **Keep the existing product language.** Extend the current school-accent,
   editorial checkout presentation with a calm static queue state rather than
   adding a second status dashboard or a guarantee countdown.

## State and copy contract

| Server-observed bid state | Modal presentation | Customer copy | Actions |
| --- | --- | --- | --- |
| `checkout_created` or no usable status yet | Brief spinner | **Confirming your bid** — "We’re confirming your payment and placing your bid." | Close remains available. No auto-return while the result is genuinely unknown. |
| `authorized` | Static queued panel; no spinner | Eyebrow: **Bid received**. Heading: **You’re up next.** Body: "The current message is still in its guaranteed time. Your bid is queued to take the board unless a higher bid moves ahead first." Small note: "You’ll only be charged if your takeover wins." | **View board** is primary. **Stay here** cancels automatic return. |
| `won` | Existing positive success treatment, only after capture/publish | Eyebrow: **Takeover complete**. Heading: **The board is yours.** Body: "You now control the [school] board." Existing safe message preview and X share action remain available. | **View board** is primary; X share remains optional; **Stay here** cancels automatic return. |
| `payment_failed` or `auth_canceled` | Static error panel | Keep the existing plain-language outcome: card was not charged for the takeover and the customer can close and try again. | No automatic return; customer chooses what to do. |
| Still non-terminal after the short confirmation poll | Static delayed panel; no indefinite spinner | **We’re confirming your bid.** "This is taking a little longer than usual. Check the board shortly for the latest status." | **View board** primary. No claim that payment succeeded or that the takeover is queued. |

`authorized` is the key state for this story. It means the bid is pending for
the next available board slot, not that the bidder has won. Do not use
"payment successful" for that state. If a provider-specific completion signal
must be acknowledged, use "Bid received" instead.

An open board has no protected slot to wait behind. Its authorized bid must be
captured and published by the worker before the browser observes the terminal
`won` state, so the queued panel is never used merely because Stripe authorization
was asynchronous.

## Modal behavior

### From Checkout completion to queue detection

1. Stripe reports embedded Checkout completion.
2. Destroy the Checkout instance as the current implementation does.
3. Poll the bidder-owned status endpoint briefly while the webhook/worker path
   establishes the bid state.
4. If the response is `authorized`, render the queued panel immediately. Do
   not keep polling for a `won` result: a long guarantee can make that wait
   many minutes.
5. If the result becomes `won`, show the true winner treatment immediately.
6. If the short poll reaches its limit without a terminal or queued result,
   replace the spinner with the delayed panel rather than leaving an animated
   waiting state on screen.

### Returning to the board

The queued, won, and delayed panels should each have a primary **View board**
button. It navigates to the safe board URL already returned by the bidder-owned
status endpoint:

- queued: append the existing `move=pending` result marker;
- won: append `move=live`;
- delayed: append `move=processing`.

After rendering a queued or won panel, start a 10-second return timer. When it
fires, navigate to the same board URL. Navigation naturally removes the modal;
there is no separate background refresh or second page reload. The panel must
show a concise return notice (for example, "Returning to the board shortly")
and a **Stay here** control that cancels the timer. Do not auto-return after an
error. If the customer activates any explicit action, cancel the timer before
performing that action.

Ten seconds is long enough to read the state and use the primary action, while
still preventing a completed Checkout flow from becoming a stranded modal. The
timer must be cancellable to avoid forcing navigation on a keyboard or
assistive-technology user.

The board page already knows how to present `pending`, `live`, and `processing`
outcomes. It should remain the source of the broader public board display. Do
not add a per-bid guarantee countdown to the modal for this story.

## Client and server contract

The existing bidder-owned status endpoint already supplies the information the
client needs: lifecycle `status`, safe `board_url`, board name, represented
school name, message, and amount. Do not expose Stripe IDs, webhook data,
authorization identifiers, another bidder's data, or raw timestamps merely to
support this UI.

The implementation may keep a last successful status payload while polling so
the queued and delayed views can link to the board. It must treat a missing or
failed status response as unknown, not as a successful authorization.

No model or migration is expected. This is a JavaScript/template/CSS behavior
change unless testing reveals a small, safe status-response addition is
required.

## Visual and interaction direction

Use the existing checkout panel rather than creating a new modal:

- The brief unknown state retains the existing animated marker.
- The queued state replaces the spinner with a static, school-accent marker
  that reads as a place in line (for example, a simple numbered or directional
  mark), not a green check or success icon.
- The true `won` state retains the current checkmark and celebratory hierarchy.
- The delayed and error states are distinct, static, and readable at narrow
  widths.
- Buttons must retain clear focus states, sufficient contrast, and a sensible
  stacked mobile layout. Respect `prefers-reduced-motion`; the queued state
  should not require motion to convey status.

Do not add official school logos, marks, or athletics styling.

## Accessibility requirements

- Use `role="status"` / an appropriate polite live region for normal state
  changes and `role="alert"` only for errors.
- Update the heading and copy atomically so screen-reader users hear the new
  state once rather than repeated polling announcements.
- Do not move keyboard focus automatically when a state changes. Keep the
  modal close button available and make the **View board** and **Stay here**
  controls keyboard reachable.
- The automatic return must be visible, cancellable, and disabled once the
  user chooses **Stay here**. Never auto-navigate on error.
- Test the full sequence with keyboard-only operation, mobile viewport, and
  reduced-motion preference.

## Analytics

Use the existing analytics contract rather than sending a new payment truth
signal:

- Emit existing `takeover_status` with `status=authorized` as soon as the
  queued panel is observed.
- Continue `takeover_status` for `won`, `payment_failed`, `auth_canceled`, and
  the delayed/processing outcome as appropriate.
- Continue `takeover_won` only after a browser observes `won`.
- Record the automatic board return through the existing `modal_closed` event
  with the approved low-cardinality `close_method=auto_return` and
  `modal_step=queued` or `success` if the existing modal instrumentation can
  represent it cleanly.

Do not send board messages, payment IDs, bid IDs, names, full URLs, or timer
values to GA4. GA4 remains non-authoritative and production-consent-gated.
Update `docs/analytics_tracking.md` only if the implementation adds a new
documented `modal_step` or `close_method` value.

## Security and operational constraints

- Preserve the status endpoint’s bidder ownership filter and rate limit.
- Do not add client-provided state that changes authorization, capture,
  publishing, or board priority.
- Keep all dynamic message, board, and display-name output escaped. The
  current JS should continue assigning dynamic text through `textContent`, not
  interpolating it into HTML.
- Do not log payment status payloads or add new sensitive browser telemetry.
- A browser tab closing, polling timeout, navigation, or automatic return must
  have no effect on the worker's finalization path.

## Test plan and acceptance criteria

Add focused automated coverage for the client-side state mapping in the
repository's established test style, plus server/template assertions where
appropriate. At minimum verify:

1. An `authorized` status stops the wait, renders the queued copy, and never
   renders winner/share copy.
2. A `won` status renders the current true-win treatment and safe share link.
3. `payment_failed` and `auth_canceled` render the non-charge error and never
   auto-return.
4. A status timeout replaces the spinner with delayed copy; it never claims a
   charge, win, or queue position.
5. **View board** navigates to the expected safe board URL with the correct
   `move` marker for queued, won, and delayed outcomes.
6. The queued and won timers return to the board after 10 seconds; **Stay
   here**, Close, Share, and View board cancel pending timers appropriately.
7. Queue/win analytics use only approved low-cardinality existing parameters.
8. Dynamic board/message/team text remains escaped, and a missing/failed status
   response is treated as unknown.
9. Keyboard, focus, mobile, and reduced-motion behavior remain usable.

Run the relevant Django tests and browser/client checks. Because this changes a
running public board surface, run the repository's required local HTTP curl
against `/schools/alabama/` before completion. Update the frontend overview,
analytics contract if needed, and this design document if implementation makes
a durable decision that differs from the story.

## Out of scope

- Changing the 30-second guarantee rule, its configuration, or payment
  capture/finalization behavior.
- A live countdown for the current takeover or pending challenger.
- New push notifications, email, or a dedicated bid-tracking screen.
- Any changes to Stripe credentials, webhooks, worker topology, or production
  infrastructure.
