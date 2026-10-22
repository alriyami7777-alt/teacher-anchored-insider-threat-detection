# EDITOR-013 paper rescue handover

ODST incremental value: **NO_INCREMENTAL_ODST_VALUE**
Teacher consensus: **MIXED**
Teacher guidance vs initialisation: **SUPPORTED_STRONG**

Matched teacher-guided linear (L1) mean PR-AUC = 0.938881
TA2 mean PR-AUC = 0.942842
Best ODST/hybrid (TA2) mean PR-AUC = 0.942842
Δ vs L1 = 0.003961
User-cluster 95% CI = [-0.0013708139376007687, 0.011356265117941461]

Why teacher anchoring: TA2 already established that equal-weight ensemble logit distillation plus optional route anchoring improves ranking beyond matched T-OPT initialisation (mean Δ vs C2-OPT = +0.007518; SUPPORTED_STRONG).

Why ODST: Under a matched teacher-guided linear control, ODST did not provide a reproducible predictive increment. Route/leaf traceability remains, but the paper cannot claim standalone ODST superiority over the simpler linear head.

Best current paper model: **TA2**

Next recommended action: Keep TA2 as the paper's teacher-anchored ODST model. Report honestly that a matched teacher-guided linear head is close (mean Δ TA2−L1 = +0.003961; 2/3 seeds; user-cluster CI includes 0) and that learned tree weighting / residual fusion did not create inner-select headroom. Do not open r5.2 TEST. Do not rerun r5.1 or r6.2.
