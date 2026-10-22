from p5common import *
import pandas as pd,re
def table(frame):
    def fmt(x):
        if pd.isna(x):return ''
        if isinstance(x,float):return f'{x:.9g}'
        return str(x).replace('|','/').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(frame.columns)+' |','| '+' | '.join(['---']*len(frame.columns))+' |']+['| '+' | '.join(fmt(x) for x in row)+' |' for row in frame.itertuples(index=False,name=None)])
def main():
    from PIL import Image
    f=check_frozen();receipt=json.loads((OUT/'AMENDMENT3_RECEIPT.json').read_text(encoding='utf-8'));pr=(R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md').read_bytes();section=pr[receipt['previous_bytes']:receipt['previous_bytes']+receipt['section_bytes']];assert hashlib.sha256(section).hexdigest()==receipt['sha256'];assert hashlib.sha256(pr[:receipt['previous_bytes']]).hexdigest()==receipt['previous_sha256']
    data={letter:json.loads((OUT/f'{letter}_RESULTS.json').read_text(encoding='utf-8')) for letter in ('A','B','C','D','E','F')}
    for name in ('A_r5.1_SCORING_COMPLETE.json','A_r6.2_SCORING_COMPLETE.json','B_SCORING_COMPLETE.json'):assert (OUT/name).exists()
    assert len(data['A']['results'])==552 and len(data['A']['contrasts'])==36
    assert len(data['B']['curves'])==864 and len(data['B']['contrasts'])==21
    assert len(data['C']['insider_detection'])==375 and len(data['C']['users_flagged_per_day'])==6960
    assert len(data['D']['metrics'])==68 and len(data['D']['contrasts'])==16
    assert len(data['E']['calibrators'])==2 and all(r['fit_calls']==1 for r in data['E']['calibrators'])
    for path in OUT.glob('*.png'):
        with Image.open(path) as im:assert min(im.info['dpi'])>=299
    skips=['Historical harnesses define paired user bootstrap and qualify the 1:1 official insider/incident correspondence; they do not define an independent incident-only bootstrap. No additional incident-only interval was invented.']
    deviations=['Phase 5 is exploratory, including repeated cross-release study of previously examined releases; it is not a new untouched confirmatory study.','The development-user transfer block uses each model\'s frozen development scaler. Existing all-user-scaled bundles are converted by fixed float64 inverse/forward affine transformation; target data are never used to fit a scaler. Float32 source-bundle quantization is retained.','The historical r6.1 manifest binds the original input-manifest bytes but has no derived-bundle byte hashes. Existing bundle bytes were therefore SHA-256 frozen before Phase 5 feature-only analysis; no r6.1 model scoring was repeated.','Each calibration family has one common calibrator fitted once on the three fixed seeds pooled equally, then shared unchanged across those seeds. There are exactly two calibrator fits, and no holdout fit.','Calibration fits and application use the logit of the frozen probability convention, with machine-epsilon clipping only at boundaries, so the saved holdout predictions can be reused without another forward pass.','Operational episode rates include both all allowed calendar user-days and scorable completed-window decision user-days. The first 19 days of each period are explicitly unscorable. Timeliness starts at the first malicious day in allowed periods only; no TEST date is queried.','Top-k user-day precision uses actual endpoint malicious-day labels, with completed-window precision supplied alongside.','Holm p-values are exploratory approximate two-sided bootstrap sign-tail probabilities derived from saved Phase 4 paired replicates with an add-one correction; the original preregistered labels remain unchanged in Phase 4.','The detectable-difference calculation is a normal approximation based on observed CI width, not a prospective guarantee or proof of equivalence.']
    result=dict(phase=5,exploratory=True,completed_utc=utc(),amendment3=receipt,models_and_methods_manifest_sha256=sha(OUT/'MODELS_AND_METHODS_FROZEN_PHASE5.json'),no_training=True,r52_test_opened=False,one_pass=dict(r51_model_seeds=69,r62_model_seeds=69,robust_conditions=26,robust_model_seeds_per_condition=27,robust_inference_passes=702,reruns=0),steps=data,skipped=skips,deviations=deviations,figures=[dict(path=p.name,data_csv=p.stem+'_data.csv',dpi=300) for p in OUT.glob('*.png')])
    dump(OUT/'PHASE5_RESULTS.json',result)
    lines=['# Phase 5: additional evaluation battery (exploratory)','',f'Completed UTC: {utc()}','',
      'All analyses in this report are exploratory. The original frozen model family and all 17 development-user Phase 4 families were evaluated once on r5.1 and r6.2. The nine specified holdout model families underwent the registered degradation battery. Operational, ranking, calibration, stability, multiplicity and precision-of-estimation analyses use the allowed TRAIN + VALIDATION holdout only. No base model was trained, fine-tuned, selected or recalibrated, and no target scaler was fitted. The only fits were the two authorised DEVELOPMENT VALIDATION calibration maps.','',
      'The r5.2 TEST period remained sealed for all users. No GitHub push occurred. Existing teacher-anchored repositories, worktrees, frozen checkpoints, scalers, thresholds and prior result files were preserved. New code is in the isolated Phase 2 project\'s phase5 subfolder. Computation used two CPU threads and a 35% per-process GPU memory cap, with cooperative pauses between neural batches; no unrelated process or window was controlled.','',
      '## Amendment 3 and preregistration chronology','',section.decode('utf-8'),'',f'Amendment section SHA-256: `{receipt["sha256"]}`. UTC: {receipt["utc"]}. All preceding {receipt["previous_bytes"]:,} bytes were preserved; preceding-byte SHA-256: `{receipt["previous_sha256"]}`. The methods and model manifest was frozen before any Phase 5 target inference.','',
      '## Frozen model inventory and methods','',f'Manifest SHA-256: `{sha(OUT/"MODELS_AND_METHODS_FROZEN_PHASE5.json")}`. Model weights and all declared dependencies were verified before evaluation and again at report assembly. TRACE is the paper name for TA2/F11; the original task-only comparator is the matched C2-OPT/F00 family, rather than the older historical C2 family.','']
    inventory=[]
    for block,specs in f['models'].items():
        for s in specs:inventory.append(dict(block=block,model=model_name(s['model']),seed=s['seed'],threshold=s['threshold'],checkpoint=s['checkpoint'],sha256=s['sha256']))
    save_csv('MODEL_INVENTORY.csv',inventory);lines += [table(pd.DataFrame(inventory)),'',
      '## A. Cross-release transfer','',
      'The existing EDITOR-006E/007C dense-daily window provider, frozen bundle identities, completed-window labels, endpoint labels and offset-0 flags were reused. Each release has 69 frozen model–seed combinations: 18 from the original six-family block and 51 from the 17-family development block. r5.1 has 996,000 windows; r6.2 has 1,988,000. The original block uses the stored all-user r5.2 TRAIN scaler directly; the development block applies its own frozen TRAIN scaler by an affine conversion of the stored z-space, without fitting.','',
      'PR-AUC is average precision. Ranking excess is AP minus prevalence; ratio to prevalence is descriptive AP/prevalence. Frozen-threshold exceedance is the flagged-window fraction and equals alerts per 1,000 divided by 1,000. A mean row averages fixed-seed metrics and is not an ensemble-score result. Contrasts compare three-seed mean AP with 2,000 paired user-cluster resamples, seed 42, 95% percentile intervals. A bootstrap draw with no positive windows is invalid and excluded; valid counts are reported. The historical harness does not define an additional independent incident-only bootstrap; official insider/incident correspondence is retained as a qualification.','']
    def add_csv(filename,title,subset=None):
        lines.extend(['### '+title,'',f'Full machine-readable table: [{filename}]({filename}).','']);d=pd.read_csv(OUT/filename);d=d if subset is None else subset(d);lines.extend([table(d),''])
    add_csv('A_TRANSFER_RESULTS.csv','All transfer models, seeds and views')
    add_csv('A_TRANSFER_CONTRASTS.csv','Paired user-cluster transfer contrasts')
    add_csv('A_HISTORICAL_COMPARISON.csv','Historical frozen-family comparisons')
    lines += ['Historical comparisons are explicitly descriptive because the final TRACE family and earlier C2/C5/attention-linear families are different frozen models. “Better” or “worse” in the historical table refers to the observed AP point estimate only; it is not a paired superiority ruling.','']
    add_csv('A_FEATURE_SHIFT.csv','Feature shifts relative to r5.2 TRAIN')
    lines += ['Feature shift is the target daily-row mean in frozen all-user TRAIN z-space minus the TRAIN reference mean of zero. It is not a target-fitted scaler. For r6.1, only the existing derived feature bundle was read; no new predictive run or raw-source rebuild occurred.','',
      '## B. Robustness on unseen users','',
      'The same 213,000 pooled holdout completed windows and saved clean predictions were reused. At severity zero no model was rescored. The 26 nonzero conditions each ran once for all 27 specified model–seed combinations (702 new inference passes). Partial source removal is the manuscript\'s linear interpolation between clean and fully ablated tensors. Full ablation uses the frozen development scaler and recovered authoritative raw-zero transformation, including derived total/activity recomputation and the frozen duration rule. Noise uses the authoritative bounded Gaussian implementation on the seven continuous/count variables, with seed 101 and a SHA-derived level-specific RNG shared across every model and seed. Binary channels remain unchanged. No thresholds were retuned.','',
      'AURC is the trapezoidal integral of AP(severity)/AP(clean), divided by maximum severity; aggregate source AURC averages the five source-specific AURCs. Bootstrap ratios reuse the same paired 500-user multiplicities across clean and degraded scores and all seeds. Retention above one is retained as observed.','']
    add_csv('B_RETENTION_CURVES.csv','All degradation-severity AP and retention results')
    add_csv('B_AURC.csv','Source-specific, aggregate source and noise AURC')
    add_csv('B_AURC_CONTRASTS.csv','Paired AURC contrasts')
    for source in ('logon','device','file','email','http','noise'):lines += [f'![{source} retention](B_RETENTION_{source}.png)','',f'300 dpi. Data: [B_RETENTION_{source}_data.csv](B_RETENTION_{source}_data.csv).','']
    lines += ['## C. Insider and operational evaluation','',
      'All 25 registered holdout insiders and 475 non-insiders were retained. Insider detection requires at least one frozen-threshold alert on a positive completed window. Insiders without a malicious day in the allowed periods are explicitly shown as ineligible for observed positive-window detection rather than assigned an unseen TEST onset. Alert timing uses window decision/end dates, not window starts, and delay starts at the first malicious day in allowed TRAIN + VALIDATION only.','',
      'Episodes consolidate same/consecutive alert decision days within each user; the malicious-episode share requires a true malicious day inside the episode\'s calendar interval. Exposure is reported per 232,000 allowed calendar user-days and per 213,000 scorable decision user-days. The first 19 days of each period have no completed window and are marked unscorable in the full daily table. Scenario membership came only from answer-file names; no answer activity payload was read.','']
    add_csv('C_OPERATIONAL_SUMMARY.csv','Detection, timeliness, false-positive users and episode rates')
    add_csv('C_INSIDER_DETECTION.csv','Every insider, model and seed')
    add_csv('C_SCENARIO_DETECTION.csv','Scenario-specific detection')
    add_csv('C_TOPK_TRIAGE.csv','Top-k user-day precision')
    lines += ['The complete per-day table is [C_USERS_FLAGGED_PER_DAY.csv](C_USERS_FLAGGED_PER_DAY.csv), with all 6,960 model/seed/day records and explicit availability flags. Every individual episode is in [C_ALERT_EPISODES.csv](C_ALERT_EPISODES.csv). The pseudonymised scenario map is [C_INSIDER_SCENARIO_MAP.csv](C_INSIDER_SCENARIO_MAP.csv). These complete tables are also embedded in PHASE5_RESULTS.json. Primary top-k precision uses actual endpoint malicious-day labels; completed-window precision is supplied alongside because the model was trained for completed-window risk.','',
      '## D. Ranking beyond PR-AUC','',
      'Alert budgets select ceil(N × budget) windows by descending score, breaking ties with the frozen row order. Recall at a fixed false-positive rate is the greatest attainable ROC true-positive rate at or below that FPR, with tied scores grouped; this is an evaluation metric, not a recalibrated deployment threshold. ROC-AUC contrasts compare TRACE minus each other family using the same 2,000 paired user-cluster resamples and the three-seed mean.','']
    add_csv('D_RANKING_METRICS.csv','All 17 models and fixed-seed means')
    add_csv('D_ROC_CONTRASTS.csv','Paired ROC-AUC contrasts against TRACE')
    lines += ['## E. Calibration','',
      'Exactly two calibrators were fitted: a common positive temperature for TRACE and a common unpenalized Platt logistic map for XGBoost_40. Each was fitted once on the three fixed seeds\' DEVELOPMENT VALIDATION predictions pooled equally (144,000 prediction/label pairs), then shared unchanged across those seeds on holdout. No model family, checkpoint, calibrator form or hyperparameter was selected from target results. Temperature optimization uses log-temperature bounds [−10,10] solely for numerical stability. Both fitting and application use logit of the frozen probability convention with machine-epsilon clipping at boundaries. Holdout base-model inference was not repeated.','',
      'ECE uses 15 equal-width probability bins. Reliability figures pool the three fixed-seed prediction/label pairs; per-seed bins and metric values are also provided. Calibration outputs are diagnostic only: the registered operational thresholds and alerts used elsewhere remain unchanged.','']
    add_csv('E_CALIBRATION_METRICS.csv','Raw and calibrated Brier scores and ECE')
    lines += ['Calibration parameters and fit receipts: [E_CALIBRATORS.json](E_CALIBRATORS.json). Full reliability bins: [E_RELIABILITY_DATA.csv](E_RELIABILITY_DATA.csv).','']
    for name in ('TRACE','XGBoost_40'):lines += [f'![{name} reliability](E_RELIABILITY_{name}.png)','',f'300 dpi. Data: [E_RELIABILITY_{name}_data.csv](E_RELIABILITY_{name}_data.csv).','']
    lines += ['## F. Stability, multiplicity and detectable differences','',
      'Between-seed AP SD uses ddof=1 over seeds 42,52,62. Score correlation is Spearman over the full holdout. Top-100 agreement refers to the highest-scoring windows that actually exceed each seed\'s frozen threshold, with intersection, union and Jaccard shown. Integrated-gradients ranking stability uses existing absolute feature-attribution sums, separately by cohort, stratum and target; the final-logit target is primary and individual trees are secondary. The original validation explanations use the original all-user model; the holdout explanations use the development-retrained model, so the cohorts are not a matched retraining experiment.','']
    add_csv('F_SEED_STABILITY.csv','Between-seed PR-AUC stability')
    add_csv('F_TRACE_SCORE_AND_TOP100_STABILITY.csv','TRACE score and top-100 flagged-window agreement')
    add_csv('F_EXPLANATION_RANK_STABILITY.csv','Between-seed IG feature-ranking correlations')
    add_csv('F_HOLM_SECONDARY_CONTRASTS.csv','Holm correction across pooled Phase 4 secondary contrasts')
    lines += ['Two-sided bootstrap p-values are approximate sign-tail values with an add-one correction, derived from the already saved Phase 4 paired replicates. Holm adjustment uses all 12 pooled secondary contrasts at familywise α=0.05. This exploratory re-analysis does not overwrite the original Phase 4 labels.','']
    add_csv('F_POWER.csv','Observed-width detectable-difference calculation')
    lines += ['The estimated standard error is CI width/(2 × 1.96); the approximate 80%-power MDE is (1.96 + 0.8416) × that standard error. The 95% half-width is also reported. This calculation assumes a roughly normal sampling distribution and does not turn a wide, asymmetric bootstrap interval into proof of equivalence.','',
      '## Skips and deviations','']+[f'- {s}' for s in skips+deviations]+['',
      '## Machine-readable results and integrity','',
      '[PHASE5_RESULTS.json](PHASE5_RESULTS.json) contains all Step A–F tables, methods/approval references, skips, deviations and figure inventory. One-pass sentinel receipts and per-stage logs are under private/. MODELS_AND_METHODS_FROZEN_PHASE5.json binds every active checkpoint, input dependency and new script. All output identifiers are pseudonyms; raw CERT IDs and raw answer payloads are not exported.','',
      'PHASE5_COMPLETE']
    text='\n'.join(lines)+'\n';assert not re.search(r'\b[A-Z]{3}\d{4}\b',text)
    path=OUT/'CHATGPT_PHASE5_REPORT.md';path.write_text(text,encoding='utf-8')
    for p in OUT.iterdir():
        if p.is_file() and p.suffix in ('.csv','.json','.md'):assert not re.search(r'\b[A-Z]{3}\d{4}\b',p.read_text(encoding='utf-8-sig')),'Potential raw identifier in '+p.name
    status('PHASE5_COMPLETE',report=str(path))
    dump(OUT/'FINAL_VERIFICATION.json',dict(utc=utc(),complete=True,no_training=True,calibrator_fits=2,r52_test_opened=False,scoring_reruns=0,preregistration_prefix_preserved=True,checkpoint_hashes_unchanged=True,report_sha256=sha(path),outputs={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!='FINAL_VERIFICATION.json'}))
if __name__=='__main__':main()
