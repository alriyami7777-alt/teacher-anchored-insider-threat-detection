# EDITOR-017 paper handover

These are controlled degraded-input / data-quality experiments.
Do not describe any EDITOR-017 result as adversarial robustness, evasion resistance, or poisoning resistance.

## Frozen clean interpretation (preserved)

- TEACHER_GUIDANCE_VS_INITIALISATION = SUPPORTED_STRONG
- ROUTE_ANCHOR_INCREMENTAL_PREDICTIVE_EFFECT = NOT_SUPPORTED
- ODST_PREDICTIVE_SUPERIORITY_OVER_LINEAR = NOT_SUPPORTED
- GLOBAL_TOPK_PR_AUC_FAITHFULNESS = NOT_SUPPORTED
- ROUTE_TRACEABILITY = SUPPORTED
- LEAF_TRACEABILITY = SUPPORTED

## Clean validation PR-AUC (seed mean)

- C2-OPT = 0.935331
- F10 = 0.942606
- TA2 = 0.942846
- L1 = 0.938893

## Controlled source-channel ablation

- C2 MEAN_SOURCE_DELTA = -0.409960
- F10 MEAN_SOURCE_DELTA = -0.387063
- TA2 MEAN_SOURCE_DELTA = -0.385313
- L1 MEAN_SOURCE_DELTA = -0.397705
- TA2 worst source = file (-0.898904)

## Controlled Gaussian input noise

- C2 MEAN_NOISE_RETENTION = 0.920903
- F10 MEAN_NOISE_RETENTION = 0.930087
- TA2 MEAN_NOISE_RETENTION = 0.935592
- L1 MEAN_NOISE_RETENTION = 0.925825

## Structural / explanation

- F10 clean teacher-relative route MAE = 0.007548
- TA2 clean teacher-relative route MAE = 0.002416
- ROUTE_ANCHOR_STRUCTURAL_ROBUSTNESS = SUPPORTED
- LOCAL_DIRECTIONAL_TREE_FAITHFULNESS = SUPPORTED
- TREE_EXPLANATION_DEGRADED_INPUT_STABILITY = SUPPORTED
- TA2 directional positive seeds = 3/3

## Final robustness gates

- TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE = CONSISTENT
- ODST_DEGRADED_INPUT_ADVANTAGE_OVER_LINEAR = CONSISTENT

## Why teacher guidance

Equal-weight ensemble teacher guidance (F10 versus C2-OPT) reduces mean source-channel PR-AUC loss and raises Gaussian-noise PR-AUC retention. The source-family user-cluster CI excludes zero; the noise-family CI includes zero. That is a CONSISTENT degraded-input value, not STRONG. It does not overwrite the frozen clean claim TEACHER_GUIDANCE_VS_INITIALISATION = SUPPORTED_STRONG.

## Why route anchoring

Route anchoring (TA2 versus F10) does not materially change clean or degraded predictive ranking. It does keep teacher-relative ODST routing closer to matched T-OPT under both perturbation families, and it slightly stabilises signed tree-contribution vectors. Treat this as structural / explanation resilience, not a predictive increment.

## Why ODST

Clean PR-AUC superiority over the matched teacher-guided linear model remains NOT_SUPPORTED. Under controlled degraded input, TA2 is directionally more resilient than L1 in both families, but only the noise-family CI excludes zero. That is CONSISTENT degraded-input advantage, separate from clean superiority. File and device channel ablation collapse all four models.

## Next recommended action

Write the paper around three separated claims: teacher guidance as the predictive and degraded-input story; route anchoring as teacher-relative routing and explanation stability; ODST versus linear as a qualified data-quality consistency result. Do not claim adversarial, evasion, or poisoning robustness. Do not reopen r5.2 TEST.

## Claim separation

Keep local directional faithfulness, degraded-input explanation stability, route traceability, leaf traceability, and the negative global top-k PR-AUC faithfulness result as separate claims. Do not merge them into "ODST is faithful".
