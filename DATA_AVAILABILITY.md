# Data Availability

The CERT insider-threat datasets are not redistributed in this repository.

Users must obtain the relevant CERT releases separately and comply with the applicable access and use conditions.

## Prohibited repository content

The following must not be committed:

- raw CERT event files;
- processed user-level datasets;
- answer packages or insider identity files;
- model checkpoints (one exception: the three seed-42 checkpoints in `revision_r2/holdout/checkpoints_seed42/`, published on 23 October 2026 so the unseen-user result can be checked; they contain weights, settings and thresholds only);
- large tensor, prediction, or cache files;
- credentials or tokens;
- absolute local file paths;
- personal or organisationally sensitive material.

## Expected local arrangement

Repository code should accept data locations through configuration files or environment variables. Scripts must not depend on hard-coded paths such as `C:\PhD\...`.

Example environment variable names:

```text
CERT_R42_ROOT
CERT_R52_ROOT
CERT_R62_ROOT
PAPER_OUTPUT_ROOT
```

Only aggregated, disclosure-reviewed tables and figures should be placed in `results/`.
