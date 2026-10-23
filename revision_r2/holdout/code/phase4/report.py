"""Assemble the requested auditable report after all required outputs exist."""
from common import *
import re
import pandas as pd
def table(df):
    def fmt(v):
        if pd.isna(v):return ''
        if isinstance(v,float):return f'{v:.9g}'
        return str(v).replace('|','/').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(map(str,df.columns))+' |','| '+' | '.join(['---']*len(df.columns))+' |']+['| '+' | '.join(fmt(v) for v in row)+' |' for row in df.itertuples(index=False,name=None)])
def main():
    original=verify_original();assert (P4/'SCORING_COMPLETE.json').exists();assert (P4/'HOLDOUT_RESULTS.json').exists();assert (EXPL/'holdout/HOLDOUT_EXPLANATION_COMPLETE.json').exists()
    f=json.loads((P4/'MODELS_FROZEN_PHASE4.json').read_text());results=json.loads((P4/'HOLDOUT_RESULTS.json').read_text());receipt=json.loads((P4/'EXPLANATION_ADAPTER_RECEIPT.json').read_text());selection=json.loads((EXPL/'holdout/HOLDOUT_SELECTION.json').read_text());ex=json.loads((EXPL/'holdout/faithfulness.json').read_text())
    for n,h in f['files'].items():assert sha(CODE/n)==h
    for r in f['models']:assert sha(r['checkpoint'])==r['sha256']
    df=pd.read_csv(P4/'HOLDOUT_RESULTS.csv');contrasts=pd.read_csv(P4/'HOLDOUT_CONTRASTS.csv');training=pd.read_csv(P4/'TRAINING_LOG_PHASE4.csv');primary=pd.read_csv(EXPL/'holdout/primary_comparison.csv');ig=pd.read_csv(EXPL/'holdout/integrated_gradients_completeness.csv')
    assert len(df)==len(f['models'])*5+len(set(r['model'] for r in f['models'] if sum(s['model']==r['model'] for s in f['models'])==3))*5
    assert len(contrasts)==70
    prereg=(OUT/'PREREGISTRATION_R2_HOLDOUT.md').read_bytes();assert len(prereg)>3370
    baseline=prereg[:3370];text=prereg.decode('utf-8');amendment=text[text.index('\n\n## Amendment 1'):]
    # Verify each appendix section's exact-byte receipt independently.
    amendments=[]
    for number in (1,2):
        marker=b'\n\n## Amendment 1' if number==1 else b'\n## Amendment 2'
        start=3370 if number==1 else prereg.index(marker);receipt_marker=f'\nAmendment {number} receipt:'.encode();end=prereg.index(receipt_marker,start)
        section=prereg[start:end];section_sha=hashlib.sha256(section).hexdigest();published=re.search(rf'Amendment {number} receipt:.*?: ([0-9a-f]{{64}})',text).group(1);assert section_sha==published
        amendments.append(dict(number=number,sha256=section_sha))
    prefix_hash=hashlib.sha256(baseline).hexdigest()
    current_pred=json.loads((P4/'SCORING_COMPLETE.json').read_text())['prediction_hashes']
    for n,h in current_pred.items():assert sha(PRIVATE/'scores'/n)==h
    from PIL import Image
    for name in ('mean_AP_seed_dots.png','contrasts_forest.png'):
        with Image.open(P4/name) as im:assert min(im.info['dpi'])>=299
    output_files=[p for p in P4.glob('*') if p.is_file() and p.suffix in ('.md','.csv','.json')]
    for p in output_files:
        if p.name=='CHATGPT_PHASE4_REPORT.md':continue
        assert not re.search(r'\b[A-Z]{3}\d{4}\b',p.read_text(encoding='utf-8-sig')),'Potential raw identifier in public output'
    lines=['# Phase 4: additional baselines and unseen-user Option C evaluation','',f'Completed UTC: {utc()}','',
      'The preregistered Option C evaluation used 500 HOLDOUT users excluded from every DEVELOPMENT fit, scaler and selection. The primary cohort pools 197,000 TRAIN windows (917 positives) and 16,000 VALIDATION windows (255 positives): 213,000 completed windows with 1,172 positives. No r5.2 TEST data was opened, built or scored. No r5.1, r6.1 or r6.2 data was used.','',
      'Qasim reports that Assoc. Prof. Dr. Mohd Murtadha bin Mohamad agreed in person on 22 Oct 2026 to using CERT r5.2 user splits for this evaluation. Qasim approved execution at 09:51 (+08). The disclosure record is SUPERVISOR_DISCLOSURE_PHASE4.json.','',
      '## Amendments, chronology and hashes','',f'The original 3,370 preregistration bytes were preserved. Their SHA-256 is `{prefix_hash}`. Both amendments were appended before baseline training and before any HOLDOUT feature window or prediction was materialized. The two original receipts are reproduced below, with the amendment text.','',amendment,'',
      '## Training and frozen recipes','',
      'All 24 additional runs used the same frozen DEVELOPMENT TRAIN/VALIDATION tensors and development-only scaler. All inputs have shape 20 × 13; tabular baselines use the same parity-gated 40 summaries of standardized float32 tensors. Supervised neural models used BCE with positive weight 48.35197368421053. Adam learning rate 0.001, batch 1,024, gradient clipping 1.0, maximum 15 epochs and patience four on DEVELOPMENT VALIDATION AP were fixed in advance. LSTM_AE used benign TRAIN windows only and MSE reconstruction scores. Three seeds (42, 52, 62) were retained. Existing Phase 2 models and thresholds were unchanged.','',
      'New baseline thresholds maximize DEVELOPMENT VALIDATION F1 over all distinct observed scores; ties select the lowest threshold. The existing Phase 2 thresholds retain their frozen grid-plus-quantile rule. No HOLDOUT recalibration or model selection occurred. For IsolationForest and LightGBM, the log\'s epochs/best_epoch fields denote their fixed estimator/boosting-round counts, not repeated neural training epochs.','',
      'Implementation details fixed before training: each TCN residual block contains two causal convolutions, left zero padding and a 1 × 1 skip projection when required; the Transformer uses the PyTorch default post-norm encoder with ReLU; the AE repeats the encoder final hidden vector as decoder inputs and uses zero initial decoder states. These resolve details not specified in the prompt and do not constitute a hyperparameter search.','',
      'Runs were sequential with two CPU threads and a per-process 45% GPU memory cap. Only experiment-owned subprocesses were managed. The shared Python installation, other chat and existing teacher-anchored repositories/worktrees were not modified. LightGBM and bootstrap acceleration dependencies were installed into phase4/.venv with shared read-only access to existing packages.','',table(training),'',
      f'Original MODELS_FROZEN.json v2 SHA-256: `{f["original_freeze_sha256"]}`. Additional checkpoints and their hashes, original checkpoint references, exact thresholds, dependencies and scorer hash are in MODELS_FROZEN_PHASE4.json (SHA-256 `{sha(P4/"MODELS_FROZEN_PHASE4.json")}`). All original implementation and model hashes were verified before scoring and again after execution.','',
      f'Option C scorer SHA-256: `{f["scoring_script"]["sha256"]}`. The original deferred scorer was preserved; its Option C successor resides in the new phase4 code folder. Original exclusive sentinel HOLDOUT_SCORING_CONSUMED.json was consumed before any HOLDOUT feature build or inference. Prediction passes: one; reruns: zero. Subsequent metrics read saved predictions only.','',
      '## Metrics and inference','',
      'AP is average precision (PR-AUC); ranking excess is AP minus the prevalence for that view. Precision, recall, F1 and alerts per 1,000 use each seed\'s frozen DEVELOPMENT threshold. A mean row is the arithmetic mean of the three seed-level metrics, not an ensemble-score metric. There is no common threshold for a mean row.','',
      'Primary contrasts are TA2 − XGBoost_40 and TA2 − F00. Additional-baseline contrasts are secondary exploratory. The paired user-cluster bootstrap uses 2,000 resamples with seed 42 over all 500 HOLDOUT users and shares each resample across models, seeds and views. Each replicate averages the three fixed-seed AP values, then forms the contrast. Tied scores are grouped exactly as in average precision. Percentile 95% intervals and all preregistered decision labels are reported. No multiplicity correction was preregistered.','',
      'The primary view is pooled completed windows; secondary views are TRAIN completed windows, VALIDATION completed windows, pooled offset-0 de-overlap (offset restarts within each user and period), and pooled endpoint labels. All secondary views use the same completed-window scores and frozen thresholds.','',
      '## Full results','']
    for view in results['views']:
        lines += ['### '+view,'',table(df[df.view==view]),'']
    lines += ['## All contrasts and decision rules','']
    for view in results['views']:lines += ['### '+view,'',table(contrasts[contrasts.view==view]),'']
    lines += ['## Figures and data','',
      '![Three-seed mean AP and individual seed dots](mean_AP_seed_dots.png)','',
      'Data: mean_AP_seed_dots_data.csv. Resolution: 300 dpi.','',
      '![Paired user-cluster bootstrap contrasts](contrasts_forest.png)','',
      'Data: contrasts_forest_data.csv. Resolution: 300 dpi.','',
      '## HOLDOUT explanation check','',
      f'The original deferred explanation script matched HOLDOUT_EXPLANATION_SCRIPT_HASH.txt: `{receipt["original_script_sha256"]}`. Its original bytes and frozen numerical engine were preserved. The Option C adapter hash `{receipt["adapted_script_sha256"]}` and all changes were recorded before execution in EXPLANATION_ADAPTER_RECEIPT.json. The adapter replaces the obsolete final-marker gate with the verified v2 parity freeze, uses the isolated Phase 2 TA2 loader and corrects the inherited validation-only figure title. All explanation algorithms and numerical settings remain frozen.','',
      f'The explanation pass ran once on all {selection["malicious"]:,} malicious pooled HOLDOUT windows and {selection["benign"]:,} randomly selected benign windows (RNG 20261022), covering {selection["users"]} users. References were medians from DEVELOPMENT TRAIN only; per-model logit standard deviations came from DEVELOPMENT VALIDATION only. No HOLDOUT reference fitting occurred.','',
      'The original 50-interval integrated-gradients method (51 trapezoidal nodes, eight tree outputs and final logit), TreeSHAP, same-sign interventions, 200 random subset draws and paired user-bootstrap comparisons were retained. Large IG completeness errors or weak faithfulness are reported as observed rather than suppressed. Explanation contrasts are exploratory and retain the 13-input versus 40-summary resolution difference; raw-feature sensitivity results are supplied separately.','',
      '### Paired explanation comparisons','',table(primary),'',
      '### Integrated-gradients completeness by seed, class and target','',table(ig),'',
      '### TreeSHAP additivity checks','',table(pd.DataFrame(ex['parity'])),'',
      'All intervention outcomes, eligible/excluded counts and confidence intervals are in explanation/holdout/faithfulness.csv and faithfulness.json; 13-versus-13 sensitivity is in raw_feature_sensitivity.csv. Per-feature/day attributions, source correlations and explanation figures are in the same directory.','',
      '## Skips, timeouts and deviations','']
    bad=training[training.status!='ok']
    lines += [table(bad) if len(bad) else 'No baseline was skipped, failed or timed out. All eight baselines completed three seeds.','',
      'Recorded implementation adaptations: a new deferred scorer replaces the superseded VALIDATION + TEST evaluation with TRAIN + VALIDATION and extends the frozen model list and metrics; the explanation adapter handles the superseded report marker and the isolated checkpoint loader; new baseline thresholds use the exact F1 maximum, and the existing thresholds are preserved. The original Phase 2 scorer, freeze, data pipeline, scaler and checkpoint bytes were not edited. No other authorization was needed. Nothing was pushed to GitHub.','',
      'Interpretation is bounded to unseen CERT r5.2 users in these TRAIN + VALIDATION calendar periods. The deliberately sealed TEST period is reserved for the PhD thesis. Outcomes from this post-amendment evaluation and the exploratory added baselines should be disclosed as such in the paper.','',
      'PHASE4_COMPLETE']
    report='\n'.join(lines)+'\n';assert not re.search(r'\b[A-Z]{3}\d{4}\b',report)
    (P4/'CHATGPT_PHASE4_REPORT.md').write_text(report,encoding='utf-8')
    status('PHASE4_COMPLETE',report=str(P4/'CHATGPT_PHASE4_REPORT.md'))
    dump(P4/'FINAL_VERIFICATION.json',dict(utc=utc(),complete=True,original_hashes_unchanged=True,original_preregistration_prefix_bytes=3370,original_preregistration_prefix_sha256=prefix_hash,amendments=amendments,training_runs=len(training),successful_training_runs=int((training.status=='ok').sum()),scored_model_seeds=len(f['models']),results_rows=len(df),contrast_rows=len(contrasts),explanation_completed=True,scoring_reruns=0,test_read=False,report_sha256=sha(P4/'CHATGPT_PHASE4_REPORT.md'),outputs={p.name:sha(p) for p in P4.glob('*') if p.is_file() and p.name!='FINAL_VERIFICATION.json'}))
if __name__=='__main__':main()
