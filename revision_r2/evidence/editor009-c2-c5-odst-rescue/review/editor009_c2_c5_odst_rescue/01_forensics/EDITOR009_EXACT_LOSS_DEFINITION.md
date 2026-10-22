# EDITOR-009 Exact Loss Definition

Campaign: EDITOR-009 DEVELOPMENT RESCUE

Producing implementation (not manuscript prose):

- C5_original_paper trainer: `cert-r52-teacher-anchored-reproducibility/scripts/objective2_teacher_anchored_odst/train.py` + `models.py`
- C2 / C3 / C4 / C6 trainer: `cert-r42-feasibility/scripts/objective2_teacher_anchored_odst/train.py` + `models.py` (accepts `w_logit`, `w_route`)

## Equation

```
L_total = L_task + λ_logit * L_logit + λ_route * L_route
```

C2: λ_logit = 0, λ_route = 0
C5_original_paper: λ_logit = 0.5, λ_route = 0.5 (static)

### L_task

- file: producing `train.py` (`nn.BCEWithLogitsLoss`)
- reduction: mean over batch windows
- class weighting: `pos_weight = (n_neg / n_pos) * 0.25` from TRAIN only
- student parameters affected: encoder, attention, ODST (linear_head frozen)

### L_logit

- file: producing `models.py` `logit_consistency_loss`
- formula: mean((s − stopgrad(t))²) / (var_unbiasedFalse(stopgrad(t)) + 1e-6)
- reduction: mean over batch windows
- teacher detach: YES
- schedule: STATIC 0.5 for C5; 0 for C2
- class weighting: none
- masking: none

### L_route

- file: producing `models.py` `route_consistency_loss`
- formula: mean Bernoulli KL over all (window, tree-index, depth) elements
- ROUTE_INDEX_IDENTITY_ASSUMED = YES (raw concatenated tree index)
- teacher detach: YES
- schedule: STATIC 0.5 for C5; 0 for C2
- class weighting: none
- masking: none

LOGIT_ANCHOR_WEIGHT_STATIC = YES
ROUTE_ANCHOR_WEIGHT_STATIC = YES

The constant C5 penalty remains active through the last epoch, so late supervised departure from the teacher is penalised at the same absolute weight as epoch 1.
