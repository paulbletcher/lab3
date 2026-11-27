# ADR-001: Lock current stock before validating and reserving it

- **Status:** Accepted
- **Date:** 2026-11-27
- **Decision owner:** Kloud Kart DE03 implementer

## Context

Two buyers can read the same last unit before either writes. Fourteen historical products already have negative balances. The shipped harness requires a clean out-of-stock result under contention, with 400 simultaneous buyers in the flash-sale scenario.

## Decision

Lock the product with `SELECT ... FOR NO KEY UPDATE`, validate the current locked balance and price, then deduct using a guarded UPDATE and complete the order/item/audit inserts in the caller transaction. This preserves row-level serialization while avoiding a failed UPDATE and fallback lookup for exhausted-stock refusals.

## Alternatives considered

### Alternative A: Read, then update without locking

- **How it would work:** Read the balance in one statement and subtract in a later statement.
- **Why it is attractive:** Simple application code and apparently fast reads.
- **Why rejected:** Both buyers can read one unit and sell it twice; an audit trigger does not repair that race.

### Alternative B: One conditional UPDATE with customer validation

- **How it would work:** Deduct with a stock predicate and customer-existence check, then look up details if no row was updated.
- **Why it is attractive:** Correct concurrency with a compact successful path; this was the preceding implementation.
- **Why rejected:** Authenticated Linux observations were 14.92, 8.54 and 9.36 seconds. The selected lock-first version measured 9.29, 7.98 and 7.54 seconds; it met ten seconds in those three trials, but a final full-suite confirmation took 19.62 seconds. The timing requirement remains inconsistent.

### Alternative C: SERIALIZABLE with retries

- **How it would work:** Run checkout at serializable isolation and retry serialization failures.
- **Why it is attractive:** Protects wider multi-row invariants.
- **Why rejected:** Requires a retry policy and can produce client-visible failures if used naively; this workload needs only one stock-row invariant.

## Consequences

- **What this buys:** The unchanged harness verifies last-unit competition, 50 winners from 400 attempts and no overselling. New deductions cannot create negative stock through this path.
- **What this costs:** Buyers of the same product wait for the row lock until transaction completion; long caller transactions increase waits. Even refused calls briefly lock the row, and row locking can cause disk writes. Existing negative balances remain visible.
- **What it costs the client if I am wrong:** Refunds and lost customer trust if another write path bypasses this condition.
- **What would make me revisit this:** A multi-product cart, a different isolation level, persistent lock waits, or new stock writers requires a revised locking/retry design.

## What this survives

Survives the tested flash-sale contention and checkout competing with controlled stock adjustments. It does not guarantee an instant response or a universal ten-second capacity bound. The final suite and rollback checks are in `tests/final_race.log` and `tests/final_evidence.json`; historical timing variability remains documented in `docs/inventory_audit.md`.

The accepted timing path uses the unchanged harness in a pinned Linux test client, with the same SCRAM password authentication and the same server resources. Native Windows connection-only controls exceeded eighteen seconds. No durability settings, indexes, buyer counts or harness code were changed. Follow-up evidence is in `tests/phase3/logs/flash_final_selected.json`.
