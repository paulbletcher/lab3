# Memo to Nana

**From:** Kloud Kart project implementer  
**Date:** 2026-11-27  
**Subject:** Safer sales, clearer spending and stock visibility

## What I found

Fourteen products have negative stock. For 1,624 completed orders, recorded totals differ from complete item amounts; 144 completed orders lack customer records. These counts overlap and do not establish losses. Historical records were preserved for investigation.

## What I built

| What you asked for | Status | Evidence |
|---|---|---|
| Prevent selling the same last unit twice | Correct in tested cases; speed target outstanding | 25 last-unit races passed; 400 buyers produced 50 purchases, 350 refusals and no errors in each of three runs |
| Keep a movement trail | Tested | Five competing purchases produced five movement records; failed purchases left no partial records |
| Faster weekly spending report | Tested locally | Every customer included; latest median 1.516 seconds versus 2.464 seconds for the original calculation on the same test data |
| Stock visibility through categories | Tested locally | Latest median 0.014 seconds; deep categories and broken links checked |
| Additional help with unreliable orders | Built and tested | Recurring review list: 1,863 flags covering 1,861 orders |

## What I recommend

Reconcile the fourteen negative balances against physical stock. Give Finance and Ops ownership of the order review list and verify original charges before correcting amounts. Use the protected sales and stock-adjustment routes.

Measure checkout on the live workload before the flash sale: the selected version achieved 9.29, 7.98 and 7.54 seconds in three trials, but final confirmation took 19.62 seconds. The ten-second goal remains unreliable. Defer a bigger server decision: the measured reports already finish in seconds, and these tests have not reproduced the reported forty-minute delay.

## What I could not stand behind

Recorded spending is not verified cash received. Missing prices, customer links and category assignments still need source evidence. The supplied stock history has no recent sales and contains future records, so I cannot justify a current stockout forecast or supplier delivery estimate. Local simulations do not prove live capacity or consistent response times.
