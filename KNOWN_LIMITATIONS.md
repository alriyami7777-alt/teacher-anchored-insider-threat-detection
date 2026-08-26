# Known Limitations

1. The final teacher-guided, route-regularised ODST must not be described as independently validated on a dataset or split unless that exact evaluation has been completed and locked.
2. CERT r5.2 one-pass test evidence applies to the eligible baselines and the frozen-encoder comparator under the recorded protocol. It is historical guarded-reference evidence and must not be assigned to the final model.
3. The current CERT r5.2 evidence for the final model is train/validation evidence.
4. Explanation evidence is bounded. The local signed reference-centred tree-contribution intervention is supported. Routes, reached leaves, tree outputs and memberships are traceable internal evidence only. General global top-k tree-ranking faithfulness is not supported.
5. Missing-source and Gaussian-noise experiments are controlled degraded-input and data-quality sensitivity analyses. They are not adversarial, evasion or poisoning robustness experiments, and they do not reproduce every operational consequence of unavailable event sources.
6. Runtime does not scale directly with ODST tree count under the current implementation.
7. CERT r6.2 is outside the current IEEE Access manuscript. The r6.2 work through Stage 1F was a model-free readiness and provenance audit, not a model-performance result, and is retained as historical material only.
8. Dataset-specific feature and source dependencies limit direct generalisation across CERT releases. The prospectively reserved CERT r6.1 cross-release evaluation did not support ranking transfer of the final model.
9. CERT r5.2 temporal partitions contain the same users, so the reported evidence does not test entirely unseen-user generalisation.
10. Endpoint-defined evaluation supports end-of-day detection and assessment. It does not establish causal detection, pre-event forecasting, or real-time intra-day prediction.
11. Overlapping sequence windows are correlated observations. De-overlapped analysis retains the principal ranking signal, but component-level contrasts become less certain.
