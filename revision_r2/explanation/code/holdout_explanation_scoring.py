"""PREPARED ONLY: explicitly execute at authorised Phase 2 HOLDOUT scoring time.

No training. No discovery of HOLDOUT paths or identities. A scoring manifest must
be supplied explicitly and bind every artifact to a SHA-256. The Phase 3 author
must not execute this file, including --help. See HOLDOUT_MANIFEST_SCHEMA.json.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import sys
sys.dont_write_bytecode=True
os.environ.setdefault('OMP_NUM_THREADS','2')
os.environ.setdefault('MKL_NUM_THREADS','2')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True,type=Path)
    p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--execute-authorised-holdout-scoring',action='store_true',required=True)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    from phase3_engine import checked,sha256,pseudonym,SEEDS,write_json
    # Verify frozen numerical implementation before importing the runner.
    here=Path(__file__).resolve().parent
    hashes=json.loads((here/'CODE_HASHES.json').read_text())
    for name in ('phase3_engine.py','run_phase3.py','holdout_explanation_scoring.py'):
        checked(here/name,hashes[name])
    checked(args.manifest,args.manifest_sha256)
    cfg=json.loads(args.manifest.read_text(encoding='utf-8'))
    if cfg['release']!='r5.2' or cfg['partition']!='HOLDOUT': raise RuntimeError('Expected explicit r5.2 HOLDOUT scoring manifest')
    if cfg.get('scoring_authorised') is not True: raise RuntimeError('HOLDOUT scoring authorisation not recorded')
    from run_phase3 import analyze,gate_ready,TA_SHA,XG_SHA
    if not gate_ready(): raise RuntimeError('Phase 2 model-freeze marker missing')
    for family in ('TA2','XGBoost_40'):
        if set(cfg['models'][family])!={str(s) for s in SEEDS}: raise RuntimeError('Exactly three frozen seeds required')
        for s in SEEDS:
            c=cfg['models'][family][str(s)]
            if c['training_population']!='phase2_non_holdout_train': raise RuntimeError('Retrained non-HOLDOUT models required')
            if c['sha256'] in set(TA_SHA.values())|set(XG_SHA.values()): raise RuntimeError('Original model is not a retrained holdout model')
            checked(c['path'],c['sha256'])
    for item in (cfg['cohort'],cfg['references']): checked(item['path'],item['sha256'])
    import numpy as np
    # Load only the explicitly provided HOLDOUT bundle at authorised scoring time.
    with np.load(cfg['cohort']['path'],allow_pickle=True) as z:
        x=np.asarray(z['X'],np.float32); y=np.asarray(z['y'],int).ravel()
        raw=np.asarray(z['user']).astype(str)
    if x.shape!=(len(y),20,13) or not np.isin(y,[0,1]).all(): raise RuntimeError('HOLDOUT bundle schema mismatch')
    users=np.array([u if re.fullmatch(r'U_[0-9a-f]{10}',u) else pseudonym(u) for u in raw]); del raw
    malicious=np.flatnonzero(y==1); benign=np.flatnonzero(y==0)
    if not len(malicious) or len(benign)<len(malicious): raise RuntimeError('Cannot form required equal-sized benign sample')
    rng=np.random.default_rng(20261022)
    take=np.sort(np.concatenate((malicious,rng.choice(benign,len(malicious),replace=False))))
    x=x[take]; y=y[take]; users=users[take]
    refs=json.loads(Path(cfg['references']['path']).read_text())
    if refs['reference_population']!='phase2_non_holdout_train' or refs['spread_population']!='phase2_validation_non_holdout':
        raise RuntimeError('HOLDOUT-derived references or spreads are prohibited')
    # Each seed may have its own scaler and model-specific reference. Analyze
    # requires shared coordinates; refuse a schema that would silently mix them.
    if refs.get('shared_scaled_coordinates_across_seeds') is not True: raise RuntimeError('Seed-specific scaling needs an explicit adapter')
    baseline=np.asarray(refs['TA2_baseline_sequence'],np.float32)
    xbase=np.asarray(refs['XGBoost_summary_medians'],np.float32)
    if baseline.shape!=(20,13) or xbase.shape!=(40,): raise RuntimeError('Reference shape mismatch')
    if not refs.get('holdout_X_uses_this_scaler_sha256')==cfg['cohort'].get('scaler_sha256'):
        raise RuntimeError('HOLDOUT scaler identity mismatch')
    spreads={f:{s:float(refs['validation_logit_sd'][f][str(s)]) for s in SEEDS} for f in ('TA2','XGBoost_40')}
    ta={s:cfg['models']['TA2'][str(s)] for s in SEEDS}
    xg={s:cfg['models']['XGBoost_40'][str(s)] for s in SEEDS}
    args.output.mkdir(parents=True,exist_ok=False)
    write_json(args.output/'HOLDOUT_SELECTION.json',{'sampling_rng':20261022,'malicious':len(malicious),
         'benign':len(malicious),'users':len(set(users)), 'source_manifest_sha256':args.manifest_sha256,
         'selected_bundle_row_indices':take,'script_sha256':sha256(__file__), 'holdout_scoring_executed':True})
    import torch
    torch.set_num_threads(2)
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    analyze(x,y,users,baseline,xbase,ta,xg,device,out=args.output,
            validation_spreads=spreads,original_parity=False)
    write_json(args.output/'HOLDOUT_EXPLANATION_COMPLETE.json',{'complete':True,'script_sha256':sha256(__file__)})

if __name__=='__main__': main()
