"""Option C deferred scorer. Sole inference entrypoint; exclusive original sentinel."""
from common import *
import argparse
def predict(spec,X,X40,device):
    import numpy as np,torch,joblib
    import phase2_runtime as rt
    from torch.utils.data import DataLoader,TensorDataset
    name,seed=spec['model'],spec['seed']
    if name in ('RF_40','XGBoost_40','IsolationForest','LightGBM_40'):
        if name=='XGBoost_40':
            from xgboost import XGBClassifier
            m=XGBClassifier();m.load_model(spec['checkpoint']);m.set_params(n_jobs=2)
        else:m=joblib.load(spec['checkpoint'])
        if hasattr(m,'n_jobs'):m.n_jobs=2
        p=-m.score_samples(X40) if name=='IsolationForest' else m.predict_proba(X40)[:,1]
    else:
        loader=DataLoader(TensorDataset(torch.from_numpy(X)),batch_size=1024,shuffle=False,num_workers=0)
        if name in BASELINES:
            m=build_model(name);payload=torch.load(spec['checkpoint'],map_location='cpu',weights_only=False);m.load_state_dict(payload['model_state_dict']);m.to(device).eval();values=[]
            with torch.no_grad():
                for (x,) in loader:
                    x=x.to(device);raw=m(x);values.append(((raw-x).square().mean((1,2)) if name=='LSTM_AE' else raw).cpu().numpy())
            raw=np.concatenate(values);p=raw.astype(np.float64) if name=='LSTM_AE' else rt.probs(raw)
        else:
            m=rt.load_model(name,seed,device);p=rt.probs(rt.logits(m,loader,device,'linear' if name=='L1' else 'odst'))
    del m
    if torch.cuda.is_available():torch.cuda.empty_cache()
    p=np.asarray(p,dtype=np.float64);assert p.shape==(len(X),) and np.isfinite(p).all()
    return p
def freeze_and_preflight():
    import numpy as np,torch,importlib.metadata
    import phase2_runtime as rt
    from verify_all import verify_all
    audit=verify_all();original=verify_original();assert not (OUT/'private/HOLDOUT_SCORING_CONSUMED.json').exists()
    runs=json.loads((P4/'TRAINING_RESULTS_PHASE4.json').read_text())
    assert len(runs)==24
    assert json.loads((P4/'STATUS.json').read_text())['stage']=='TRAINING_FINISHED'
    recipes=json.loads((P4/'RECIPES_FROZEN_PHASE4.json').read_text())
    for name,h in recipes['files'].items():assert sha(CODE/name)==h,'Training implementation changed after preregistered freeze'
    base=[r for r in runs if r['status']=='ok']
    models=[r for r in original['models'] if 'PRECURSOR' not in r['model']]+base
    for r in models:assert sha(r['checkpoint'])==r['sha256']
    device=setup_torch();data=rt.data();X=np.array(data['validation']['X'][:16]);X40=np.array(data['validation']['X40'][:16])
    assert np.array_equal(rt.aggregate_common13_windows(X)[0],X40)
    dry=[]
    for spec in models:
        p=predict(spec,X,X40,device);dry.append(dict(model=spec['model'],seed=spec['seed'],finite=bool(np.isfinite(p).all())))
    sys.path.insert(0,str(EXPL));import run_phase3 as runner
    from phase3_engine import integrated_gradients,aggregate40
    m=rt.load_model('TA2',42,device)
    class ExplanationForward:
        def __init__(self):self.device=device
        def __call__(self,x):
            out=rt.student_forward(m,x);return torch.cat((out['tree_outputs'],out['logit'][:,None]),1)
    attrs,diffs,residual,relative=integrated_gradients(ExplanationForward(),X[:2],np.zeros((20,13),np.float32))
    assert attrs.shape==(2,9,20,13) and np.isfinite(attrs).all()
    xg=next(r for r in models if r['model']=='XGBoost_40' and r['seed']==42);xf=runner.XGForward(xg['checkpoint'],xg['sha256']);sm=aggregate40(X[:2]);assert np.array_equal(sm,X40[:2]);assert np.max(np.abs(xf.contributions(sm).sum(1)-xf.predict(sm)))<1e-3
    del m,xf
    assert all(sum(r['model']==n for r in models)==3 for n in ('TA2','F00','XGBoost_40'))
    manifest=dict(utc=utc(),option='C',evaluation_periods=['train','validation'],test_sealed=True,original_freeze_sha256=sha(OUT/'MODELS_FROZEN.json'),models=[{k:v for k,v in r.items() if k!='history'} for r in models],skipped=[r for r in runs if r['status']!='ok'],scoring_script=dict(path=str(Path(__file__).resolve()),sha256=sha(__file__)),files={p.name:sha(p) for p in CODE.glob('*.py')},supervisor_disclosure_sha256=sha(OUT/'SUPERVISOR_DISCLOSURE_PHASE4.json'),preregistration_sha256=sha(OUT/'PREREGISTRATION_R2_HOLDOUT.md'),preflight_development_only=dry,environment={s:importlib.metadata.version(s) for s in ('numpy','pandas','torch','scikit-learn','xgboost','lightgbm','numba')})
    manifest['full_input_verification_sha256']=sha(P4/'FULL_FROZEN_INPUT_VERIFICATION.json')
    assert not (P4/'MODELS_FROZEN_PHASE4.json').exists()
    dump(P4/'MODELS_FROZEN_PHASE4.json',manifest);status('PHASE4_MODELS_FROZEN',models=len(models))
def execute():
    import numpy as np,pandas as pd,torch
    import pyarrow.dataset as ds
    from datetime import date
    import phase2_runtime as rt
    from verify_all import verify_all
    verify_all('PRE_SCORING_HASH_VERIFICATION.json');original=verify_original();f=json.loads((P4/'MODELS_FROZEN_PHASE4.json').read_text())
    assert sha(P4/'FULL_FROZEN_INPUT_VERIFICATION.json')==f['full_input_verification_sha256']
    assert sha(OUT/'MODELS_FROZEN.json')==f['original_freeze_sha256']
    for name,h in f['files'].items():assert sha(CODE/name)==h,'Phase 4 code changed'
    for spec in f['models']:assert sha(spec['checkpoint'])==spec['sha256']
    assert sha(OUT/'SUPERVISOR_DISCLOSURE_PHASE4.json')==f['supervisor_disclosure_sha256']
    assert sha(OUT/'PREREGISTRATION_R2_HOLDOUT.md')==f['preregistration_sha256']
    assert f['evaluation_periods']==['train','validation'] and f['test_sealed']
    assert not (PRIVATE/'scores').exists()
    lock=OUT/'private/HOLDOUT_SCORING_CONSUMED.json'
    with lock.open('x',encoding='utf-8') as handle:json.dump(dict(utc=utc(),freeze_sha256=sha(P4/'MODELS_FROZEN_PHASE4.json'),disclosure_sha256=f['supervisor_disclosure_sha256'],option='C',no_reruns=True),handle,indent=2)
    status('HOLDOUT_BUILDING',sentinel_consumed=True)
    users=(OUT/'private/HOLDOUT_USERS.txt').read_text().splitlines();assert len(users)==500
    dev=set((OUT/'private/DEVELOPMENT_USERS.txt').read_text().splitlines());assert not set(users)&dev
    sc=json.loads((OUT/'private/DEVELOPMENT_DAILY_SCALER.json').read_text());feats=sc['features'];mean=np.array(sc['mean']);scale=np.array(sc['scale'])
    source=Path(r'C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\interval_level\r52_user_day_intervals_dense.parquet')
    predicate=ds.field('user').isin(users)&(ds.field('interval_date')>=date(2010,1,2))&(ds.field('interval_date')<=date(2011,4,10))
    frame=ds.dataset(source,format='parquet').to_table(columns=['user','interval_date',*feats,'is_malicious_interval'],filter=predicate).to_pandas()
    frame['interval_date']=pd.to_datetime(frame.interval_date);frame=frame.sort_values(['user','interval_date'],kind='mergesort')
    assert len(frame)==500*(413+51) and frame.interval_date.max()<=pd.Timestamp('2011-04-10')
    xs=[];tab=[];ys=[];eps=[];clusters=[];offset=[];parts=[];pseudonyms=[]
    for ui,u in enumerate(users):
        group=frame.loc[frame.user==u]
        for pname,lo,hi,expected in [('train','2010-01-02','2011-02-18',413),('validation','2011-02-19','2011-04-10',51)]:
            g=group.loc[(group.interval_date>=lo)&(group.interval_date<=hi)]
            assert len(g)==expected and (g.interval_date.diff().dropna()==pd.Timedelta(days=1)).all()
            raw=g[feats].to_numpy(dtype=np.float64);labels=g.is_malicious_interval.to_numpy();ix=np.arange(expected-19)[:,None]+np.arange(20)[None,:]
            X=((raw[ix]-mean)/scale).astype(np.float32);xs.append(X);tab.append(rt.aggregate_common13_windows(X)[0]);ys.extend(labels[ix].max(1));eps.extend(labels[ix[:,-1]]);clusters.extend([ui]*len(ix));offset.extend(np.arange(len(ix))%20==0);parts.extend([pname]*len(ix));pseudonyms.extend(['U_'+hashlib.sha256(u.encode()).hexdigest()[:10]]*len(ix))
    X=np.concatenate(xs);X40=np.concatenate(tab);y=np.array(ys,dtype=np.int8);endpoint=np.array(eps,dtype=np.int8);cluster=np.array(clusters,dtype=np.int16);offset=np.array(offset,dtype=bool);part=np.array(parts)
    assert X.shape==(213000,20,13) and int(y.sum())==1172 and np.isfinite(X).all() and np.isfinite(X40).all()
    for name,n,p in [('train',197000,917),('validation',16000,255)]:assert (part==name).sum()==n and int(y[part==name].sum())==p
    assert len(set(pseudonyms))==500
    PRIVATE.mkdir(exist_ok=True);np.savez_compressed(PRIVATE/'HOLDOUT_COHORT.npz',X=X,y=y,user=np.array(pseudonyms),cluster=cluster,endpoint=endpoint,offset0=offset,partition=part)
    receipt=dict(utc=utc(),shape=list(X.shape),windows=len(y),positives=int(y.sum()),periods=['train','validation'],date_predicate=['2010-01-02','2011-04-10'],test_read=False,scaler_sha256=original['scaler_sha256'],cohort_sha256=sha(PRIVATE/'HOLDOUT_COHORT.npz'),frozen_manifest_sha256=sha(P4/'MODELS_FROZEN_PHASE4.json'))
    dump(P4/'HOLDOUT_BUILD_RECEIPT.json',receipt);del frame,xs,tab
    target=PRIVATE/'scores';target.mkdir();device=setup_torch()
    for i,spec in enumerate(f['models']):
        status('SCORING_ONCE',model=spec['model'],seed=spec['seed'],completed=i,total=len(f['models']))
        p=predict(spec,X,X40,device);np.savez_compressed(target/f"{spec['model']}_{spec['seed']}.npz",scores=p,threshold=spec['threshold'])
    verify_original()
    for spec in f['models']:assert sha(spec['checkpoint'])==spec['sha256']
    dump(P4/'SCORING_COMPLETE.json',dict(utc=utc(),models=len(f['models']),sentinel_sha256=sha(lock),test_read=False,reruns=0,prediction_hashes={p.name:sha(p) for p in target.glob('*.npz')}));status('SCORING_FINISHED',models=len(f['models']))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--freeze-preflight',action='store_true');p.add_argument('--execute-once',action='store_true');a=p.parse_args();assert a.freeze_preflight!=a.execute_once
    freeze_and_preflight() if a.freeze_preflight else execute()
