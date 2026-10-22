# EDITOR-016 paper rescue handover

Full-system superiority: **NOT_SUPPORTED**
ODST specialist incremental value: **NOT_SUPPORTED**
Teacher-guidance specialist effect: **NOT_SUPPORTED**
Routed local directional faithfulness: **NOT_SUPPORTED**
Historical global top-k faithfulness: **NOT_SUPPORTED** (frozen)
Best current paper model: **TA2**

Why teacher guidance: Equal-weight ensemble residual guidance remains the only intervention with supported global predictive value. On INNER_SELECT it also improved the ODST specialist over matched task-only ODST at every frozen q, but that inner effect was not promoted because it did not produce ODST-specific value over a matched linear specialist.

Why ODST: The uncertainty-routed ODST specialist did not beat the matched teacher-guided linear specialist, nor the frozen L1 base, on whole-system INNER_SELECT PR-AUC at any predeclared coverage. No configuration was promoted to official validation.

Next recommended action: Keep TA2 as BEST_CURRENT_PAPER_MODEL. Do not launch another generic ODST search.

Do not convert routed directional faithfulness into a global PR-AUC faithfulness claim.
