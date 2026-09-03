# Bedrock/Nova Moderation Evaluation

## Purpose and scope

The versioned corpus at `data/moderation_evaluation/bedrock_regression.json`
is a developer regression suite for the live Bedrock/Nova adapter. It contains
250 synthetic, labeled cases with stable opaque IDs, content type, expected
customer action, expected normalized decision, policy category, and concise
notes. It is not production user content and must never be populated with
copied customer messages or real contact details.

The corpus is stratified as follows:

| Segment | Count | Expected outcome |
| --- | ---: | --- |
| Must-allow public sports/tradition anchors | 60 | allow / allow |
| Normal rivalry trash talk and profanity | 60 | allow / allow |
| Clear harmful content | 80 | reject / block |
| Ambiguous or borderline content | 50 | reject / review |

The clear harmful set includes synthetic threats, hate/slur fixtures, contact
and private-information fixtures, targeted sexual harassment, illegal-content
requests, and spam. The borderline set is intentionally tracked separately:
review is currently a customer-facing rejection, but it is not equivalent to a
confident block for quality metrics.

The file contains raw synthetic safety strings because the model must be tested
against representative harmful categories. Keep corpus review and access
limited to the repository's development/security group. Never send these
strings to analytics or application logs, and never use the corpus as a
production data source.

## Live evaluation workflow

Configure a development account with scoped `bedrock:Converse` permission,
`TAKEBOARD_BEDROCK_ENABLED=true`, `TAKEBOARD_BEDROCK_MODEL_ID`, and
`TAKEBOARD_BEDROCK_REGION`. Then run:

```sh
python manage.py evaluate_bedrock_moderation
```

This explicit opt-in command calls the configured adapter once per case. It
does not invoke deterministic validation, the decision cache, rate-limit
counters, or durable moderation models. It emits only aggregate metrics and
per-case IDs with normalized expected/actual decisions and categories. It never
prints candidate text, notes, prompts, model payloads, or provider responses.
The command fails before any model call when Bedrock is disabled or missing its
model/region configuration, and exits unsuccessfully if provider failures
occur. Unit tests patch the adapter and make no external network calls.

The report includes the expected-vs-actual confusion matrix, false-block rate
among expected-allow anchors, false-allow rate among clear expected-block
cases, model review and customer-facing rejection rates, category breakdown,
model/policy versions, elapsed time and min/mean/p50/p95/max latency, and
sanitized failure IDs with exception class names.

## Acceptance gates

Before enabling external dev/staging traffic:

1. zero false blocks in the 60 must-allow anchors, including standalone
   `RUDY`;
2. zero false allows in the 80 clear-block cases;
3. all provider failures are surfaced, with no approval or Checkout Session;
4. no raw candidate text appears in command output, logs, analytics, or
   persistent evaluation records; and
5. review/reject results are reported separately and investigated before
   launch.

The 250 cases are a regression suite, not statistical proof of a sub-1%
production error rate. Expand the corpus for new failure modes, keeping IDs
stable and adding synthetic cases rather than customer text.

## Latest dev evidence

The final explicit live run on 2026-09-03 used the configured `nova-lite-v1`
adapter with policy `2026-09-3`, eight bounded workers, and all 250 cases. It
completed 250 cases with no provider failures. The must-allow gate was 0/60
false blocks and the clear-block gate was 0/80 false allows. Overall model
review rate was 0.4%, customer-facing rejection rate was 48.0%, mean latency
was 1143.77 ms, p50 was 1082.53 ms, and p95 was 1566.19 ms. The ambiguous
review set remains tracked separately for policy/operator review; no approval
or Checkout path was used by the evaluator.

## Decision record

On 2026-09-03, the Nova prompt was made explicit that a standalone first name,
public athlete/coach reference, team, mascot, school tradition, or rivalry
slogan is not personal information. Personal information now means contact
details or uniquely identifying private-person information, such as a phone,
email, home address, credential, or private-person doxxing. Public sports
semantics remain compatible with allowed trash talk while true doxxing,
contact data, threats, hate/slurs, targeted sexual harassment, illegal content,
spam, URLs, and deceptive impersonation remain blocked.

The moderation policy version was bumped from `2026-08-1` to `2026-09-3` so
existing cached decisions, including the observed incorrect `RUDY` block, cannot
be reused. Redis is not broadly cleared as part of this change.

The observed dev evidence that motivated this work was a Nova `block /
personal_info / 0.95` result for standalone RUDY on the Notre Dame board;
that text is represented only by the synthetic regression anchor and targeted
tests, not in logs or analytics.
