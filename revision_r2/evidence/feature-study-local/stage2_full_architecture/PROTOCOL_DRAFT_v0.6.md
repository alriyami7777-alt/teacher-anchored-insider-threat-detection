# Stage 2 — full Bi-LSTM–attention–ODST feature comparison

Prepared: 9 October 2026, Asia/Singapore.

Revision v0.3 responds to Claude audit S2-01 through S2-08 and adds the user-requested safe pause/checkpoint/resume requirement. This is a reviewed-proposal candidate, not execution approval.

Parent revision v0.2: user-directed panel change to F6_PRIMITIVES, F13 and F29. The v0.1 proposal is preserved; no training or architecture change is authorized by this revision.

**Status: REVIEW_DRAFT_NO_TRAINING.** The user requested a separately reviewed second-stage protocol and then explicitly changed its feature panel to 6, 13 and 29. This document proposes the new experiment; it does not authorize fitting, alter the current campaign, or amend the frozen IEEE Access study. Implementation and independent review are still required.

## 1. Recommendation and timing

Prepare and inspect this protocol while Stage 1 runs. Finalize it after Stage 1 completion, recovery accounting and final audit supplements have been reconciled. Then obtain independent review of the protocol and executable implementation before any Stage 2 model fit. Run Stage 2 sequentially after Stage 1 releases the study writer lock.

The questions are whether reducing or expanding daily features changes performance of the complete architecture, and the retrospective performance difference between ensemble-distilled continuation and matched task-only continuation. G-C is exploratory and does not isolate generic guidance from ensemble distillation.

The current attention-linear learner does not answer the full-architecture question. The complete student evaluated here is Bi-LSTM → temporal attention → ODST → binary probability.

## 2. Evidence and historical boundary

Inspected read-only sources are recorded with fresh hashes in `SOURCE_EVIDENCE_v0.3.json`:

- Stage 1 governing `revision_v0.2/PROTOCOL_DRAFT_v0.2.md`, §8, explicitly reserves an ODST extension for a separately reviewed stage and requires feature-matched teachers and task-only/guided controls.
- Stage 1 `INNER_SELECTION.json` identifies S13 as `LOCO_active_duration_minutes` and Splus as `FAM_actions`; its selections used INNER_SELECT, with outer_validation_used=false.
- Historical `EDITOR012_RUN_MANIFEST.json` identifies two ODST layers, four trees per layer, depth four, temperature 0.5, sparsemax feature selection/sigmoid splits and the canonical average of eight tree outputs.
- Historical `editor012_rescue/constants.py`, `models.py`, `losses.py` and `producing.py` describe optimizer groups, matched teacher/student checks, frozen teachers and ET1 equal-weight ensemble logit MSE.
- Producing `prototype_v3_node/architecture.py` and `odst.py` define the actual encoder, attention, ODST forward path and training-data initialization.

These sources establish architecture and loss semantics. They do not establish that a newly trained teacher on changed features reproduces the archived teacher. All newly proposed fits are new-study models. Archived checkpoints, scalers, reports and manuscript evidence remain read-only. No resizing or partial loading of a 13-input archived checkpoint into a different schema is allowed.

Stage 1 outer XGBoost outcomes were already on disk before this panel was fixed, and outer attention outcomes were likely available too. The panel was explicitly requested by the user; independence from available outcomes cannot be independently verified. All Stage 2 VALIDATION results are outcome-exposed retrospective estimates, with no confirmatory or prospective language.

## 3. Three feature sets

Use exactly these existing Stage 1 registered schemas, as requested by the user. F6_PRIMITIVES and F29 are fixed comparison arms; they are not the S13 and Splus subsets selected by the Stage 1 inner rule:

1. **F13 baseline:** the original ordered 13 daily channels.
2. **F6_PRIMITIVES reduced:** six daily primitive channels: logon_count, device_count, file_count, email_count, http_count and active_duration_minutes. Bind their exact ordered columns to the realized schema; this is a registered compact comparator, not an optimized subset.
3. **F29 expanded:** the original 13 channels plus all 16 registered same-day additions. Bind the exact ordered added channels and extraction rules to the realized F29 schema. This is the registered full same-day expansion, not the inner-selected Splus family.

Bind the exact realized ordered column lists and representation hashes to the Stage 1 preflight records. Do not reconstruct them from prose. The added file_write_count and file_to_removable_count channels are identical in the inspected partitions; F29 therefore adds at most 15 distinct signals in 16 extra slots. Disclose this retained duplicate and count nominal channels separately from unique observed signals. Keep it for the proposed matched transfer experiment; deduplicating it would require a different reviewed schema.

S13 and Splus are outside this revised three-set proposal. Adding either would create a fourth arm and require a reviewed budget extension before fitting. The panel is user-directed, not chosen by reranking Stage 1 outer results. A later schema change must be versioned before review and execution.

## 4. Data, labels and preprocessing

Use the existing r5.2 cohort, canonical user/date keys, 20-day completed windows, ANY_DAY_COMPLETED_WINDOW_T20 labels, and fixed INNER_TRAIN, INNER_SELECT, TRAIN and VALIDATION boundaries. Reuse verified Stage 1 daily arrays and labels; perform no additional raw extraction or history-feature expansion.

- INNER_TRAIN: 622,000 windows, 2,457 positives.
- INNER_SELECT: 128,000 windows, 1,214 positives.
- Full TRAIN: 788,000 windows, 3,957 positives.
- VALIDATION: 64,000 windows, 728 positives.
- Exclude the 38,000 inner boundary-crossing windows. Preserve calendar and cohort order.

Neural input shape is [batch, 20, F]. Validate chronological lag order, feature order and schema-specific dimensions. Fit daily imputation and standardization on unique eligible training user-days only: INNER_TRAIN for all inner fits and TRAIN for outer fits. Retain the Stage 1 training-only missingness-indicator policy, identities and population-standard-deviation convention. No scaler, initialization statistic, class weight or teacher may learn from the evaluation partition.

All Stage 2 cache identities bind label task, row keys, source/schema identity, preprocessing, teacher generation, seed, initialization and loss condition. A matching shape or column count is insufficient.

TEST remains excluded. Reused VALIDATION supports retrospective comparisons; a future untouched period or cohort is needed for confirmation.

## 5. Full architecture and inference semantics

Propose the historically evidenced architecture, adapting only input width to F:

- One bidirectional LSTM, 64 hidden units per direction, followed by dropout 0.2.
- Temporal additive attention with hidden dimension 64; context width 128.
- ODST-046: two layers, four trees per layer, depth four, one output per tree, temperature 0.5, ODST dropout 0, initial leaf standard deviation 0.05.
- Sparsemax feature-selection probabilities, sigmoid split choices, and dense concatenation of preceding layer outputs as in the producing source.
- Final classification logit is the canonical mean of the eight tree outputs; probability is its sigmoid.

The stored linear head, residual scale and sample gate do not participate in full-model classification. They are not silently blended into the output. Test this explicitly against the producing forward implementation. Attention weights are temporal weights, not causal daily-feature importance. Teacher inference is needed for guidance during training, not for the student's final deployment prediction.

## 6. New teacher generation and matched controls

Every schema receives its own new teachers on the same eligible training partition and preprocessing as its students. Use seeds 42, 52 and 62 throughout. No teacher is shared across feature sets or between inner and outer fits.

Propose four trainable conditions per schema/seed/partition:

1. **L: attention-linear precursor.** A new Bi-LSTM/attention model supplies training-only encoder initialization and a fresh linear reference.
2. **T: full ODST teacher.** Copy that schema/seed's L encoder and attention state, initialize its ODST from training contexts, and train the full architecture on the task loss. Freeze the resulting teacher after its checkpoint/epoch rule is satisfied.
3. **C: task-only full student.** Start from an exact clone of T for the matching schema/seed and train with task loss alone, using a fresh optimizer with no inherited teacher moments.
4. **G: guided full student.** Start from the same exact T clone as C, reset its optimizer, and train with task loss plus ET1 guidance.

C and G must have bit-identical starting state hashes, preprocessing, batches/order and training budget rules. They differ only in the guidance term. This comparison estimates the effect of continued guidance conditional on teacher-informed initialization. It does not isolate initialization itself. T-versus-C additionally describes the effect of further task-only training; G-versus-T includes both continued training and guidance.

For each schema and partition, finish all three T fits before either student condition uses ensemble targets. The guidance target for each eligible training example is the equal-weight arithmetic mean of the three frozen teacher **logits**, not their probabilities. Use only the same schema's teachers. Target caches bind all three teacher state hashes, input/scaler identity, canonical row keys, dtype and logit convention.

Proposed guided objective:

`L_G = weighted_BCE(student_logit, label) + 0.5 * mean((student_logit - mean_teacher_logit.detach())**2)`.

The MSE is unnormalized ET1 logit MSE. There is no softened-KL temperature, route anchor, confidence/agreement weighting or historical single-teacher C5 loss. Teachers remain in eval mode, receive no gradients, and cannot appear in student optimizer groups. Teacher target construction on training examples is disclosed as in-sample distillation. Do not claim cross-fitting or unseen-teacher targets.

Route-guidance and random-initialization factorial controls are separate optional extensions; they are not hidden inside this budget.

## 7. Proposed training recipe — requires review

These are **new-study proposals**, not an exact recreation of the archived training history:

- L: Adam at 0.001, weight decay 0, batch 1,024, maximum 30 epochs, patience four, gradient norm clipping 1.
- T: at most 30 epochs total. First three epochs train ODST only with encoder/attention frozen in eval mode and encoder dropout disabled; subsequent epochs train encoder/attention at 3e-5 and ODST at 0.001. Task-only weighted BCE. Reset and document optimizer groups at the phase boundary for both inner and outer T. Switch encoder/attention/dropout to train mode at epoch four. This warm-up is proposed, not asserted to be historical practice.
- C/G: train encoder/attention at 3e-5 and ODST at 0.001, weight decay 0; at most 30 epochs, patience four, gradient clipping 1; inactive linear/gating parameters frozen.
- All task losses: positive weight = 0.25 × training negatives / training positives, independently derived from the fit partition.
- CUDA float32; AMP and TF32 off; deterministic algorithms on; cuDNN benchmark off; fixed CUBLAS workspace; exact Adam defaults, dropout and shuffle behavior to be serialized before implementation approval.

Inner stopping uses INNER_SELECT AP with strict improvement, earliest tied epoch and patience four. For T, checkpoint selection and stopping begin only starting at epoch four, after its three warm-up epochs; all 30 permitted epochs include warm-up. Do not choose a teacher/student checkpoint on VALIDATION.

Outer L/T/C/G fits are new full-TRAIN models. Use the upward-rounded median of the three best inner epochs separately for each schema and condition, clamped to 1–30; T is clamped to 4–30 because inner checkpoint eligibility begins at epoch four. For C and G use the same outer epoch count: the maximum of their separately computed rounded-up inner medians, clamped to 1–30. This shared count is fixed from inner data and prevents outer G-C from also comparing different training durations. Train exactly that many epochs with no outer stopping. Outer students clone the newly fitted outer teachers, not inner checkpoints.

**Resolved initialization proposal for independent review:** use `implementation/contracts.py`. Select min(4096, N_fit) distinct training window indices with PCG64, sort them, and encode in eval mode/no_grad in batches of 1024; concatenate float32 128-dimensional contexts in that order. No labels or evaluation windows enter initialization. Run the pinned producing NODE data-aware initialization on CPU contexts with threshold_quantile=0.5, target_scaled_std=1.0 and leaf_init_std=0.05, preserving its sequential dense-layer behavior and temperature clamps. The base constructor temperature is 0.5; learned split temperatures are initialized by the training-data method, not asserted to stay constant.

RNG seeds are the big-endian first four bytes of SHA256(`stage2-v0.3|schema|partition|seed|phase`); sampling uses `init_sample`, leaves use `init_leaf`, and each phase has a distinct documented stream. Preserve and restore the CPU RNG around data-aware initialization. Only the LSTM input width depends on F; ODST layer inputs are 128 and 132. The producing model constructor/forward semantics remain pinned. Synthetic source parity tests check initialization and canonical tree averaging for 6/13/29. This resolves the written contract; GPU and end-to-end runner verification remain required before fitting.

C and G begin from the identical T state with independently constructed fresh Adam optimizers, identical group hyperparameters and reset shared training RNG streams. Precompute and hash every frozen teacher target before student training. No teacher forward occurs inside either student's training batch loop. BCE is batch mean with training-only positive weight; ET1 is unweighted batch-mean squared logit error with lambda=0.5, and the target is the mean of canonical eight-tree teacher logits. Inner C/G keep their own stopping histories; G-C therefore compares the registered training recipes including inner stopping, not only a pointwise loss term.

Pin Adam betas=(0.9,0.999), eps=1e-8, weight_decay=0, amsgrad=False, foreach=False and fused=False; no internal LSTM dropout. PCG64 epoch permutations advance within a fit; sample index hashes and generator state are checkpointed. Report cap-hit flag, terminal epoch, best epoch, stale count and late AP trajectory for every condition/schema/seed. The 30-epoch cap applies uniformly; no outcome-dependent extensions or unbudgeted sensitivity fits. Cap hits remain a limitation.

## 8. Fit budget and resource plan

For each of inner and outer partitions: 3 schemas × 3 seeds × 4 conditions = 36 fits. Proposed Stage 2 total: **72 new fits** comprising 18 linear precursor fits, 18 full teacher fits, 18 task-only student fits and 18 guided student fits. Teacher ensembles reuse those teachers; they add inference/target-generation cost, not extra fits.

This intentionally trains fresh precursor references rather than assuming Stage 1 attention state dictionaries are interchangeable with the historical producing architecture. Optional reuse would need demonstrated key/function/preprocessing parity and a revised reviewed budget before execution.

Separate total logical fits, fitted attempts, completed fits, failed attempts, target-generation time and verification time. Stage 1's 174 logical fits and one authorized recovery attempt are independent accounting records. No Stage 2 runtime or memory ETA has been measured. Record extraction reuse, precursor/teacher/student training time, target generation, peak host RSS, peak CUDA allocation, inference and artifact storage. Whole-device GPU peak requires a separate measurement and must not be inferred from PyTorch allocation alone.

Run sequentially on the local GPU after Stage 1 ends; no concurrent training campaign or recipe changes for speed. Read-only resource checks are permitted. A pilot fit for feasibility is still a model fit and requires explicit reviewed accounting; synthetic implementation checks need no training data.

## 9. Evaluation and decision rules

Primary metric is sklearn noninterpolated average precision (AP), the calculation historically labeled PR-AUC. Do not substitute trapezoidal area. Report per-seed values and their arithmetic mean, not pooled-score AP unless separately registered.

Estimation-first design: the primary **estimation contrast** is G(F29) minus G(F13), reported as an AP point estimate and interval without a confirmatory success/promotion decision. The 0.005 practical benchmark may be shown descriptively, not as a validated power target. G(F6_PRIMITIVES) minus G(F13) is a secondary estimate; any -0.005 noninferiority benchmark is explicitly exploratory. Failure to exclude zero or the margin does not establish equivalence or inferiority.

Retain three seeds and the 72-fit budget. More seeds characterize optimizer variability but do not increase the number of positive users, and cannot by themselves repair cluster-level uncertainty. Claude's power concern is treated as a planning limitation, not a demonstrated calculation of attainable power or a claim that the decision rule is impossible.

Register the frozen three-teacher ensemble as an exploratory no-new-fit reference: probability=sigmoid(mean canonical teacher logits). Predict on the same rows, report its AP and costs, and compare descriptively with individual teachers and G/C. G-C estimates ensemble distillation conditional on teacher-informed initialization. None of the secondary contrasts is promoted to an uncorrected confirmed finding.

Use 2,000 attempted paired user-cluster draws with seed 42, retaining user multiplicity. Within each draw compute AP differences for matched seed pairs and then average them. Use linear percentiles and require at least 1,900 valid two-class draws; record invalid draws without resampling toward a desired result. Bootstrap intervals condition on these fitted teachers/students and this historical calendar; they do not capture full teacher-retraining or feature-selection uncertainty. Three student seeds using the same teacher ensemble are not independent teacher ensembles.

For each condition/schema/seed, calibrate F1 threshold on its best inner checkpoint using the existing exact tie rule and all-negative option; freeze it for outer refit. Label outer precision/recall/F1, confusion counts and alert burden TRANSPORTED_THRESHOLD. No validation threshold search or within-bootstrap retuning.

Report ROC-AUC, prevalence, AP above prevalence, costs and all 20 nonoverlapping offsets. Offset contrasts are descriptive mean seed AP differences, with offset 0 first and no offset bootstrap. Use canonical pairing keys including label_task, user, start/end dates and legacy sequence ID. Preserve positive-window denominators and disclose overlapping-window dependence.

## 10. Execution order, identities and interruption governance

1. Close Stage 1's final source/runtime, provenance, fit-count and recovery checks.
2. Freeze three schemas and this protocol's resolved version; publish an author response to independent review.
3. Implement and test a new Stage 2 package outside Stage 1 `implementation/`; freeze exact source/runtime/inputs/recipes/teacher-generation identities before fitting.
4. Complete inner L and T generation for all three schemas/seeds, then inner C/G calibration. Verify all 36 inner fits and thresholds/outer epoch rules.
5. Freeze the outer manifest and enforce source/runtime identity at **outer entry**, not just after outer predictions.
6. Fit outer L and T, then outer C/G. Perform evaluation only against the registered schema/condition panel; preserve all outcomes and failures.
7. Run analysis, paired intervals, provenance and fit-count reconciliation; supply an independent audit packet.

Every fit retains run identity, source/runtime/split/preprocessing hashes, initialization state hashes, teacher/target hashes, checkpoint hashes, training history, thresholds, predictions, metrics and cost. C/G pairing must be directly verifiable. Initialization, logits and route/tree behavior need synthetic parity checks against the producing architecture, including gradients and inactive heads. Real-data preflight must verify keys, channels, label parity, split exclusion and no duplicate canonical windows without opening TEST.

Use exclusive cooperative locks and a coordinator process identity with birth time. On interruption, retain partial evidence and stop safely. Recovery eligibility depends on infrastructure failure, regardless of available scores. Extra fitted attempts need explicit authorization and an identical-identity continuation; never silently change a recipe or restart the whole study under a new manifest. No automatic retry or stale-lock takeover is proposed.

## 11. Independent review checklist and remaining blockers

Independent review should examine schema transfer without outer reranking; complete architecture and forward parity; the fresh precursor→teacher→student chain; equal starting C/G states; teacher-only training data; teacher/ensemble target identities; exact loss reductions; warm-up/stopping/outer epoch semantics; fit accounting; threshold and bootstrap semantics; code/runtime gates; and crash recovery.

Before declaring this executable, resolve and freeze:

- Whether the proposed three schemas and 72-fit budget are accepted.
- Implementation verification of the resolved fresh-teacher initialization contract, optimizer/shuffle details and proposed teacher warm-up.
- Evidence that the adapted producing architecture supports each input width without changes to ODST semantics.
- Definition of the primary inference claim and treatment of secondary noninferiority/guidance comparisons.
- Stage 1 final audit disposition, including the earlier general duplicate-event-ID diagnostic gap. No raw-data duplicate defect is asserted here; its scope and any remaining limitation must be reported.
- Current-environment hardware/runtime identity and exact accounting for future recovery attempts.

**Training gate:** independent protocol review, reviewed executable implementation, successful preflight and explicit Stage 2 execution authorization. This document supplies the concrete proposal for that review; it is not itself a completed independent audit or a training authorization.


## 12. Safe pause and checkpoint/resume contract

Internet loss does not affect a launched local runner; no network service or Codex response is required for a training batch. The laptop must remain awake. Shutdown, reboot or forced sleep can interrupt compute.

The planned runner provides a durable pause request checked at optimizer-update boundaries and at inference chunks. On request it checkpoints, atomically records PAUSED, releases its process claim, retains the campaign reservation, and exits. The user waits for the PAUSED status before shutting down. Resume must be an explicit local operation; there is no unprompted automatic restart. An epoch-boundary-only pause is an additional fallback, not a claim of immediate checkpoint completion.

Save a generation after every 25 completed optimizer updates, every epoch, phase transition and graceful pause. Persist model and optimizer state, next batch, epoch-start PCG64 state and permutation SHA256 (the full permutation is regenerated, not stored), Python/NumPy/CPU/CUDA RNG states, PCG64 generator state, early stopping and best model state, history, accumulated loss and processed count. Checkpoint identity additionally binds code, source dependencies, inputs, scaler, fit ID, teacher/target hashes, dtype, device/runtime and optimizer recipe. Recovery rejects identity drift and corruption. Final predictions and target caches also need generation/progress identity and durable completion markers; partial files cannot be reused as complete artifacts.

Write new checkpoint bytes to a same-directory temporary file, flush/fsync, atomically replace the generation name, then atomically commit a SHA256-bound pointer. Retain earlier committed generations. Never trust an incomplete temporary file or load an external/untrusted pickle. `implementation/contracts.py` supplies this foundation; it is not the campaign runner.

After an abrupt power loss, the last committed generation permits replay of unsaved batches. Retain and count process segments and repeated optimizer updates separately from the 72 logical fits; disclose replay time and checkpoint overhead. Resume is allowed only for identity-matched committed state under the reviewed contract and explicit user instruction. An absent/corrupt checkpoint requires a separately authorized additional fitted attempt, with prior evidence preserved. Graceful continuation does not refit completed models.

Test full-architecture uninterrupted-versus-resumed parameter/optimizer/loss/RNG parity on synthetic CPU and CUDA data, fresh-process restore, phase transition, corruption/mismatched identity rejection, atomic pointer failure and real runner pause/control behavior before any CERT fit. Current tests establish a foundation only; full CUDA/crash/runner tests are pending. Exact resumption on changed hardware/software is not promised.

Use explicit registered fit IDs and one atomic terminal status with append-only transition history. Log hashes, writer-script identity, checkpoint pointer and process birth time accompany each status. Reconciliation writers have their own retained code and command identities. Phase 1's archived files are read-only.

## 13. Review disposition and training gate

This v0.3 proposes resolutions for S2-01..S2-08 and retains all old drafts. The 72-fit, three-schema panel remains unchanged. New 30-epoch and shared outer C/G scheduling rules require independent review. Attach producing architecture/ODST/attention/loss sources, exact reused input identities, synthetic test records and pause/resume foundations to the review packet.

Before training: complete and independently review the full orchestration/data/teacher/target/checkpoint implementation; pass source/runtime/data preflight and synthetic CPU/CUDA crash/continuation checks; freeze executable manifests; obtain explicit execution approval. No real-data fit is launched by protocol drafting or synthetic implementation tests.


## 14. v0.4 independent-review amendments and implementation contract

This dated revision supersedes conflicting continuation and initialization wording in v0.3. It preserves that draft and the Stage 1 frozen sources and results. Status: IMPLEMENTATION DRAFT, NOT AUTHORIZED FOR TRAINING. Implementation is isolated in implementation_v0_4; the old implementation directory is unchanged.

R2-01: Before model construction, seed the construct_L or construct_T stream. A stream seed is the first four big-endian SHA256 bytes of stage2-v0.4|schema|partition|seed|phase. Record the constructed state hash before transfer. Initialization-window selection uses init_sample and leaf initialization uses init_leaf. ODST feature-selection weights remain those drawn at construction. Preserve learned per-node temperatures initialized by the producing source; the constructor temperature is 0.5, not a requirement to overwrite initialized temperatures.

R2-02: C and G share the student stream for batch permutations and all dropout randomness. Both start from the same seed-matched T state. Reset the student stream after all construction and teacher-cache operations. Other streams are train_L and train_T. Paired randomness is a controlled starting contract, not a promise of identical resulting optimization.

R2-03/R2-08: Save checkpoint generations every 25 updates, at epochs, phase transitions, graceful pauses and final training. Persist epoch-start PCG64 state and permutation hash; never store the full shuffle vector. Keep the last three generations, last two epoch generations and last three phase/pause/final generations (union at most eight state files). Keep small commit metadata. Each commit has an increasing generation number and predecessor-record hash. A corrupt generation triggers score-independent fallback to the latest earlier verified retained generation. If none exists, stop reserved; never start a fresh fit automatically. Discard incomplete inference and regenerate it deterministically. Continuation is mandatory for eligible checkpoints regardless of observed scores. Record every process segment; explicitly distinguish replayed computation from new logical fits. There are 72 registered logical fits; approved continuation does not change schemas, seeds, recipe or fitted identity. This contract still requires synthetic fresh-process CPU/CUDA and control tests before launch.

R2-05/R2-06/R2-07: Vendor the three producing architecture files in a private namespace and hash-check all three, including sequence_ensemble.py. Record the single relative-import adaptation. Copy only lstm.* and attention.* from L into T; do not copy the linear head or any ODST parameter. Initialize ODST on CPU using a local CPU generator whose state temporarily replaces and then restores CPU RNG. CUDA RNG is unchanged by this helper. T warm-up freezes encoder and attention parameters and sets their dropout modules to evaluation mode. Joint training re-enables those modules. Task-only and guided students create fresh Adam optimizer state after copying T weights.

R2-09: Record all per-seed AP contrasts, not only seed means. Primary reporting is retrospective estimation, not untouched confirmation: the 6/13/29 panel was fixed after Stage 1 outer outcomes existed. Retain descriptive paired user-cluster intervals conditional on fitted models; exploratory comparisons are uncorrected for multiplicity. Report all 20 non-overlapping offsets, starting with offset 0, as seed-mean AP differences without offset bootstrap. Report the mean-logit three-teacher ensemble as a reference with zero additional fits. Guidance versus task-only mixes regularization with teacher ensembling; no causal guidance-only claim follows.

R2-10: Before launch, record an operations acknowledgement covering mains power, no sleep, and OS/driver update deferral. Do not modify system settings automatically. Bind Python, packages, GPU UUID/model, driver, CUDA and cuDNN to the manifest. A changed runtime blocks continuation pending review. The persistent study reservation remains while PAUSED or FAILED_RESERVED; the process claim ends on graceful pause. Resume is explicit and never triggered by an internet connection change.

Input preflight accesses only saved TRAIN/INNER_SELECT/VALIDATION arrays and metadata. TEST and raw event streams are not opened. Stage 1 raw duplicate-event diagnostics and historical-label limitations remain disclosed; new checks do not retrospectively assert raw-data parity.

Execution requires a passed test record and saved-array preflight, frozen manifest, independent implementation-review verdict, explicit user execution authorization and operations acknowledgement bound to that manifest. No approval record may be inferred from implementation authorization. Internet loss does not stop a launched local process; safe shutdown requires requesting pause and waiting for PAUSED. Abrupt shutdown may require replay from the last verified checkpoint. Changed hardware/software or absence of a valid checkpoint is not promised to resume.


## 15. v0.5 implementation-review corrections (supersedes conflicting operational wording)

This revision responds to Claude's independent v0.4 review I-01 through I-12. Protocol and implementation remain review candidates; CERT execution is NOT authorized. Preserve v0.4 sources, manifests and audit packets. The statistical recipe and stage2-v0.4 random-stream namespace are unchanged.

Launch requires separate implementation and execution dispositions. Bind the exact Markdown report and findings JSON by SHA256, require findings EXECUTION=READY and execution_conditions_open=[], require every listed review condition CLOSED, and require a manifest-bound PRE_LAUNCH_TESTS record with passed, source-bound evidence for CPU orchestration, CUDA orchestration, C/G pairing, twenty external hard terminations, full-shape synthetic costs, and failure paths. Retain the existing independently reviewed source, runtime, preprocessing/input and explicit authorization/operations gates. Synthetic approval fixtures are labelled SYNTHETIC_ONLY, isolated under audit, and cannot approve a CERT_STUDY manifest.

FAILED_RESERVED requires a separate explicit failure-record-bound RESUME_AFTER_FAILURE authorization. A completed campaign is immutable and cannot be run again. A stale request predating the new process birth can be cleared for explicit continuation; a request made during startup remains pending. On inability to inspect process birth time, fail clearly and treat the owner as possibly alive.

Checkpoint commit records form chronological history. Separately record the model-state parent (generation, record hash and payload hash); a fallback's new checkpoint names the generation actually loaded as state_parent. Valid orphan-pointer commits are adopted into the ledger after verifying their payload. Append every resume to RESUME_LOG; LAST_RESUME is a current pointer, not the history. Allocate sequence numbers above every state/commit filename and never overwrite a commit. A damaged record or broken record chain stops for recovery review; it cannot silently start a new chain. Payload corruption can still fall back along an intact ledger.

Record START with resumed generation and updates_at_resume; record observed updates durably and graceful PAUSED/COMPLETE segment ends. Compute observed replay from prior observed update counts versus the resumed count. An abrupt shutdown between an optimizer update and its durable observation may leave a small unobserved tail; disclose that limit rather than assert an exact count of unobserved computation.

C/G pairing must be asserted in analysis for starting weights, training stream, first-epoch permutation and first-batch dropout masks. This does not promise identical masks later after divergent optimization. Freeze the unused ODST output head. Label G/F29 minus G/F13 primary retrospective estimation; G/F6 minus G/F13 secondary exploratory with the -0.005 benchmark; all others exploratory and uncorrected. cap_hit pertains only to the inner 30-epoch ceiling; outer fixed budgets are not capped early stopping. Final completion records bind every registered per-fit completion record, process segment totals, ensemble cache completions and analysis.

Normalize historical vendor text to LF, preserving exact source text and recording the single relative-import adaptation. Record the entire pip freeze --all list and its canonical hash in runtime identity. Stage 2's system Python/PyTorch/CUDA/cuDNN stack differs from Stage 1's conda stack; juxtaposition must disclose that difference.

Required synthetic orchestration runs the actual runner/analysis with a saved synthetic Dataset stand-in, all 72 identities, cap four, batch 16 and a reduced bootstrap for test cost. Production retains cap 30, batch 1024 and 2000 bootstrap draws. Compare scientific model/prediction/result/history/operating-point/analysis artifacts byte-for-byte; lifecycle timestamps, process records, costs and run bindings should differ and are not scientific parity failures. Test CPU and CUDA fresh processes at seven forced pause seams, twenty externally terminated children, failure-bound authorization and the uncommitted-partial refusal. Synthetic full-calendar allocation and representative production-batch timing yield conditional scenarios, not a measured whole-campaign ETA. Actual OS power-cut/NTFS durability remain unproven.


## 16. v0.6 checkpoint transaction and measured operations (superseding v0.5)

Claude's v0.5 execution conditions E-1/E-2 remain subject to independent clearance. No CERT execution is approved. Preserve old versions. The statistical recipe and stage2-v0.4 random streams are unchanged.

A save uses unique same-directory temporary names, including the generation number for state and commit temporaries. At process startup the next number exceeds all state/commit names, including leftovers. Completed model bytes are flushed/fsynced and renamed. Commit JSON is written to a unique temporary file and flushed/fsynced, then atomically published without overwriting by an NTFS hard link; the redundant temporary link is removed after publication. A complete commit is published BEFORE the latest pointer. Pointer replacement also uses a unique fsynced temporary. A restart selects the newest verified committed payload even if the old pointer lags. Partial temporary files are never parsed as committed state, never reused and retained as evidence. If no valid initial committed state exists, the separate uncommitted-partial recovery rule still applies; there is no silent fresh fit.

Full chronological verification occurs on process startup/load and at final training save. Under exclusive campaign ownership, routine saves verify the newest three records and update an in-memory verified prefix, sequence counter and bounded retained-state inventory. Older prefix corruption is caught at the next full audit; it is not silently re-rooted. This removes repeated parsing of the whole history at every save. Every-update durable observation remains in place and its actual Windows fsync overhead is measured.

E-1 evidence externally terminates synthetic children during state and commit temporary writes, after fsyncs, after model rename, during pointer writing and after publication. Compare uninterrupted versus explicit plain-command continuation with the actual runner. This is process-termination evidence on this NTFS stack, not an actual OS power-cut durability guarantee.

E-2 uses a full guided synthetic GPU fit: 622000 windows, 608 batches per epoch, batch 1024, save every 25 updates and at least 15 epochs. Record wall/update compute time, checkpoint calls/duration, checkpoint and other fsync durations, resource peaks, retained disk footprint, and a revised conditional campaign estimate. Synthetic daily data is float64 with shape 2000x413x29. Fixed zero guidance targets and an archived synthetic teacher are performance fixtures, not scientific teacher results. Final evaluation is small; other campaign evaluation/cache/bootstrap overhead remains separately qualified.

Regenerated orchestration evidence uses cap eight and explicitly reports actual patience stopping. All six pre-launch records must match the new sources and final manifest; supplementary E-1/E-2 evidence is included in the review bundle. The independent findings must clear technical execution conditions; operations acknowledgement and human launch approval remain distinct requirements. The manual recovery runbook covers authorization-bound quarantine, never deletion or identity bypass.
