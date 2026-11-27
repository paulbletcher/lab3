# ADR-005: Traverse categories with cycle protection and no fixed depth cap

- **Status:** Accepted
- **Date:** 2026-11-27
- **Decision owner:** Kloud Kart DE03 implementer

## Context

The actual tree reaches four levels but marketing can add more. Two categories form a cycle, one has a missing parent and 37 products have no category. The previous implementation stopped at level 20, contrary to the requirement not to hard-code depth.

## Decision

Use recursive CTEs with PostgreSQL CYCLE protection, removing the level-20 predicates while preserving the existing view interfaces. Count distinct low-stock products (stock <= 10) in reachable subtrees, and expose unreachable categories, missing assignments and NULL stock through a separate exception view.

## Alternatives considered

### Alternative A: Fixed-depth joins or a twenty-level cutoff

- **How it would work:** Join a preset number of levels or stop recursion after twenty.
- **Why it is attractive:** Bounds traversal work and appears sufficient for current data.
- **Why rejected:** Silently omits valid deeper descendants; a 35-level test demonstrates why current depth is not a contract.

### Alternative B: Recursion without cycle detection

- **How it would work:** Follow every parent-child edge without remembering the path.
- **Why it is attractive:** Shorter query.
- **Why rejected:** A disconnected cycle can prevent all-start traversal from terminating.

### Alternative C: Repair or flatten categories before reporting

- **How it would work:** Rewrite missing parents and cycle links or store a closure table.
- **Why it is attractive:** Could simplify reads after a full catalog redesign.
- **Why rejected:** Intended assignments are unknown and changes would rewrite history; current local rollup is already fast.

## Consequences

- **What this buys:** Depth-independent traversal, deterministic termination on cycles, explicit exclusions and no double counting within a subtree. Actual root total reconciles to 1,931 reachable low-stock products.
- **What this costs:** Products in disconnected categories are excluded from valid-root totals and require exception review. Ancestor counts overlap by design and must not be summed across all levels.
- **What it costs the client if I am wrong:** Hidden replenishment needs if exception rows are ignored or legitimate products are attached to the wrong category.
- **What would make me revisit this:** Very large or unusually deep catalogs, slow measured traversal, changed threshold rules or corrected catalog structure warrants review.

## What this survives

Survives a 35-level tree, two-node and self cycles, orphan categories/products, uncategorized products, negative/NULL stock, the inclusive threshold and duplicate-path checks in `tests/final_recursive.log`. The compatibility column depth_limit_reached is always false because traversal is no longer artificially truncated. Cycle members are reported separately via report_category_cycles.
