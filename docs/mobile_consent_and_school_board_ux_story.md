# Post-launch story: mobile consent and school-board action hierarchy

## Priority and intent

**Priority: soon after launch, not a pre-launch blocker.**

This is a mobile UX refinement to make the school-board game loop easier to understand and act on. It should follow the launch-critical work unless the current consent implementation makes the primary takeover control unreachable.

The target experience is simple: a visitor should be able to understand the school, see the current message, and recognize that they can take the board within one mobile viewport. Analytics consent must not obscure or compete with that path.

## Problem

On the mobile school-board page, the fixed analytics-consent banner can overlap the takeover CTA. The page also has several stacked visual layers before the CTA:

1. Global navigation.
2. Shared round-status rail.
3. Back link and school identity.
4. Rivalry and share actions.
5. A `Current board` wrapper.
6. A nested current-message panel.
7. Controller and current-price details.
8. The takeover CTA.

The cookie rail makes this visible, but it is not the only issue: the current structure makes the primary action arrive too late even when consent is absent. The nested white card and dark message panel also make the page feel like a dashboard rather than one public rivalry board.

## Product outcome

On a typical 390px-wide phone, a first-time visitor can see the school name, current board state/message, and a clear takeover opportunity without a cookie-control surface blocking the action.

## User stories

- As a visitor, I can view a board and reach its takeover action even before I answer the optional analytics-consent prompt.
- As a visitor, I can make an informed, unpressured choice to accept or decline analytics cookies.
- As a fan, I can immediately tell which board I am viewing, what it currently says, who controls it, and what it costs to take over.
- As a keyboard or screen-reader user, I can use all consent and board actions without an obscured control or a focus trap.

## Scope

### A. Compact, non-obstructive analytics-consent rail

Replace the tall mobile consent banner with a compact fixed rail that is about 56–64px high on mobile. The intended one-line layout is:

```text
Analytics cookies?  Privacy  [Accept] [Decline]
```

Requirements:

- `Accept` and `Decline` must have equivalent size, prominence, and easily tappable targets. Do not use color or weight to pressure an acceptance decision.
- Keep the visible label specific to the purpose: `Analytics cookies?` is clearer than `Cookies`.
- Retain a Privacy link. The rail should not expand with explanatory prose.
- Dynamically reserve bottom document space equal to the rendered rail height whenever the rail is visible. The final page action must scroll fully above the rail.
- Do not introduce a sticky takeover CTA while the fixed consent rail is present. Two fixed bottom elements would compete and leave too little usable viewport space.
- Do not load optional analytics before consent is granted; deferring the prompt does not authorize analytics.
- Prefer showing the rail after a brief opportunity to orient on the page or following an initial non-payment interaction. It must not appear in a way that prevents seeing or opening the takeover flow.
- Keep existing privacy and consent-record behavior intact. Any compliance interpretation should be reviewed separately from this UX story.

### B. Simplified school-board hierarchy

Restructure the mobile school-board page around one strong board object rather than a card inside another card.

Desired content order:

```text
← All boards                                      [Share icon]

OKLAHOMA BOARD
OKLAHOMA

OPEN FOR TAKEOVER
────────────────────────────────
CURRENT MESSAGE
FUCK TEXAS
────────────────────────────────
nutter_butter controls this board     Current takeover $1.00

[ Take the board from $2.00 ]

Rivalry watch
```

Implementation direction:

- Retain the shared round-status rail under the global navigation. It should remain compact and must not be duplicated in the school-board hero.
- Keep the back link near the top of the board page.
- Reduce the share control to an icon-first secondary action with an accessible text label. It should not consume the visual weight of a primary CTA.
- Move `Rivalry watch` below the takeover CTA as a secondary text link.
- Treat the current-message panel as the board itself. Remove or substantially reduce the surrounding white `Current board` wrapper so there is one clear focal object.
- Keep the board status (`Open for takeover` / paused state) adjacent to the message panel, where it is relevant.
- Present controller and current takeover price as compact supporting information beneath the message. On mobile, use a two-column arrangement only when it remains legible; otherwise stack it cleanly.
- Keep the takeover CTA the strongest element below the message and price. Its content, price, and bid-modal behavior remain unchanged.
- Preserve dynamic content behavior: long approved messages, boards without a controller, paused bidding, pending bids, and authenticated/unauthenticated takeover states must all remain supported.

## Non-goals

- Do not change bidding rules, prices, payment flow, moderation, school affiliations, or the semantics of a board reset.
- Do not make the consent rail a full-screen modal.
- Do not add logos, mascots, or school abbreviations as part of this story.
- Do not redesign the desktop experience unless a responsive change is needed to preserve a shared component.
- Do not add a second countdown or sticky purchase surface to compensate for the mobile hierarchy.

## Accessibility and interaction requirements

- Consent buttons must meet minimum touch-target guidance and retain visible keyboard focus.
- The consent rail must not cover a focused element. Use appropriate scroll padding/margins as well as reserved page space.
- If consent details are opened, the dialog must manage focus, support Escape, and restore focus on close.
- The icon-first Share control requires an accessible name such as `Share Oklahoma board`.
- Preserve semantic headings, landmark structure, sufficient color contrast, and text scaling through at least 200%.
- Do not announce the running countdown repeatedly to assistive technology.

## Analytics

Keep existing board and takeover analytics unchanged. Add or verify:

- `analytics_consent_shown` when the compact rail becomes visible, including the page surface.
- Existing consent outcome tracking for accepted and declined choices, without recording optional analytics before approval.
- `takeover_cta_visible` or an equivalent exposure event only if an established analytics convention already supports it; do not add noisy scroll events solely for this work.

## Validation plan

Test at 390px-wide viewports and at short mobile heights, with consent both visible and dismissed:

- Occupied board with a short message.
- Occupied board with a multi-line message and a long controller name.
- Open board with no controller.
- Paused bidding and a pending takeover state.
- Signed-out, signed-in, and profile-incomplete takeover paths.
- Keyboard navigation and screen-reader controls for consent, Share, Rivalry watch, and Take the board.
- Slow/disabled JavaScript behavior for the consent display and no optional-analytics loading before consent.

The final visual check should confirm that the takeover action is either visible or can scroll wholly above the consent rail, and that no action is hidden behind a fixed element.

## Definition of done

- The mobile consent rail is compact, balanced, and does not obscure the takeover CTA or any focused control.
- The school-board page presents one recognizable board object rather than nested competing cards.
- The primary takeover CTA has clear visual priority over Share and Rivalry watch.
- Dynamic board states and existing analytics/payment behavior continue to work.
- Responsive, accessibility, and consent-flow checks pass.
- The change is documented in the frontend and analytics source-of-truth docs if the implemented behavior changes their stated contract.
