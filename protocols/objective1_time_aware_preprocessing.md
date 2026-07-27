# Objective 1 Protocol: Time-Aware Preprocessing

**Research objective:** Develop time-aware preprocessing that preserves inactivity and behavioural chronology.

**Chapter 3 phase:** Phase 1, data preparation and temporal representation.

## Procedure

1. Audit each authorised event source without modifying raw files.
2. normalise timestamps using the documented release-specific format.
3. Construct a dense daily timeline for each user.
4. Retain inactive days explicitly.
5. Derive the reviewed 13 daily features.
6. Construct 20-day sequences with stride one.
7. Apply chronological per-user boundaries.
8. Reject any sequence crossing a train, validation, or test boundary.
9. Record source counts, matched labels, sequence counts, and data hashes where permitted.

## Completion criterion

The preprocessing stage is complete only when source coverage, chronology, label matching, boundary safety, and sequence counts have been audited.
