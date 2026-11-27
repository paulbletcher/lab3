# ADR-004: Report attributable completed spending from recorded order totals

- **Status:** Accepted
- **Date:** 2026-11-27
- **Decision owner:** Kloud Kart DE03 implementer

## Context

Fifteen status spellings, missing customers, incomplete item prices and mismatched totals make spending ambiguous. Rebuilding amounts from item lines would silently choose a different value without payment or discount evidence. Every customer, including zero-spend customers, must remain visible.

## Decision

Include orders whose trimmed lowercase status is complete/completed, with an existing customer, a non-NULL recorded total and a date before tomorrow. Preserve stored totals, show lifetime spending and order counts, and produce the current plus previous eleven calendar months with zero-filled months, deterministic running totals and exactly 100 top positions.

## Alternatives considered

### Alternative A: Sum item amounts as spending

- **How it would work:** Aggregate quantity times unit price per order.
- **Why it is attractive:** Reconciles with product-level details when lines are complete.
- **Why rejected:** Missing prices make some totals unknowable; discounts and fees may explain differences. The amount charged has not been verified.

### Alternative B: Match only the exact status completed

- **How it would work:** Filter status without normalization.
- **Why it is attractive:** Minimal SQL and no interpretation.
- **Why rejected:** Counts only 22,091 instead of 111,351 normalized completed orders across all dates.

### Alternative C: Remove suspect orders or merge shared emails

- **How it would work:** Exclude discrepancies or consolidate customers by email.
- **Why it is attractive:** Produces superficially cleaner reports.
- **Why rejected:** Hides recorded value and may merge distinct people without evidence.

## Consequences

- **What this buys:** All 40,420 customers appear; 111,195 eligible orders and 339,184,984.53 reconcile on 2026-11-27. Rank shares ties; a separate row number ordered by amount then customer ID selects exactly 100.
- **What this costs:** Recorded spending is not verified cash received or net revenue. Today is included through end of day; timestamps lack a time zone. Missing customers and future orders are excluded and disclosed.
- **What it costs the client if I am wrong:** Wrong treatment of completed statuses or stored totals can misdirect customer prioritization and revenue decisions.
- **What would make me revisit this:** Confirmed payment/discount rules, an agreed business timezone, a different month definition, or corrected customer attribution would change eligibility.

## What this survives

Survives zero-order customers, tied timestamps/ranks, future dates, monthly gaps and exact original-versus-optimized comparison in `tests/final_reporting.log`. Running totals order by date then order ID. UTC is the verified session timezone; the report moves with CURRENT_DATE and is not a fixed historical snapshot.
