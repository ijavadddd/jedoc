# PRD — Reservation service for a 10M-user drop

## Problem
A product drop sells out in seconds. Buyers double-click, clients retry, and the inventory row for the popular SKU becomes a lock hotspot. Oversell is not acceptable. A slow "you are in line" page is acceptable; a wrong "you got it" is not.

## Users
- Shoppers hammering a single SKU.
- The inventory service, which is the only writer of available quantity.
- Support staff, who need a stable idempotency key to explain a retried purchase.

## Must ship
1. Reserve N units of a SKU only when the available quantity covers N at write time.
2. Retries with the same idempotency key return the original decision and do not decrement twice.
3. A conflicting reserve returns a clear conflict, not a 500 and not a silent success.
4. Quantities and money are exact integers.
5. The hot path does not depend on a single global counter row shared by every SKU.

## Must not ship in this slice
- Cross-region multi-master inventory.
- A recommendation engine.
- A generic plugin marketplace.

## Scale
- 10 million accounts.
- Peak 50,000 reservation attempts per second against a small set of hot SKUs.
- p99 decision latency under 150ms inside the datacenter.
- Zero oversells in a 10-minute sustained test.

## Notes for the architect
Look for read-modify-write, N+1 availability checks, unbounded offset pagination, and any design that updates one celebrity row for every buyer. Propose a partition and a conditional update. Write the testable contract the TDD node should lock before implementation.
