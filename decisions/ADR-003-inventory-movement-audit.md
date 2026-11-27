# ADR-003: Record movements through restricted atomic functions

- **Status:** Accepted
- **Date:** 2026-11-27
- **Decision owner:** Kloud Kart DE03 implementer

## Context

Sales, restocks, inspected returns, damage, corrections and stock takes need an explainable audit trail. Direct stock writes could bypass logging. The original schema has no movement trigger; a trigger that merely logs stock changes cannot stop two buyers using a stale balance.

Check 22 now finds 144 product balances different from net movements (2,553 absolute units). Unknown opening balances prevent classifying those differences as proven errors; the audit trail alone does not certify physical stock. Evidence: tests/gapfix_stock_reconciliation.json.

## Decision

Keep sale logging inside `place_order` and use `record_inventory_movement` for other supported movements, updating stock and inserting the log atomically. Restrict the application role to these SECURITY DEFINER functions with a limited owner and safe search path; do not add a duplicate logging trigger.

## Alternatives considered

### Alternative A: AFTER UPDATE audit trigger

- **How it would work:** Automatically insert a movement after each stock update.
- **Why it is attractive:** Captures direct updates through one database hook.
- **Why rejected:** A stock delta alone lacks reason, return inspection and order context; adding it alongside current logging doubles the trail. A logging trigger alone does not reserve stock safely.

### Alternative B: Application-only logging

- **How it would work:** Let each application write its own stock and log records.
- **Why it is attractive:** Easy to integrate without database permissions changes.
- **Why rejected:** A forgotten log, separate transaction or unauthorized direct update breaks the invariant.

### Alternative C: Superuser application connections

- **How it would work:** Continue using unrestricted administrator credentials.
- **Why it is attractive:** No role setup needed.
- **Why rejected:** Every caller can bypass or rewrite the audit trail; the supplied harness uses admin only for fixture administration.

## Consequences

- **What this buys:** One movement per approved operation, inspected-return checks and protected historical logs for the restricted application role. No duplicate trigger records.
- **What this costs:** Requires application connections to use a restricted login assigned the NOLOGIN application role. Current role tests use SET LOCAL ROLE. Warehouse and checkout capabilities share one role.
- **What it costs the client if I am wrong:** Unlogged changes or uninspected returns could overstate sellable stock if a privileged connection or inappropriate role is used.
- **What would make me revisit this:** A production login model, separate warehouse permissions, additional writers, or a requirement to audit privileged administrators warrants revision.

## What this survives

Survives all 19 movement cases, forced audit-write failure and 12 application permission checks re-executed in `tests/final_movements.log`, `tests/final_audit_rollback.log` and `tests/final_permissions.log`. Administrators retain bypass capability; this is not a tamper-proof external ledger. Row locking prevents the stock race; transactional inserts and permissions protect the movement record.
