# EDITOR-020 paper rescue handover

BEST_CURRENT_PAPER_MODEL = TA2

TEACHER_GUIDED_ROBUSTNESS_TRAINING = CONSISTENT

ODST_ROBUSTNESS_SUPERIORITY_OVER_LINEAR = NOT_SUPPORTED

ROUTE_ANCHOR_ROBUST_TRAINING_VALUE = NOT_SUPPORTED

ROBUST_TA2_CLEAN_PREDICTIVE_SUPERIORITY = NOT_SUPPORTED

WHY_TEACHER_GUIDANCE

R3 and R1 see the same degraded training examples; the only added term in R3 is clean-teacher ensemble logit consistency on the degraded student view.

WHY_ODST

Degraded-input superiority is assessed against a matched robustness-trained attention-linear model, not against ordinary clean L1, and is not a clean predictive-superiority claim.

WHY_ROUTE_ANCHORING

TA2-R4 versus TA2-R3 isolates robust route consistency: student routes on degraded input are pulled toward the matched clean T-OPT route.

NEXT_RECOMMENDED_ACTION

Do not replace clean TA2 with a robustness-trained student. The frozen clean-preservation gate blocked every robustness objective. A future authorised experiment may keep clean teacher logit MSE as architecture identity while adding degraded terms, but EDITOR-020 does not change lambdas after seeing results.
