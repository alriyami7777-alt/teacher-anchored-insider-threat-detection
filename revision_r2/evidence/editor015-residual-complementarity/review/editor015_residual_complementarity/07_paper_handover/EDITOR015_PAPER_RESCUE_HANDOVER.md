# EDITOR-015 paper rescue handover

Residual ODST value: **NO_RESIDUAL_ODST_VALUE**
Fixed L1+TA2 complementarity: **MIXED**
Local directional faithfulness: **SUPPORTED**
Historical global top-k faithfulness: **NOT_SUPPORTED** (frozen)
Best current paper model: **TA2**

Why teacher guidance: Equal-weight ensemble logit guidance remains the only intervention with a supported predictive increment over matched task-only training; residual experiments inherit that L1 base.

Why ODST: Neither the function-preserving residual nor a fixed L1+TA2 combination established reproducible incremental ranking value over the matched teacher-guided linear base.

Next recommended action: Keep TA2 as BEST_CURRENT_PAPER_MODEL. Do not launch another generic ODST search.

Do not convert local directional faithfulness into a global PR-AUC faithfulness claim.
