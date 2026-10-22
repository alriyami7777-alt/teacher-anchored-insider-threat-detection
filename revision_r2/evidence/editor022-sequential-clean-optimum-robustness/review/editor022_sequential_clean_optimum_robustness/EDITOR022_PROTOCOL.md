# EDITOR-022 protocol freeze

Result-blind freeze. No EDITOR-022 predictive result has been observed.

Parent commit: `b41944b3b67518eb1afc69b17450eeef29f5b8f7`
EDITOR021_RESULTS_COMMIT: `b3d5ef1e57299bd019fdd482e95ccdc44dfc165e`
EDITOR021P1_CORRECTION_COMMIT: `b41944b3b67518eb1afc69b17450eeef29f5b8f7`
EDITOR021_PROTOCOL_COMMIT: `a1e7825c1f11bfe36595ef28c197c7a105685aaf`

This is one unified experiment. It is not EDITOR-022A/B/C.

## Frozen CFP0 Stage-1 starting checkpoints

- seed 42: `outputs/editor021_clean_function_representation_robustness/CFP0/seed42/best.pt` sha256=`af47cebd144c7f3c2aac2c71697f726242b7fbb17f9d6fc1126449096910a438`
- seed 52: `outputs/editor021_clean_function_representation_robustness/CFP0/seed52/best.pt` sha256=`3a06349cdb872840a51b87711e5b49f57498e499780d4930738d3c4a6ad8fa25`
- seed 62: `outputs/editor021_clean_function_representation_robustness/CFP0/seed62/best.pt` sha256=`ce153b2b379195b40aa96984cc0c3d9fb96bb86bbf3f5d6cbf0b9fa5b1218a5c`

Do not recreate these INNER_SELECT checkpoints.

## Frozen CFP0_START metrics

- mean clean PR-AUC `0.9575902800558067`
- mean S_source `-0.39657911984842825`
- mean S_noise `-0.10660614343516985`
- mean S_composite `-0.25159263164179907`
- parity tolerance `1e-10`

## Architecture

TA2 = 20x13 -> Bi-LSTM -> temporal attention -> attention-pooled h -> ODST-046 -> binary logit

## Stage-2 candidates

- SEQ0 rho=0.000 robustness=OFF
- SRP025 rho=0.025 robustness=ON
- SRP050 rho=0.050 robustness=ON
- SRP100 rho=0.100 robustness=ON

STAGE2_EPOCHS = 1. End-of-epoch checkpoint only. No early stopping. No best-epoch selection.

FRESH_STAGE2_OPTIMISER = YES. OPTIMISER_STATE_CONTINUED_FROM_CFP0 = NO.

SAMPLER_EPOCH_INDEX = 1.

## Objectives

- `L_clean = L_task + 0.5 L_teacher + 0.5 L_route + 1.0 L_FP`
- `MSE(z_S(x), stopgrad[z_F_CFP0(x)])`
- `1 - cos(h_S(x_tilde), stopgrad[h_F_CFP0(x)])`

The frozen CFP0 reference is F_CFP0. It does not replace T-OPT.

## Gradient geometry

- projection: `g_r_perp = g_r - ((g_c · g_r) / (|g_c|_2^2 + eps)) g_c  if (g_c · g_r) < 0 else g_r`
- budget: `alpha = min(1, rho |g_c|_2 / (|g_r_perp|_2 + eps)); g_enc = g_c + alpha g_r_perp; g_odst = g_c`
- ODST/head receives clean gradient only

## Gates

- SEQ0 scaffold vs CFP0_START: mean delta >= -0.001 and no seed < -0.003
- INNER G1–G6 versus CFP0_START, with G6 versus SEQ0
- Official O1–O7 only for the one automatically selected SRP

## Selection rule

G1-G6 then greatest S_composite; tie <=0.001 chooses smaller rho

## Official validation rule

O1-O7 on selected SRP vs CFP0_FULL_START and SEQ0_FULL

Validation Stage V1 trains inherited CFP0_FULL from historical TA2 on full r5.2 TRAIN.
Stage V2 then applies one matched SEQ0_FULL / SELECTED_SRP_FULL epoch from frozen CFP0_FULL.

Frozen INNER CFP0 thresholds: seed 42 = 0.89, seed 52 = 0.85, seed 62 = 0.85.

## Perturbations

- source: `dc83b14cbf27822f86b1626032c5947ac79aa55c264b0a2c524ca44c9e1b07c2`
- gaussian: `bcab265042f6b6363d6bc7245d5a0bf6d177d2fcb75528a124978f04d8d9bb1f`
- scaler: `6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488`

## Split identity

- train `b268328d3bf2e98f712d1145958dabe175ce2c07a7c390da4b84a663317ebc2e`
- validation `5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c`
- user mapping `851385f9c926cf945b3c74b5c9442e3ccb94cf1d9dabb98106a29cbfea01c5c0`
- seeds `[42, 52, 62]`

## Deny-list

r5.2 TEST, CERT r5.1, CERT r6.2, target-domain fit, new perturbations, new architecture,
EDITOR022B/C, EDITOR-023 robustness rescue, post-result rho/epoch/LR search.

## Historical artefacts

EDITOR-021 review and output directories are read-only to EDITOR-022.

## Result-freeze procedure

1. write all scientific result artefacts
2. write completed EDITOR022_RUN_MANIFEST.json
3. write EDITOR022_RESULT_FREEZE.md
4. write EDITOR022_TERMINAL_BLOCK.txt
5. compute hashes of all final stable hash-target artefacts
6. write EDITOR022_SHA256_MANIFEST.json LAST

The SHA manifest must not hash itself. Nothing listed in it may be modified afterwards.

## Producing pins

- architecture `9867b0c266f3b735d138e2d8d53f0d3f5c5c644e25302c10c25e2f4677560abd`
- odst `95764ce80a7c80529108d8d6b72f6bd06896c39d065f7e475c12dce8421417bb`
- sequence_ensemble `43f16bce9c09305c7578d319dadf4c23c6c18cbe70fd7dcc1fda0114c86d6475`
