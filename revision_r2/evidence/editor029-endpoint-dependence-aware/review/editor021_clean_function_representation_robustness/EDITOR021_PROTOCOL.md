# EDITOR-021 protocol freeze

Result-blind freeze. No EDITOR-021 predictive result has been observed.

Parent commit: `c26e7291c077dd2626544701217201016c27194d`

## Architecture

TA2: 20-day × 13-feature → Bi-LSTM → temporal attention → attention-pooled `h(x)` → ODST-046 → logit.

Starting hash-gated F11/TA2 checkpoints:
- seed 42: `54f6c097af9568a4ee5701ef375559a2f649cec6c1817e578d3e8e01e6d73df8`
- seed 52: `7613ba559bcf55827d04129066eb595b677994494609646f8b2463308ed5edb4`
- seed 62: `904003dca219435464476cf36abedb11ee4e2f7a11ff09caa3791d685b8f644d`

## Objectives

- `L_TA2 = L_task + 0.5 L_teacher + 0.5 L_route`
- `L_FP = MSE(z_S(x), stopgrad(z_Fref(x)))` with `LAMBDA_FP = 1.0`
- `L_clean = L_TA2 + L_FP`
- `L_repr = 1 - cos(h_S(x_tilde), stopgrad(h_Fref(x)))`

`L_repr` is not applied to ODST/head parameters. CFP0 has `rho = 0` and no representation gradient.

## Gradient geometry

- projection: `g_r_perp = g_r - ((g_c · g_r) / (|g_c|_2^2 + eps)) g_c  if (g_c · g_r) < 0 else g_r`
- budget: `alpha = min(1, rho |g_c|_2 / (|g_r_perp|_2 + eps)); g_enc = g_c + alpha g_r_perp; g_odst = g_c`
- rho search: 0.10 / 0.25 / 0.50 only

## Gates

- CFP0 scaffold vs starting TA2 INNER_SELECT: mean delta >= -0.001 and no seed < -0.003
- INNER G1–G5 versus matched CFP0
- Official O1–O6 only for the one automatically selected CFPR

## Perturbations

- source: `dc83b14cbf27822f86b1626032c5947ac79aa55c264b0a2c524ca44c9e1b07c2`
- gaussian: `bcab265042f6b6363d6bc7245d5a0bf6d177d2fcb75528a124978f04d8d9bb1f`
- scaler: `6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488`

## Deny-list

r5.2 TEST, CERT r5.1, CERT r6.2, adversarial/evasion/poisoning claims.

## Producing pins

- architecture `9867b0c266f3b735d138e2d8d53f0d3f5c5c644e25302c10c25e2f4677560abd`
- odst `95764ce80a7c80529108d8d6b72f6bd06896c39d065f7e475c12dce8421417bb`
- sequence_ensemble `43f16bce9c09305c7578d319dadf4c23c6c18cbe70fd7dcc1fda0114c86d6475`
