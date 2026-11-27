# ADR-001: Reserve stock with one conditional row update

- **Status:** Accepted
- **Date:** 2026-11-27
- **Decision owner:** Kloud Kart DE03 implementer

## Context

Two buyers can read the same last unit before either writes. Fourteen historical products already have negative balances. The shipped harness requires a clean out-of-stock result under contention, with 400 simultaneous buyers in the flash-sale scenario.

## Decision

Use the conditional `UPDATE products SET stock_quantity = stock_quantity - p_quantity WHERE stock_quantity >= p_quantity` in `functions/phase3_place_order.sql`. Let the row lock serialize competing updates and recheck availability at the default READ COMMITTED isolation level; return a refusal when no row qualifies.

## Alternatives considered

### Alternative A: Read, then update without locking

- **How it would work:** Read the balance in one statement and subtract in a later statement.
- **Why it is attractive:** Simple application code and apparently fast reads.
- **Why rejected:** Both buyers can read one unit and sell it twice; an audit trigger does not repair that race.

### Alternative B: Lock with SELECT FOR UPDATE before checkout

- **How it would work:** Lock the product, inspect its balance, and then update it.
- **Why it is attractive:** Correct serialization and easy to extend to multi-product validation.
- **Why rejected:** Adds a statement and lock handling for this single-product contract; the existing guarded update is already correct.

### Alternative C: SERIALIZABLE with retries

- **How it would work:** Run checkout at serializable isolation and retry serialization failures.
- **Why it is attractive:** Protects wider multi-row invariants.
- **Why rejected:** Requires a retry policy and can produce client-visible failures if used naively; this workload needs only one stock-row invariant.

## Consequences

- **What this buys:** The unchanged harness verifies last-unit competition, 50 winners from 400 attempts and no overselling. New deductions cannot create negative stock through this path.
- **What this costs:** Buyers of the same product wait for the row lock until transaction completion; long caller transactions increase waits. Existing negative balances remain visible.
- **What it costs the client if I am wrong:** Refunds and lost customer trust if another write path bypasses this condition.
- **What would make me revisit this:** A multi-product cart, a different isolation level, persistent lock waits, or new stock writers requires a revised locking/retry design.

## What this survives

Survives the tested flash-sale contention and checkout competing with controlled stock adjustments. It does not guarantee an instant response or a universal ten-second capacity bound. The final suite and rollback checks are in `tests/final_race.log` and `tests/final_evidence.json`; historical timing variability remains documented in `docs/inventory_audit.md`.
