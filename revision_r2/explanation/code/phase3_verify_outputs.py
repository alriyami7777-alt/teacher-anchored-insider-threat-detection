"""Post-run CPU audit of Phase 3 artefacts only. Never loads original tensors.

Do not import or run holdout_explanation_scoring.py.
"""
import os
os.environ['CUDA_VISIBLE_DEVICES']=''
os.environ['OMP_NUM_THREADS']='2'
import hashlib, json, re, sys
from pathlib import Path
sys.dont_write_bytecode=True
import numpy as np
import pandas as pd
from PIL import Image

ROOT=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision\explanation')
CODE=Path(r'C:\PhD\07_Projects\r2_explanation')
sys.path.insert(0,str(CODE))
from phase3_engine import sha256,write_json
from run_phase3 import TA_SHA,XG_SHA,TA_BASE,XG_BASE

checks={}
report=(ROOT/'CHATGPT_PHASE3_REPORT.md').read_text(encoding='utf-8-sig')
checks['report_complete']=report.rstrip().splitlines()[-1]=='PHASE3_COMPLETE'
checks['stderr_empty']=(ROOT/'WORKER_STDERR.log').stat().st_size==0
status=json.loads((ROOT/'RUN_STATUS.json').read_text())
checks['run_complete']=status['status']=='PHASE3_COMPLETE'
checks['holdout_script_not_executed']=status['holdout_explanation_script_executed'] is False
hashes=json.loads((CODE/'CODE_HASHES.json').read_text())
checks['code_output_copies_and_hashes_match']=all(sha256(CODE/n)==h==sha256(ROOT/n) for n,h in hashes.items())
checks['holdout_script_hash_matches']=(ROOT/'HOLDOUT_EXPLANATION_SCRIPT_HASH.txt').read_text().split()[0]==sha256(CODE/'holdout_explanation_scoring.py')
checks['protocol_hash_matches']=sha256(ROOT/'PHASE3_PROTOCOL.json')==(ROOT/'PHASE3_PROTOCOL_SHA256.txt').read_text().split()[0]
provenance=json.loads((ROOT/'SOURCE_PROVENANCE.json').read_text())['files']
checks['original_source_hashes_unchanged']=all(sha256(p)==h for p,h in provenance.items())
checks['all_six_checkpoint_hashes_unchanged']=all(sha256(TA_BASE/f'seed{s}/best_student.pt')==TA_SHA[s] and
   sha256(XG_BASE/f'xgboost_seed{s}/model.json')==XG_SHA[s] for s in (42,52,62))
with np.load(ROOT/'cohort_pseudonyms.npz') as z:
    users=z['user']; y=z['y']
    checks['cohort_counts']=len(y)==64000 and int(y.sum())==728 and len(np.unique(users))==2000
    checks['all_exported_users_pseudonyms']=all(re.fullmatch(r'U_[0-9a-f]{10}',u) for u in users)
    checks['32_windows_each_user']=bool(np.all(np.unique(users,return_counts=True)[1]==32))
    checks['malicious_users_31']=len(set(users[y==1]))==31
metrics=pd.read_csv(ROOT/'faithfulness.csv')
checks['all_models_seeds_levels_present']=all(len(metrics[(metrics.model==m)&(metrics.seed==s)&(metrics.level==l)])==expected
  for s in (42,52,62) for m,l,expected in [('TA2','feature',108),('TA2','source',72),
                 ('XGBoost_40','feature',108),('XGBoost_40','source',72),('XGBoost_40','raw_feature',108)])
checks['eligibility_accounting']=bool((metrics.n_eligible+metrics.n_skipped==metrics.n_total).all())
checks['all_ci_bootstrap_replicates_2000']=bool((metrics.bootstrap_valid[metrics.n_eligible>0]==2000).all())
checks['ci_order_valid']=bool((metrics.loc[metrics.n_eligible>0,'ci_low']<=metrics.loc[metrics.n_eligible>0,'ci_high']).all())
checks['metric_estimates_finite_when_eligible']=bool(np.isfinite(metrics.loc[metrics.n_eligible>0,'estimate']).all())
details={}
for s in (42,52,62):
    with np.load(ROOT/f'ig_seed{s}.npz') as z:
        ig=z['ig']; delta=z['differences']; residual=z['residual']; rel=z['relative']
        checks[f'ig_{s}_shape_finite']=ig.shape==(64000,9,20,13) and bool(np.isfinite(ig).all())
        # Recompute completeness directly from exported full input attributions.
        recovered=ig.astype(np.float64).sum((2,3))-delta
        checks[f'ig_{s}_completeness_reproduces']=bool(np.allclose(recovered,residual,atol=1e-12)) and bool(np.allclose(np.abs(residual)/np.maximum(np.abs(delta),1e-6),rel))
        details[f'ig_{s}_final_median_relative_error']=float(np.median(rel[:,-1]))
    del ig,delta,residual,rel,recovered
    with np.load(ROOT/f'xgboost_shap_seed{s}.npz') as z:
        shap=z['contributions']; margins=z['margins']
        checks[f'TreeSHAP_{s}_shape_additive']=shap.shape==(64000,41) and bool(np.allclose(shap.sum(1),margins,atol=1e-3))
    for model,levels in [('TA2',('feature','source')),('XGBoost_40',('feature','source','raw_feature'))]:
        for level in levels:
            with np.load(ROOT/f'{model}_seed{s}_{level}_interventions.npz') as z:
                checks[f'{model}_{s}_{level}_complete_arrays']=len(z.files)==(16 if level=='source' else 24) and all(z[k].shape==(64000,) for k in z.files)
figures={}
for name in ('integrated_gradients.png','faithfulness.png'):
    with Image.open(ROOT/name) as im:
        figures[name]={'pixels':list(im.size),'dpi':im.info.get('dpi')}
        checks[name+'_300_dpi']=min(im.info.get('dpi',(0,0)))>=299.9
all_texts=[p for p in ROOT.iterdir() if p.is_file() and p.suffix in ('.py','.json','.csv','.md','.txt','.log')]
# CERT usernames have three uppercase letters followed by four digits. Do not
# emit any candidate match or its surrounding text if a check fails.
checks['no_CERT_ID_patterns_in_text_outputs']=all(re.search(r'\b[A-Z]{3}\d{4}\b',p.read_text(encoding='utf-8-sig')) is None for p in all_texts)
faith=json.loads((ROOT/'faithfulness.json').read_text())
primary=[r for r in faith['primary_comparison'] if r['seed']=='mean_of_seeds' and r['sign']=='class_supporting']
raw=[r for r in faith['raw_feature_sensitivity'] if r['seed']=='mean_of_seeds' and r['sign']=='class_supporting']
results={'checks':checks,'all_pass':all(checks.values()),'completeness':details,
         'primary':primary,'raw_feature_sensitivity':raw,'parity':faith['parity'],'figures':figures,
         'metric_rows':len(metrics),'skipped_metric_rows':int((metrics.n_eligible==0).sum())}
write_json(ROOT/'FINAL_VERIFICATION.json',results)
print(json.dumps(results,indent=2))
raise SystemExit(0 if results['all_pass'] else 1)
