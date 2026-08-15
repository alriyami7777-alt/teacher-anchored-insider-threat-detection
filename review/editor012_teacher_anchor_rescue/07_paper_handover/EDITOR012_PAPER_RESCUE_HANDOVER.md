# EDITOR-012 paper rescue handover

Teacher-guidance predictive effect: **SUPPORTED_STRONG**
Paper rescue gate: **TEACHER_GUIDANCE_RESCUE_CONFIRMED**

F00 C2-OPT mean PR-AUC = 0.935324
F10 D-OPT mean PR-AUC = 0.942595
F01 R2-OPT mean PR-AUC = 0.937496
F11 DR-OPT mean PR-AUC = 0.942842

Best repaired condition: F11_DROPT (TA2 = ODST-046 + ET1 ensemble distill + route λ=0.5)
Δ vs matched C2 = 0.007518 (3/3 primary seeds)
User-cluster 95% CI (F11−F00) = [0.000345, 0.018250]
User-cluster 95% CI (F10−F00) = [0.000357, 0.017391]
Extended 10-seed panel = 9/10 positive; mean Δ = 0.006157

Route fidelity: F11 restores teacher-relative routes versus F10 (MAE 0.002415 vs 0.007547) with negligible predictive increment (Δ F11−F10 = +0.000247; CI includes 0). Route anchoring is a structural-fidelity regulariser, not the predictive mechanism.

Historical C5 remains the original dual-anchor formulation. TA2 is a distinct repaired identifier.

Freeze TA2 as the repaired teacher-anchored formulation and wait for authorised final-test strategy.
