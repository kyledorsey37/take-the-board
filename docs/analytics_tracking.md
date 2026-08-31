# GA4 event tracking

Take the Board uses the Google tag in `templates/base.html` and a fail-silent
`window.takeTheBoard.trackEvent()` helper in `static/js/app.js`. The tag is
rendered only when production has a valid `GOOGLE_ANALYTICS_MEASUREMENT_ID`.
Local and staging environments intentionally do not collect analytics.

## Rules

- Never send board messages, report text, emails, OTP codes, display names,
  authentication tokens, Stripe identifiers, bid public IDs, or raw URLs as
  event parameters.
- Use the school or rivalry slug only when it is useful for aggregate product
  analysis. These are product content identifiers, not user identifiers.
- Use `amount_bucket`, not the exact amount. Current buckets are `1_to_4`,
  `5_to_9`, `10_to_24`, `25_to_99`, and `100_plus`.
- Event names describe an interaction or a user-visible result. Server-side
  payment and moderation state remains authoritative; browser events are for
  funnel analysis only.

## Event catalog

| Event | When | Useful parameters |
| --- | --- | --- |
| `hero_viewed` | Home hero is rendered | `surface`, `hero_variant` |
| `navigation_click` | Public navigation or discovery link clicked | `surface`, `destination`, `school_slug`, `rivalry_slug`, `hero_variant` |
| `board_opened` | A board link is clicked | `surface`, `school_slug`, `rivalry_slug`, `target` |
| `takeover_cta_clicked` | A takeover CTA is clicked | `surface`, `school_slug`, `cta`, `hero_variant` |
| `rivalry_opened` | A rivalry card is clicked | `surface`, `rivalry_slug` |
| `rivalry_back_side_clicked` | A rivalry side CTA is clicked | `surface`, `rivalry_slug`, `school_slug` |
| `board_share_clicked` | Share intent begins | `surface`, `school_slug` |
| `board_share_result` | Share succeeds, is dismissed, or fails | `surface`, `school_slug`, `result`, `share_method` |
| `auth_modal_opened` | Sign-in modal opens | `surface`, `auth_context`, `school_slug`, `modal_id` |
| `auth_code_requested` | Email OTP request returns | `auth_context`, `result` |
| `auth_code_verified` | OTP verification returns | `auth_context`, `result` |
| `auth_code_resent` | Resend request returns | `auth_context`, `result` |
| `auth_email_changed` | User goes back to email entry | `auth_context` |
| `display_name_submitted` | Board name save returns | `auth_context`, `result` |
| `profile_setup_opened` | Profile setup modal opens | `surface`, `school_slug`, `modal_id` |
| `bid_modal_opened` | Takeover form modal opens | `surface`, `school_slug`, `modal_id` |
| `modal_closed` | Any tracked dialog closes | `modal_id`, `modal_step`, `close_method`, `school_slug` |
| `school_backing_selected` | A backing school is selected | `school_slug`, `backing_school_slug` |
| `school_picker_opened` | Backing-school picker opens | `school_slug`, `target` |
| `bid_amount_selected` | A quick amount is selected | `school_slug`, `amount_bucket`, `target` |
| `takeover_submitted` | Takeover form passes browser validation and submits | `surface`, `school_slug`, `amount_bucket` |
| `form_validation_error` | A tracked form is blocked by browser validation | `surface`, `field`, `school_slug` |
| `takeover_result_viewed` | Bid result is rendered | `surface`, `school_slug`, `result` |
| `bid_confirmation_viewed` | Paid bid review step is rendered | `surface`, `school_slug`, `amount_bucket` |
| `bid_confirmation_submitted` | Paid bid confirmation submits | `surface`, `school_slug`, `amount_bucket` |
| `bid_confirmation_back_clicked` | User returns from review to edit the bid | `surface`, `school_slug` |
| `checkout_loaded` | Stripe Embedded Checkout mounts | `school_slug`, `amount_bucket` |
| `checkout_completed` | Stripe reports checkout completion to the browser | `school_slug`, `amount_bucket` |
| `checkout_error` | Checkout cannot load | `school_slug`, `amount_bucket`, `result` |
| `takeover_status` | Browser observes a terminal or final takeover state | `school_slug`, `status`, `amount_bucket` |
| `takeover_won` | Browser observes a won takeover | `school_slug`, `amount_bucket` |
| `report_modal_opened` | Report modal opens | `school_slug`, `modal_id` |
| `report_submitted` | Report form submits | `school_slug`, `category` |
| `report_result_viewed` | Report response fragment renders | `surface`, `result` |
| `standings_period_changed` | Leaderboard period link is clicked | `period` |
| `rivalry_period_changed` | Rivalry period link is clicked | `rivalry_slug`, `period` |
| `faq_opened` | FAQ item opens | `surface`, `faq_id` |
| `sign_out` | Sign-out form submits | `surface` |

## Recommended GA4 setup before launch

1. Create the production web data stream and put its `G-...` measurement ID in
   the production environment only.
2. Decide and implement the privacy notice and consent behavior for the
   jurisdictions where the game is offered before enabling collection.
3. Register only the low-cardinality parameters needed in reports as custom
   dimensions: `surface`, `destination`, `school_slug`, `rivalry_slug`,
   `hero_variant`, `cta`, `modal_id`, `modal_step`, `close_method`,
   `auth_context`, `result`, `status`, `amount_bucket`, `share_method`,
   `category`, `faq_id`, and `period`.
4. Build explorations around these funnels:
   - home hero → board opened → bid modal opened → takeover submitted;
   - auth modal opened → code requested → code verified → profile setup;
   - takeover submitted → confirmation viewed → checkout loaded → checkout
     completed → takeover status `won`;
   - report modal opened → report submitted → report result viewed.
5. Use GA4 Enhanced Measurement for scroll and outbound-link reporting rather
   than adding noisy application events.

GA4 events do not replace server-side payment, moderation, or audit records.
Those records remain the source of truth for business outcomes.
