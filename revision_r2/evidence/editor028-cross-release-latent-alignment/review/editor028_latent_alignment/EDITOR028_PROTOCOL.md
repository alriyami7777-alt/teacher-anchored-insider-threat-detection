# EDITOR-028 PROTOCOL

Frozen before teacher/student training. No architecture search. No lambda search.

- Parent SHA: `c491b79c2f552318ff3993e585a7abd3d2d7857b`
- Intervention: `TRAINING-TIME LATENT COVARIANCE ALIGNMENT`
- Architecture change: `NO`
- Reader-facing student: `final ensemble-guided, route-anchored student`
- ODST: `Oblivious Differentiable Sparsemax Tree`
- CORAL: `CORrelation ALignment`

## Base input representation

- Exact EDITOR-026 centred user-relative transform.
- Lookback = 20 calendar days.
- Volume: `log1p(current) - median(log1p(past same-user calendar days))`
- Binary: `current - mean(past same-user calendar days)`
- Do not use EDITOR-027 scale normalisation.
- Output remains 20 x 13. No release/domain/user embedding.

## Architecture

- 20 x 13 sequence → Bi-LSTM → temporal attention → attention-pooled representation → ODST → binary prediction.
- ODST-046 trees=4 depth=4. Hidden size 64. No Transformer, CNN, domain classifier, or new head.

## Teachers

- Representation-matched attention-linear then T-OPT on r5.2 only.
- Producing files: `editor026_user_relative.train.train_attention_linear` and `train_ur_teacher`.
- Internal identifiers: ['CENTERED_TEACHER_42', 'CENTERED_TEACHER_52', 'CENTERED_TEACHER_62'].

## Student objective

- L_base = L_task + 0.5 L_teacher + 0.5 L_route.
- Aligned candidates add lambda_CORAL * L_CORAL on the attention-pooled representation.
- L_CORAL = ||C_s - C_t||_F^2 / (4 d^2). Batches smaller than 2 contribute 0.

## Candidates and seeds

- ALIGN0 lambda=0.00: matched user-relative centred final model without latent alignment
- ALIGN01 lambda=0.01: centred final model with latent CORAL weight 0.01
- ALIGN05 lambda=0.05: centred final model with latent CORAL weight 0.05
- ALIGN10 lambda=0.10: centred final model with latent CORAL weight 0.10
- Seeds exactly: [42, 52, 62]
- Source batch order matched across candidates. Target batch order matched across aligned candidates.
- Target sampling is uniform and outcome-independent. r6.1 labels are inaccessible during training.

## Label-blind selection

- S1 mean r5.2 PR-AUC >= 0.9353238885175368
- S2 at least 2/3 seeds >= 0.93
- S3 candidate - ALIGN0 >= -0.002
- S4 alignment reduction A >= 0.3
- S5 at least 2/3 seeds lower CORAL discrepancy than ALIGN0
- S6 mean source-separation retention >= 0.9
- If none pass: do not open r6.1 labels.

## r6.1 evaluation and promotion

- Primary metric PR-AUC. Prevalence lift >= 10.0. User-cluster bootstrap 2000/seed 42.
- Promotion requires S1-S6 and R1-R9 on both label views.
- If promotion is NO, MODEL_RESCUE_PROGRAMME = CLOSED. Do not create EDITOR-029.
- Historical EDITOR-024–027 results are immutable. r6.1 cannot serve as a future untouched target.

Written at 2026-08-24T05:14:27Z.
