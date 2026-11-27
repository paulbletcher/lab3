# ADR-002: Commit stock, order, item and movement as one transaction

- **Status:** Accepted
- **Date:** 2026-11-27
- **Decision owner:** Kloud Kart DE03 implementer

## Context

An order without its stock movement, or a stock deduction without an order, leaves Nana unable to fulfil or reconcile sales. The original integer primary keys have no automatic defaults; MAX(id)+1 is unsafe under concurrency. Historical orphan item references also occupy order IDs that must not be reused.

## Decision

Keep checkout stock deduction and all three inserts inside the caller transaction, allowing insertion errors to roll the statement back. Use independent sequences seeded above existing IDs, including orphan order references, and create orders as pending because checkout does not collect payment.

## Alternatives considered

### Alternative A: MAX(id)+1

- **How it would work:** Read the largest ID and add one for each insert.
- **Why it is attractive:** Requires no sequence objects.
- **Why rejected:** Concurrent sessions can allocate the same ID and fail after stock reservation.

### Alternative B: Commit each write separately

- **How it would work:** Save the stock change, order, item and log in separate transactions.
- **Why it is attractive:** Makes each individual write easy to observe.
- **Why rejected:** A later failure leaves partial business state that cannot be treated as a successful sale.

### Alternative C: One data-modifying CTE

- **How it would work:** Chain every write through RETURNING dependencies.
- **Why it is attractive:** Could reduce statement setup overhead.
- **Why rejected:** Both the earlier experiment and the follow-up combined-write candidate were rejected. The latter measured 14.63, 18.47 and 13.44 seconds, all over target, despite passing all 19 edge/rollback checks. Separate inserts remain.

## Consequences

- **What this buys:** Safe concurrent identifiers, consistent new totals and all-or-nothing state. Forced order-insert and audit-insert failures are tested.
- **What this costs:** Sequence gaps survive rollback; integer ID capacity is finite. Installation requires stopped application writers. Reinstallation keeps consumed sequence progress.
- **What it costs the client if I am wrong:** Partial orders or misleading audits if transaction ownership is misunderstood; future ID exhaustion would stop checkout.
- **What would make me revisit this:** Approaching the integer limit, payment integration, multi-product carts, or a caller that commits incorrectly would require revision.

## What this survives

Survives clean refusals, numeric insertion failure, audit insertion failure and explicit caller rollback in the tested environment. Valid pending orders do not enter the completed-spending report. See `tests/final_checkout.log`, `tests/final_audit_rollback.log` and the edge checks in `tests/final_evidence.json`.
