"""Unattended Phase 3; originals read-only; GPU behind exact Phase 2 marker."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time
sys.dont_write_bytecode=True
os.environ.setdefault('OMP_NUM_THREADS','2')
os.environ.setdefault('MKL_NUM_THREADS','2')
import numpy as np
from phase3_engine import *

PROJECTS=Path(r'C:\PhD\07_Projects')
REPO=PROJECTS/'teacher-anchored-insider-threat-detection-editor023'
OUT=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision\explanation')
PHASE2=OUT.parent/'holdout/CHATGPT_PHASE2_REPORT.md'
MARKER='PHASE2_COMPLETE_MODELS_FROZEN_NOT_SCORED'
DATA=PROJECTS/'cert-r42-feasibility/data/processed/r5.2/tensors'
TRAIN_SHA='b268328d3bf2e98f712d1145958dabe175ce2c07a7c390da4b84a663317ebc2e'
VAL_SHA='5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c'
USER_SHA='851385f9c926cf945b3c74b5c9442e3ccb94cf1d9dabb98106a29cbfea01c5c0'
TA_SHA={42:'54f6c097af9568a4ee5701ef375559a2f649cec6c1817e578d3e8e01e6d73df8',
        52:'7613ba559bcf55827d04129066eb595b677994494609646f8b2463308ed5edb4',
        62:'904003dca219435464476cf36abedb11ee4e2f7a11ff09caa3791d685b8f644d'}
XG_SHA={42:'2109554164abdd002ce0a4377f957c5aa3bc26886a197749ea79fc04d9b94fae',
        52:'0f32857232341cb6a26d6cf55cb2375b8e256e0e0f89519d3059415cac8ad7e6',
        62:'3062488680b8bc05959ddcb0cab948378988564fc82a88213e346ca570b0c7ab'}
TA_BASE=PROJECTS/'teacher-anchored-insider-threat-detection-editor012/outputs/editor012_teacher_anchor_rescue/F11_DROPT'
XG_BASE=PROJECTS/'cert-r52-locked-baselines/outputs/objective2/r52_locked_baselines'

def utc(): return dt.datetime.now(dt.timezone.utc).isoformat()

def log(message,out=OUT):
    line=f'{utc()} {message}'
    print(line,flush=True)
    with (out/'RUN_LOG.txt').open('a',encoding='utf-8') as f: f.write(line+'\n')

def gate_ready(path=PHASE2):
    # No model or tensor access needed. Ignore only trailing newline/whitespace.
    if not path.is_file(): return False
    content=path.read_text(encoding='utf-8-sig').rstrip()
    return bool(content) and content.splitlines()[-1]==MARKER

def wait_for_phase2():
    while not gate_ready():
        log('WAITING_PHASE2 exact completion marker absent; GPU not accessed; next check in 600 seconds')
        write_json(OUT/'RUN_STATUS.json',{'status':'WAITING_PHASE2','updated_utc':utc(),
                   'gpu_accessed':False,'holdout_explanation_script_executed':False,'next_check_seconds':600})
        time.sleep(600)
    write_json(OUT/'GPU_GATE_RELEASE.json',{'time_utc':utc(),'report':str(PHASE2),
               'sha256':sha256(PHASE2),'required_final_marker':MARKER,'satisfied':True})
    log('PHASE2 marker verified; original-model explanation inference may start')
    write_json(OUT/'RUN_STATUS.json',{'status':'RUNNING_ORIGINAL_VALIDATION','updated_utc':utc(),
               'phase2_gate_satisfied':True,'holdout_explanation_script_executed':False})

def protocol():
    return {'task':'PHASE3','created_utc':utc(),'training':False,'test_data':False,'holdout_scoring_executed':False,
      'cohort':{'release':'r5.2','partition':'original VALIDATION','n_sequences':64000,'n_users':2000,
                'malicious_windows':728,'benign_windows':63272,'malicious_users':31,'windows_per_user':32,
                'validation_npz_sha256':VAL_SHA,'user_order_sha256':USER_SHA,
                'definition_file':str(REPO/'src/editor017_robustness/campaign.py'),
                'definition_function':'run_campaign: load_train_validation, recover_user_mapping, directional_table',
                'constants_file':str(REPO/'src/editor012_rescue/constants.py'),
                'directional_definition_file':str(REPO/'src/editor015_residual/explain.py'),
                'editor017_commit':'c75321a627ecc7539d1a759764d7ce395895179a',
                'editor023_commit':'a480fa2413cf0b70c398081ca5f8f52470a665a3',
                'historical_eligibility':'per seed and k, malicious positive trees; benign negative trees; insufficient signs excluded',
                'new_eligibility':'same frozen population, both signs in each class; inputs replace trees; insufficient signs excluded'},
      'manuscript_inconsistency':'484 windows / 151 users / 242 positives / 242 negatives belongs to r4.2 in objective3_missing_source_robustness.py, not the r5.2 EDITOR-017/023 cohort. Claude clarified use of actual r5.2 cohort on 2026-10-21.',
      'ig':{'steps':50,'quadrature':'composite trapezoid, 50 intervals / 51 endpoints',
            'targets':'8 raw tree outputs and final logit','input':[20,13],
            'baseline':'median over all original r5.2 TRAIN day rows per scaled feature, broadcast to all 20 days; paper intervention convention',
            'completeness':'abs(sum(IG)-[f(x)-f(b)])/max(abs(f(x)-f(b)),1e-6); report per-target/class median, p95, absolute residual and near-zero counts'},
      'interventions':{'feature_k':[1,3,5],'source_k':[1,2],'random_draws':200,
          'TA2_feature_unit':'one of 13 raw features, summed signed IG over 20 days; replace all 20 days',
          'XGBoost_feature_unit':'one of 40 locked window summaries; replace summary with TRAIN median',
          'raw_feature_sensitivity':'XGBoost 40 summaries grouped to 13 raw features; replace all summaries in group',
          'signs':'positive and negative, separately, for every label stratum',
          'random_control':'200 independent uniform subsets without replacement within subset, from same-sign eligible units; duplicates retained with multiplicity and scored once',
          'directional_accuracy':'strictly positive expected signed margin change; zero changes count as failures',
          'normalization':'population standard deviation (ddof=0) of each original model/seed over all 64000 validation logits/margins',
          'source_mapping':dict(zip(SOURCES,[list(g) for g in SOURCE_FEATURES])),
          'shared_raw_features_excluded_from_source_analysis':[FEATURES[j] for j in (0,6,12)],
          'shared_summary_features_excluded':10,'source_analysis_summary_features_included':30,
          'physical_validity':'local model-input interventions; derived constraints not recomputed; not a physical sensor-removal simulation'},
      'bootstrap':{'replicates':2000,'rng':42,'unit':'pseudonymised user',
                   'ci':'percentile 95%; sequence-weighted mean after resampling whole user clusters',
                   'pairing':'shared user resample across model contrast, random control, and all three fixed seeds; jointly eligible windows only'},
      'primary_exploratory':{'contrast':'TA2 minus XGBoost directional accuracy at feature k=3',
             'strata':['overall','malicious'],'sign':'class-supporting: positive for malicious / negative for benign',
             'secondary':'both signs separately and TA2-minus-XGBoost difference of random-control gaps',
             'seed_aggregation':'equal-seed mean on windows eligible in both models in all 3 seeds; seedwise also reported',
             'limitation':'primary feature resolution is 13 versus 40 inputs; raw-feature 13-versus-13 sensitivity also reported; exploratory, no superiority claim implied'},
      'source_removal_rank':['file','device','logon','web','email'],'source_spearman':'sum mean |IG| over direct source count/presence channels; shared channels excluded',
      'frozen_model_hashes':{'TA2':TA_SHA,'XGBoost_40':XG_SHA},
      'gpu_gate':{'path':str(PHASE2),'endswith':MARKER,'poll_seconds':600},
      'identifier_rule':'U_ + first 10 hex characters of SHA-256(original user ID); raw sequence IDs omitted'}

class TAForward:
    def __init__(self,path,expected,device):
        import torch
        checked(path,expected)
        if str(REPO/'src') not in sys.path: sys.path.insert(0,str(REPO/'src'))
        from editor012_rescue.producing import build_odst046_model,load_state_dict
        from editor012_rescue.models import student_forward
        self.model=build_odst046_model(); load_state_dict(self.model,path,strict=True)
        self.model.to(device).eval()
        for p in self.model.parameters(): p.requires_grad_(False)
        self.device=device; self.torch=torch; self.student_forward=student_forward
    def __call__(self,z):
        out=self.student_forward(self.model,z)
        return self.torch.cat((out['tree_outputs'],out['logit'][:,None]),1)
    def predict(self,x):
        out=[]
        with self.torch.no_grad():
            for i in range(0,len(x),2048):
                out.append(self(self.torch.as_tensor(x[i:i+2048],dtype=self.torch.float32,device=self.device))[:,-1].cpu().numpy())
        return np.concatenate(out).astype(np.float64)

class XGForward:
    def __init__(self,path,expected):
        import xgboost as xgb
        self.xgb=xgb; checked(path,expected)
        self.model=xgb.Booster(params={'nthread':2,'device':'cpu'})
        self.model.load_model(path); self.model.set_param({'nthread':2,'device':'cpu'})
        if self.model.num_features()!=40: raise RuntimeError('Expected frozen 40-feature XGBoost')
    def predict(self,x):
        return self.model.predict(self.xgb.DMatrix(x),output_margin=True).astype(np.float64)
    def contributions(self,x):
        return self.model.predict(self.xgb.DMatrix(x),pred_contribs=True).astype(np.float64)

def load_original_data():
    checked(DATA/'r52_T20_s1_validation.npz',VAL_SHA)
    checked(DATA/'r52_T20_s1_train.npz',TRAIN_SHA)
    with np.load(DATA/'r52_T20_s1_validation.npz',allow_pickle=True) as z:
        x=np.asarray(z['X'],np.float32); y=np.asarray(z['y'],int).ravel()
        raw=np.asarray(z['user']).astype(str)
        if tuple(map(str,z['feature_names'].tolist()))!=FEATURES: raise RuntimeError('Validation schema mismatch')
    if x.shape!=(64000,20,13) or y.sum()!=728: raise RuntimeError('Frozen validation population mismatch')
    if hashlib.sha256('\n'.join(raw.tolist()).encode()).hexdigest()!=USER_SHA: raise RuntimeError('Frozen validation user ordering mismatch')
    users=np.array([pseudonym(u) for u in raw]); del raw
    if len(set(users))!=2000: raise RuntimeError('User count or pseudonym collision')
    if not np.isfinite(x).all(): raise RuntimeError('Nonfinite original validation input')
    with np.load(DATA/'r52_T20_s1_train.npz',allow_pickle=False) as z:
        train=np.asarray(z['X'],np.float32)
    if train.shape!=(788000,20,13): raise RuntimeError('Frozen TRAIN shape mismatch')
    # Columnwise medians keep peak temporary memory below a full tensor copy.
    med=np.array([np.median(train[:,:,j]) for j in range(13)],np.float32)
    baseline=np.broadcast_to(med,(20,13)).copy()
    summary=aggregate40(train); xg_baseline=np.median(summary,axis=0).astype(np.float32)
    del train,summary
    write_json(OUT/'TRAIN_REFERENCES.json',{'train_sha256':TRAIN_SHA,
               'TA2_scaled_feature_medians':dict(zip(FEATURES,med)),
               'TA2_baseline_sequence':baseline,'XGBoost_summary_medians':dict(zip(SUMMARY_NAMES,xg_baseline)),
               'validation_statistics_used_for_reference':False})
    return x,y,users,baseline,xg_baseline

def save_results(path,results):
    np.savez_compressed(path,**{f'k{k}_s{sign}_{key}':value for (k,sign),r in results.items() for key,value in r.items()})

def load_results(path):
    out={}
    with np.load(path) as z:
        for key in z.files:
            a,b,name=key.split('_',2); out.setdefault((int(a[1:]),int(b[1:])),{})[name]=z[key]
    return out

def analyze(x,y,users,baseline,xg_baseline,ta_specs,xg_specs,device,out=OUT,validation_spreads=None,original_parity=True):
    import pandas as pd
    all_features=[]; all_days=[]; completeness=[]; top=[]; sources=[]; metrics=[]
    primary_ta={}; primary_xg={}; raw_xg={}; parity=[]
    summaries=aggregate40(x)
    np.savez_compressed(out/'cohort_pseudonyms.npz',user=users,y=y,window_index=np.arange(len(y)))
    for seed in SEEDS:
        log(f'TA2 seed={seed}: loading hash-gated frozen original model',out)
        forward=TAForward(ta_specs[seed]['path'],ta_specs[seed]['sha256'],device)
        logits=forward.predict(x)
        if original_parity:
            frozen=np.load(TA_BASE/f'seed{seed}/val_logits.npy').ravel()
            error=float(np.max(np.abs(logits-frozen)))
            parity.append({'model':'TA2','seed':seed,'max_abs_logit_error':error})
            if error>5e-4: raise RuntimeError('Frozen TA2 validation logit parity failed')
        spread=float(np.std(logits)) if validation_spreads is None else validation_spreads['TA2'][seed]
        target=out/f'ig_seed{seed}.npz'
        if target.exists():
            with np.load(target) as z: attrs=z['ig']; differences=z['differences']; residual=z['residual']; relative=z['relative']
        else:
            last=[0.0]
            def progress(done,total):
                if time.monotonic()-last[0]>60 or done==total:
                    log(f'TA2 seed={seed}: IG {done}/{total} windows',out); last[0]=time.monotonic()
            attrs,differences,residual,relative=integrated_gradients(forward,x,baseline,progress=progress)
            np.savez_compressed(target,ig=attrs,differences=differences,residual=residual,relative=relative)
        f,d,c,t,s=ig_summary(attrs,y,seed,relative,residual,differences)
        all_features+=f; all_days+=d; completeness+=c; top+=t; sources+=s
        attribution=attrs[:,-1].sum(1); del attrs,differences,residual,relative
        for level,ks in [('feature',(1,3,5)),('source',(1,2))]:
            target=out/f'TA2_seed{seed}_{level}_interventions.npz'
            if target.exists(): result=load_results(target)
            else:
                last=[0.0]
                def progress(k,sign,done,total):
                    if time.monotonic()-last[0]>60 or done==total:
                        log(f'TA2 seed={seed}: {level} k={k} sign={sign} {done}/{total}',out); last[0]=time.monotonic()
                result=interventions(forward.predict,x,baseline,attribution,group_columns('TA2',level),ks,progress=progress)
                save_results(target,result)
            metrics+=summarize_interventions(result,users,y,spread,'TA2',seed,level)
            if level=='feature': primary_ta[seed]=result
        # Hash proves no checkpoint was modified by explanation computation.
        checked(ta_specs[seed]['path'],ta_specs[seed]['sha256'])
        del forward,attribution
        log(f'XGBoost_40 seed={seed}: frozen TreeSHAP and interventions',out)
        xg=XGForward(xg_specs[seed]['path'],xg_specs[seed]['sha256'])
        margin=xg.predict(summaries); shap=xg.contributions(summaries)
        error=float(np.max(np.abs(shap.sum(1)-margin)))
        parity.append({'model':'XGBoost_40','seed':seed,'TreeSHAP_completeness_max_abs_error':error})
        if error>1e-3: raise RuntimeError('TreeSHAP margin additivity failed')
        if original_parity:
            with np.load(XG_BASE/f'xgboost_seed{seed}/validation_probabilities.npz') as z: saved=z['y_proba']
            actual=1/(1+np.exp(-margin)); prob_error=float(np.max(np.abs(saved-actual)))
            parity[-1]['validation_probability_parity_max_abs_error']=prob_error
            if prob_error>1e-5: raise RuntimeError('Frozen XGBoost validation parity failed')
        spread=float(np.std(margin)) if validation_spreads is None else validation_spreads['XGBoost_40'][seed]
        np.savez_compressed(out/f'xgboost_shap_seed{seed}.npz',contributions=shap,margins=margin)
        for level,ks in [('feature',(1,3,5)),('source',(1,2)),('raw_feature',(1,3,5))]:
            target=out/f'XGBoost_40_seed{seed}_{level}_interventions.npz'
            if target.exists(): result=load_results(target)
            else:
                result=interventions(xg.predict,summaries,xg_baseline,shap[:,:-1],group_columns('XGBoost_40',level),ks,
                                     sequence_batch=128,prediction_batch=16384)
                save_results(target,result)
            metrics+=summarize_interventions(result,users,y,spread,'XGBoost_40',seed,level)
            if level=='feature': primary_xg[seed]=result
            if level=='raw_feature': raw_xg[seed]=result
        checked(xg_specs[seed]['path'],xg_specs[seed]['sha256'])
        pd.DataFrame(metrics).to_csv(out/'faithfulness.partial.csv',index=False)
    primary=paired_primary(primary_ta,primary_xg,users,y)
    sensitivity=paired_primary(primary_ta,raw_xg,users,y)
    pd.DataFrame(all_features).to_csv(out/'integrated_gradients_features.csv',index=False)
    pd.DataFrame(all_days).to_csv(out/'integrated_gradients_days.csv',index=False)
    pd.DataFrame(completeness).to_csv(out/'integrated_gradients_completeness.csv',index=False)
    pd.DataFrame(metrics).to_csv(out/'faithfulness.csv',index=False)
    pd.DataFrame(primary).to_csv(out/'primary_comparison.csv',index=False)
    pd.DataFrame(sensitivity).to_csv(out/'raw_feature_sensitivity.csv',index=False)
    write_json(out/'integrated_gradients.json',{'completeness':completeness,'top3_features':top,'source_correlations':sources,
               'feature_aggregates':all_features,'day_aggregates':all_days})
    write_json(out/'faithfulness.json',{'metrics':metrics,'primary_comparison':primary,'raw_feature_sensitivity':sensitivity,'parity':parity})
    figures(out,all_features,all_days,metrics,primary)
    return completeness,primary,parity

def completion_report(complete,primary,parity):
    p=protocol(); lines=['# PHASE 3 — explanation evidence','',
      'Completed UTC: '+utc(),'',
      '## Scope and frozen cohort','',
      'Used only the original frozen TA2/F11 and XGBoost_40 models, seeds 42, 52, 62. No training, GitHub push, TEST data, r5.1, r6.1 or r6.2 data, or Phase 2 holdout scoring. Existing repositories and worktrees were read only.',
      '',f'GPU start was gated on `{MARKER}` as the final nonblank text of `{PHASE2}`. The gate record and report hash are in GPU_GATE_RELEASE.json.',
      '', 'The cohort is all **64,000 original r5.2 VALIDATION windows from 2,000 users**, with 728 malicious and 63,272 benign labels (31 users with malicious windows; 32 windows per user). Sign eligibility is applied separately by seed, k, model and sign. All exclusions are in faithfulness.csv; paired comparisons use jointly eligible windows.',
      '',f'Definition: `{REPO}/src/editor017_robustness/campaign.py`, `run_campaign`, with `recover_user_mapping` and `editor012_rescue/data.py::load_train_validation`; identities and counts: `src/editor012_rescue/constants.py`. Local signed selection: `src/editor015_residual/explain.py::directional_table`.',
      '', 'EDITOR-017 commit: c75321a627ecc7539d1a759764d7ce395895179a. EDITOR-023 commit: a480fa2413cf0b70c398081ca5f8f52470a665a3. EDITOR-023 uses the same validation population and training references for its explanation stability analysis; its source does not define a new 484-window cohort.',
      '', '**Manuscript inconsistency:** 484 windows / 151 users is an r4.2 definition in `src/objective3_missing_source_robustness.py` (242 malicious / 242 benign), not the r5.2 EDITOR-017/023 population. Claude explicitly clarified using the actual r5.2 cohort. No r4.2 tensors or checkpoints were loaded.',
      '', '## Step 1 — Integrated Gradients','',
      '50 intervals with composite trapezoid integration (51 evaluation nodes), from each raw tree output and final logit to the 20×13 scaled input. Baseline: original r5.2 TRAIN median over all day rows per feature, broadcast over 20 days, matching the paper feature intervention convention. TRAIN_REFERENCES.json records all values. No validation statistic defines the reference.',
      '', 'Completeness median relative errors (overall; denominator floored at 1e-6):']
    for seed in SEEDS:
        rows=[r for r in complete if r['seed']==seed and r['stratum']=='overall']
        lines.append('- Seed '+str(seed)+': '+', '.join(f"{r['target']}={r['median_relative_error']:.6g}" for r in rows))
    ig=json.loads((OUT/'integrated_gradients.json').read_text())
    lines+=['','Source-level Spearman correlation with file > device > logon > web > email (final-logit IG):']
    for seed in SEEDS:
        values=[r for r in ig['source_correlations'] if r['seed']==seed and r['target']=='final_logit']
        lines.append('- Seed '+str(seed)+': '+', '.join(f"{r['stratum']}={r['spearman_vs_source_removal']}" for r in values))
    lines+=['','Full errors, absolute residuals, near-zero denominator counts, malicious/benign aggregates, top-three features per tree and source-level Spearman correlations are in integrated_gradients.json and the three IG CSVs. Figure: integrated_gradients.png (300 dpi). The five-source comparison uses direct count/presence channels; total events, duration and active-day flags are shared and excluded, with their attribution mass reported separately.','','## Step 2 — local input faithfulness','',
      'Both signs were evaluated in each label stratum. The expected change is logit decrease for positive inputs and increase for negative inputs. Zero changes fail directionality. Random controls average 200 independent same-sign random k-subsets per sequence (duplicates retain their sampling multiplicity). Margin changes are divided by the population SD of each model/seed across original validation logits. CIs use 2,000 paired whole-user cluster bootstrap replicates, RNG 42, with window weighting after cluster resampling.',
      '', 'Exploratory primary contrast: TA2 minus XGBoost directional accuracy at feature k=3, class-supporting sign (positive for malicious labels; negative for benign). Equal-seed mean uses jointly eligible windows in all three seeds:']
    for r in primary:
        if r['seed']=='mean_of_seeds' and r['sign']=='class_supporting' and r['metric']=='TA2_minus_XGBoost_directional_accuracy':
            lines.append(f"- {r['stratum']}: {r['estimate']:.6f}, 95% CI [{r['ci_low']:.6f}, {r['ci_high']:.6f}], n={r['n_paired']} paired windows.")
    lines+=['','All seed/sign/k/stratum outcomes, random gaps, exclusions and CIs appear in faithfulness.csv/json, primary_comparison.csv, and faithfulness.png (300 dpi). The primary comparison has different input resolution: 13 TA2 raw features versus 40 XGBoost summaries, as requested. A parallel XGBoost analysis grouping summaries to 13 raw features is in raw_feature_sensitivity.csv. Source-level analysis uses five comparable direct source groups. These are local input interventions, not a physical source-removal simulation; derived-feature constraints are not recomputed. No outcome was selected or suppressed based on which model performed better.','','## Step 3 — HOLDOUT preparation only','',
      'holdout_explanation_scoring.py was written and SHA-256 hashed, and was not run. Its hash is in HOLDOUT_EXPLANATION_SCRIPT_HASH.txt. It requires explicit scoring execution and a hash-bound scoring manifest; it selects all malicious HOLDOUT windows plus an equal-sized random benign sample, RNG 20261022. It requires training-only references and validation-only logit spreads from the retrained models and does not derive those from HOLDOUT data. The dependency hashes are also recorded so the same engine can be verified at scoring time. No Phase 2 HOLDOUT data or models were opened by this phase.',
      '', '## Validation and limitations','',
      'Synthetic CPU tests cover exact linear IG, completeness, sign handling, replacement semantics, same-sign random controls, grouping, user clustering, paired comparison, the GPU gate, and pseudonymisation. Frozen TA2 logit and XGBoost probability parity, TreeSHAP additivity, and checkpoint hashes were checked during execution; details are in faithfulness.json. Complete protocol and source hashes were frozen before results were computed. Sparse sign eligibility and any large 50-step IG completeness errors must be considered when interpreting the results; all are disclosed. No extra Qasim approval was required and no requested outcome was skipped.',
      '', 'PHASE3_COMPLETE']
    (OUT/'CHATGPT_PHASE3_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('MPLCONFIGDIR',str(OUT/'matplotlib_cache'))
    if (OUT/'CHATGPT_PHASE3_REPORT.md').exists() and (OUT/'CHATGPT_PHASE3_REPORT.md').read_text().rstrip().endswith('PHASE3_COMPLETE'):
        raise RuntimeError('Phase 3 already complete; refusing implicit rerun')
    if not (OUT/'PHASE3_PROTOCOL.json').exists(): write_json(OUT/'PHASE3_PROTOCOL.json',protocol())
    wait_for_phase2()
    import torch
    torch.set_num_threads(2)
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    log(f'Numerical execution device={device}; no training')
    x,y,users,base,xbase=load_original_data()
    ta={s:{'path':TA_BASE/f'seed{s}/best_student.pt','sha256':TA_SHA[s]} for s in SEEDS}
    xg={s:{'path':XG_BASE/f'xgboost_seed{s}/model.json','sha256':XG_SHA[s]} for s in SEEDS}
    complete,primary,parity=analyze(x,y,users,base,xbase,ta,xg,device)
    completion_report(complete,primary,parity)
    write_json(OUT/'RUN_STATUS.json',{'status':'PHASE3_COMPLETE','updated_utc':utc(),
               'phase2_gate_satisfied':True,'holdout_explanation_script_executed':False})
    log('PHASE3_COMPLETE')

if __name__=='__main__':
    try:
        # Keep this unattended run awake; Windows clears the request on exit.
        if os.name=='nt':
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        main()
    except Exception as e:
        # Do not emit traceback or exception data that could include raw input IDs.
        OUT.mkdir(parents=True,exist_ok=True)
        write_json(OUT/'RUN_FAILURE.json',{'time_utc':utc(),'exception_type':type(e).__name__,
                   'message':'Phase 3 stopped; no completion marker emitted. Inspect identifier-free stage log and source checks.'})
        write_json(OUT/'RUN_STATUS.json',{'status':'FAILED','updated_utc':utc(),
                   'exception_type':type(e).__name__,'holdout_explanation_script_executed':False})
        log('FAILED '+type(e).__name__+' (details suppressed to prevent input-ID disclosure)')
        raise SystemExit(1)
    finally:
        if os.name=='nt':
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
