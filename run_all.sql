-- Kloud Kart DE03 SQL Lab
-- Master execution script.
-- Run against a freshly loaded database.
-- Does not drop existing tables or reload historical data.

\set ON_ERROR_STOP on

-- Phase 0: Environment verification
\echo 'Phase 0: Environment verification'
\ir setup_checks.sql

-- Phase 1: Data integrity diagnosis
\echo 'Phase 1: Data integrity diagnosis'
\ir integrity_checks.sql

-- Phase 2: Transactional checkout
-- Implementation pending.

-- Phase 3: Inventory auditing
-- Implementation pending.

-- Phase 4: Customer-spending report
-- Implementation pending.

-- Phase 5: Recursive low-stock report
-- Implementation pending.

-- Phase 6: Performance optimization
-- Implementation pending.

-- Phase 7: Additional improvement
-- Implementation pending.

-- Phase 8: Final verification
-- Implementation pending.

\echo 'All configured scripts completed successfully.'