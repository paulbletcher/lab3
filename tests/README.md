# Test and evidence guide

The submission entry points are `final_verification.py` and `check_submission.py`.
`race_test.py` at the repository root is the unchanged official harness.

`phase3/backups/`, `phase2/logs/` and `phase3/logs/` are historical evidence only.
Do not execute backup or experiment SQL as installation scripts. Install with
`run_all.sql`; rejected and slow runs are deliberately preserved.

Current flash-sale evidence is `phase3/logs/flash_final_selected.json`; it includes
the 19.62-second final confirmation. No consistent ten-second guarantee is made.
