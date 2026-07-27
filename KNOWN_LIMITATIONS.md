# Known Limitations

1. The final teacher-anchored student must not be described as independently validated on a dataset or split unless that exact evaluation has been completed and locked.
2. CERT r5.2 one-pass test evidence applies to the eligible baselines and frozen-encoder comparator under the recorded protocol.
3. Teacher-anchored r5.2 results currently represent train/validation reproducibility evidence.
4. Reference-centred ODST explanation evidence is supported with sensitivity limits; raw-ranking results are retained as a negative or qualified finding.
5. Missing-source experiments are source-channel ablations and do not reproduce every operational consequence of unavailable event sources.
6. Runtime does not scale directly with ODST tree count under the current implementation.
7. CERT r6.2 work through Stage 1F is a model-free readiness and provenance audit, not a model-performance result.
8. Dataset-specific feature and source dependencies limit direct generalisation across CERT releases.
