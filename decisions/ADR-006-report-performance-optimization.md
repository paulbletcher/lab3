# ADR-006: Reuse a month template and materialize eligible orders within each report

- **Status:** Accepted
- **Date:** 2026-11-27
- **Decision owner:** Kloud Kart DE03 implementer

## Context

The original report expanded 40,420 customers into 485,040 customer-month rows. The prior local median was 3,731.280 ms; a rolled-back candidate measured 1,222.963 ms. That experiment had not been deployed. The requirement is a report in seconds without buying infrastructure.

## Decision

Permanently replace the customer-month expansion with one reusable twelve-key JSON template overlaid with observed monthly amounts, and materialize eligible orders once per statement. Keep ordinary live views and the six original primary-key indexes; verify exact output equality and measure complete execution plans.

## Alternatives considered

### Alternative A: Add reporting indexes immediately

- **How it would work:** Index status, order date or customer for this report.
- **Why it is attractive:** May help selective queries.
- **Why rejected:** This report processes most customers and completed orders; the measured avoidable work is intermediate row expansion. No controlled evidence justifies added write/storage cost.

### Alternative B: Persist a materialized report

- **How it would work:** Cache the complete customer report and refresh on a schedule.
- **Why it is attractive:** Could make repeated reads very fast.
- **Why rejected:** Adds stale-data and refresh operations when an ordinary optimized view already meets the local seconds budget.

### Alternative C: Increase server memory or work_mem globally

- **How it would work:** Allocate more resources to avoid spills.
- **Why it is attractive:** May reduce temporary disk work.
- **Why rejected:** No production bottleneck has been reproduced; memory multiplies across concurrent operations. SQL simplification should be measured first.

## Consequences

- **What this buys:** Equivalent live output with less intermediate work. Both EXCEPT ALL directions are empty. Raw final plans and three-run times are preserved in tests/final_plans.txt and tests/final_performance.json.
- **What this costs:** The MATERIALIZED CTE is per-query work, not a persistent cache; it can spill. Sorting/ranking and monthly aggregation still consume CPU, memory and temporary storage.
- **What it costs the client if I am wrong:** If equality were wrong, customer totals or ranks could change; if production differs, capacity or latency could remain inadequate.
- **What would make me revisit this:** Sustained production latency, a different data distribution, frequent selective lookups, or material growth would justify remeasurement and targeted indexes or refresh design.

## What this survives

Survives full-data semantic comparison, zero months, ties and reinstallation. The previous experiment showed a 15,400 KB external sort and five-batch hash aggregation; final-plan spills are reported honestly in docs/performance_report.md. Local timings do not turn Nana's reported forty minutes into a measured production speedup. No planner settings or extra indexes were introduced.
