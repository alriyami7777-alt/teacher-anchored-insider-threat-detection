# EDITOR-029 PROTOCOL FREEZE

Task: endpoint-defined and dependence-aware evaluation.
Parent: EDITOR-028 results commit `8d139c67e71cd2d2fca28e98f6214d059a0abc92`.
The model-rescue programme remains closed. The historical paper model remains the final ensemble-guided, route-anchored student (internal identifier TA2).
Endpoint-defined models are sensitivity / editor-closure models and do not automatically replace historical TA2.

## Reader-facing terminology

- C2-OPT: teacher-initialised task-only control.
- F10: ensemble-guided ODST student without route anchoring.
- TA2: final ensemble-guided, route-anchored student.
- L1: matched attention-linear reference.
- ODST: Oblivious Differentiable Sparsemax Tree.
- PR-AUC: area under the precision-recall curve (primary ranking metric).
- EP_C2 / EP_F10 / EP_FINAL / EP_LINEAR: endpoint-defined matched counterparts.

## Part A — de-overlapped sensitivity of frozen r5.2 models

No retraining. Frozen checkpoints for C2-OPT, F10, TA2, and L1 at seeds 42/52/62.
Historical mean r5.2 validation PR-AUC values must reproduce within tolerance 0.0005.
De-overlap masks depend only on user identity, chronological sequence position, and window dates.
Primary view DEOVERLAP_OFFSET0 selects positions 0, 20, 40, ... within each user's ordered windows.
All 20 offsets are sensitivity views, not 20 independent experiments, and must not be pooled as independent observations.
User-cluster bootstrap: sampling unit = user, 2000 valid replicates, seed 42, identical resampled users for matched contrasts.

## Part B — endpoint-defined past-and-current-day task

The model receives the 20 calendar days ending at day d. The target is whether verified malicious activity occurs specifically on endpoint day d.
Malicious activity on d-19 ... d-1 does not make the endpoint label positive.
No day after d enters the input. Bidirectional LSTM processing of the 20-day history is permitted because every represented day is at or before d.
This supports only end-of-day behavioural detection/assessment. It does not support real-time intra-day prediction, pre-event forecasting, or causal intervention.
The original frozen 13-feature representation and historical r5.2 TRAIN scaler are reused. NEW_SCALER_FIT = NO.
Endpoint-matched teachers are reconstructed with the authoritative producing procedure and endpoint labels. Historical teacher outputs are not reused.
Students: EP_C2, EP_F10, EP_FINAL, EP_LINEAR. Seeds 42/52/62. Checkpoint selection uses r5.2 endpoint validation PR-AUC only.

## Claim boundaries

- Same-user temporal partitions: yes. Unseen-user generalisation: not tested.
- Frozen r6.1 conclusion is unchanged.
- Do not interpret any-day PR-AUC minus endpoint-day PR-AUC as a model-effect statistic.
- Do not start EDITOR-030 automatically.
- Do not access r5.2 TEST. Do not rerun r5.1/r6.1/r6.2 inference.

Written at 2026-08-24T14:37:47Z.
