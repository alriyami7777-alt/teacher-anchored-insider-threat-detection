# Artefact Inventory and Provenance Register

## Generated inventory

`PAPER_ARTIFACT_INVENTORY.generated.csv` is produced automatically from the
versioned LaTeX manuscript. It records figures and tables detected in the
current manuscript checkpoint.

This file may be regenerated and overwritten.

## Curated register

`PAPER_ARTIFACT_REGISTER.csv` is the authoritative paper-facing provenance
register. It is initially seeded from the generated inventory, then enriched
manually with:

- producing project and worktree;
- frozen branch and commit;
- producing configuration or run;
- canonical saved output;
- evidence role;
- verification status;
- claim-to-evidence qualification;
- canonical SHA-256 hash.

The automatic inventory script must never overwrite the curated register.

## Manuscript timing

The current inventory represents the versioned Overleaf checkpoint in GitHub,
not unpublished edits still being made in the live Overleaf project.
