"""Recorded adaptation of the Phase 3 deferred scorer for authorised Option C."""
from common import *
import argparse,re
def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True,type=Path);p.add_argument('--manifest-sha256',required=True);p.add_argument('--execute-authorised-holdout-scoring',action='store_true',required=True);p.add_argument('--output',required=True,type=Path);args=p.parse_args()
    receipt=json.loads((P4/'EXPLANATION_ADAPTER_RECEIPT.json').read_text());assert sha(__file__)==receipt['adapted_script_sha256'];assert sha(args.manifest)==args.manifest_sha256==receipt['manifest_sha256']
    sys.path.insert(0,str(EXPL));from phase3_engine import checked,pseudonym,write_json
    hashes=json.loads((EXPL/'CODE_HASHES.json').read_text())
    for name in ('phase3_engine.py','run_phase3.py','holdout_explanation_scoring.py'):checked(EXPL/name,hashes[name])
    verify_original();cfg=json.loads(args.manifest.read_text());assert cfg['release']=='r5.2' and cfg['partition']=='HOLDOUT' and cfg['scoring_authorised'] and cfg['evaluation_periods']==['train','validation'] and cfg['test_sealed']
    import run_phase3 as runner
    for family in ('TA2','XGBoost_40'):
        assert set(cfg['models'][family])=={str(s) for s in SEEDS}
        for s in SEEDS:
            c=cfg['models'][family][str(s)];assert c['training_population']=='phase2_non_holdout_train';assert c['sha256'] not in set(runner.TA_SHA.values())|set(runner.XG_SHA.values());checked(c['path'],c['sha256'])
    for item in (cfg['cohort'],cfg['references']):checked(item['path'],item['sha256'])
    import numpy as np,torch
    with np.load(cfg['cohort']['path'],allow_pickle=False) as z:
        x=np.asarray(z['X'],np.float32);y=np.asarray(z['y'],int).ravel();raw=np.asarray(z['user']).astype(str);partition=z['partition']
    assert x.shape==(213000,20,13) and len(y)==213000 and y.sum()==1172 and set(partition)=={'train','validation'}
    users=np.array([u if re.fullmatch(r'U_[0-9a-f]{10}',u) else pseudonym(u) for u in raw]);del raw
    malicious=np.flatnonzero(y==1);benign=np.flatnonzero(y==0);assert len(benign)>=len(malicious)>0
    rng=np.random.default_rng(20261022);take=np.sort(np.concatenate((malicious,rng.choice(benign,len(malicious),replace=False))));x=x[take];y=y[take];users=users[take]
    refs=json.loads(Path(cfg['references']['path']).read_text());assert refs['reference_population']=='phase2_non_holdout_train' and refs['spread_population']=='phase2_validation_non_holdout' and refs['shared_scaled_coordinates_across_seeds']
    baseline=np.asarray(refs['TA2_baseline_sequence'],np.float32);xbase=np.asarray(refs['XGBoost_summary_medians'],np.float32);assert baseline.shape==(20,13) and xbase.shape==(40,)
    assert refs['holdout_X_uses_this_scaler_sha256']==cfg['cohort']['scaler_sha256']
    spreads={f:{s:float(refs['validation_logit_sd'][f][str(s)]) for s in SEEDS} for f in ('TA2','XGBoost_40')};ta={s:cfg['models']['TA2'][str(s)] for s in SEEDS};xg={s:cfg['models']['XGBoost_40'][str(s)] for s in SEEDS}
    args.output.mkdir(parents=True,exist_ok=False)
    write_json(args.output/'HOLDOUT_SELECTION.json',dict(sampling_rng=20261022,malicious=len(malicious),benign=len(malicious),users=len(set(users)),source_manifest_sha256=args.manifest_sha256,selected_bundle_row_indices=take,script_sha256=sha(__file__),holdout_scoring_executed=True,evaluation_periods=['train','validation'],test_read=False))
    import phase2_runtime as rt
    class IsolatedTA(runner.TAForward):
        def __init__(self,path,expected,device):
            checked(path,expected);seed=next(s for s in SEEDS if cfg['models']['TA2'][str(s)]['sha256']==expected);self.model=rt.load_model('TA2',seed,device)
            for param in self.model.parameters():param.requires_grad_(False)
            self.device=device;self.torch=torch;self.student_forward=rt.student_forward
    runner.TAForward=IsolatedTA
    import matplotlib.figure
    original_title=matplotlib.figure.Figure.suptitle
    def cohort_title(self,title,*a,**kw):return original_title(self,title.replace('Frozen r5.2 validation','HOLDOUT TRAIN + VALIDATION'),*a,**kw)
    matplotlib.figure.Figure.suptitle=cohort_title
    os.environ['MPLCONFIGDIR']=str(P4/'matplotlib_cache')
    device=setup_torch();runner.analyze(x,y,users,baseline,xbase,ta,xg,device,out=args.output,validation_spreads=spreads,original_parity=False)
    matplotlib.figure.Figure.suptitle=original_title
    write_json(args.output/'HOLDOUT_EXPLANATION_COMPLETE.json',dict(complete=True,script_sha256=sha(__file__),test_read=False))
if __name__=='__main__':main()
