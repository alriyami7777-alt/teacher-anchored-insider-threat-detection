"""Phase 5 inference/analysis helpers. No training entrypoint."""
from pathlib import Path
import os,sys,json,hashlib,time,importlib.util
sys.dont_write_bytecode=True
os.environ['PYTHONUTF8']='1'
for name in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[name]='2'
ROOT=Path(r'C:\PhD\07_Projects\r2_holdout');CODE=ROOT/'phase5'
R2=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision')
OUT=R2/'phase5';PRIVATE=OUT/'private';P4=R2/'holdout/phase4';HPRIVATE=R2/'holdout/private';P4PRIVATE=HPRIVATE/'phase4'
REPO=Path(r'C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor023')
R61=Path(r'C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor024-r61')
SEEDS=(42,52,62)
sys.path.insert(0,str(ROOT/'phase4'));sys.path.insert(0,str(ROOT))
import common as p4
import phase2_runtime as rt
import numpy as np
def utc():
    from datetime import datetime,timezone
    return datetime.now(timezone.utc).isoformat()
def sha(p):return p4.sha(p)
def clean(x):
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [clean(v) for v in x]
    if isinstance(x,np.ndarray):return clean(x.tolist())
    if isinstance(x,np.generic):return clean(x.item())
    if isinstance(x,Path):return str(x)
    if isinstance(x,float) and not np.isfinite(x):return None
    return x
def dump(p,x):p4.dump(p,clean(x))
def status(stage,**kw):
    dump(OUT/'STATUS.json',dict(utc=utc(),stage=stage,exploratory=True,**kw));print(utc(),stage,kw,flush=True)
def pseudo(s):return 'U_'+hashlib.sha256(str(s).encode()).hexdigest()[:10]
def device():
    import torch
    torch.set_num_threads(2)
    if torch.cuda.is_available():
        torch.cuda.set_per_process_memory_fraction(.35)
        return torch.device('cuda')
    return torch.device('cpu')
def registry():return json.loads((OUT/'MODELS_AND_METHODS_FROZEN_PHASE5.json').read_text(encoding='utf-8'))
def check_frozen():
    f=registry();p4.verify_original()
    for group in f['models'].values():
        for s in group:assert sha(s['checkpoint'])==s['sha256']
    for p,h in f['dependencies'].items():assert sha(p)==h,'Frozen dependency changed: '+p
    for n,h in f['code_hashes'].items():assert sha(CODE/n)==h,'Phase 5 code changed: '+n
    return f
def sentinel(name):
    p=PRIVATE/'sentinels'/f'{name}.json';p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(dict(utc=utc(),evaluation=name,manifest_sha256=sha(OUT/'MODELS_AND_METHODS_FROZEN_PHASE5.json'),no_reruns=True),f,indent=2)
def load_model(spec,dev):
    import torch,joblib
    name=spec['model']
    if name in ('RF_40','IsolationForest','LightGBM_40'):
        m=joblib.load(spec['checkpoint']);m.n_jobs=2;return m
    if name=='XGBoost_40':
        from xgboost import XGBClassifier
        m=XGBClassifier();m.load_model(spec['checkpoint']);m.set_params(n_jobs=2);return m
    if spec['block']=='development':
        if name in p4.BASELINES:
            m=p4.build_model(name);payload=torch.load(spec['checkpoint'],map_location='cpu',weights_only=False);m.load_state_dict(payload['model_state_dict'])
        else:return rt.load_model(name,spec['seed'],dev)
    else:
        payload=torch.load(spec['checkpoint'],map_location='cpu',weights_only=False);m=rt.build('odst')
        if name=='L1':
            m.load_state_dict(payload['student_state_dict']);head=torch.nn.Linear(128,1)
            head.load_state_dict({k.removeprefix('linear_head.linear.'):v for k,v in payload['modules_state_dict'].items() if k.startswith('linear_head.linear.')});m.linear_head=head
        else:m.load_state_dict(payload['model_state_dict'])
    m.to(dev).eval()
    for p in m.parameters():p.requires_grad_(False)
    return m
def infer_batch(m,spec,x,dev):
    import torch
    name=spec['model']
    if name in ('RF_40','XGBoost_40','IsolationForest','LightGBM_40'):
        tab=rt.aggregate_common13_windows(x)[0]
        return (-m.score_samples(tab) if name=='IsolationForest' else m.predict_proba(tab)[:,1]).astype(np.float64)
    with torch.no_grad():
        t=torch.as_tensor(x,device=dev)
        if name in p4.BASELINES:
            z=m(t)
            if name=='LSTM_AE':return (z-t).square().mean((1,2)).cpu().numpy().astype(np.float64)
        elif name=='L1':
            h,_=m.encode_attention_h(t);z=m.linear_head(h).squeeze(-1)
        else:z=rt.student_forward(m,t)['logit']
        return rt.probs(z.cpu().numpy())
def predict_array(spec,x,dev):
    m=load_model(spec,dev);p=np.empty(len(x),np.float64)
    for lo in range(0,len(x),1024):
        hi=min(lo+1024,len(x));p[lo:hi]=infer_batch(m,spec,np.asarray(x[lo:hi]),dev)
        if dev.type=='cuda':time.sleep(.001)
    del m
    import torch
    if torch.cuda.is_available():torch.cuda.empty_cache()
    assert np.isfinite(p).all();return p
def base_score(spec):
    with np.load(P4PRIVATE/'scores'/f"{spec['model']}_{spec['seed']}.npz") as z:return z['scores']
def holdout():
    with np.load(P4PRIVATE/'HOLDOUT_COHORT.npz') as z:return {n:z[n] for n in z.files}
def model_name(name):return 'TRACE' if name=='TA2' else name
def save_csv(name,rows):
    import pandas as pd
    pd.DataFrame(rows).to_csv(OUT/name,index=False)
def point_metrics(y,p,threshold):
    from sklearn.metrics import average_precision_score,precision_score,recall_score,f1_score
    prev=float(np.mean(y));flag=p>=threshold;ap=float(average_precision_score(y,p))
    return dict(windows=len(y),positive_windows=int(y.sum()),prevalence=prev,PR_AUC=ap,ranking_excess=ap-prev,ratio_to_prevalence=ap/prev if prev else None,precision=float(precision_score(y,flag,zero_division=0)),recall=float(recall_score(y,flag,zero_division=0)),F1=float(f1_score(y,flag,zero_division=0)),alerts_per_1000=float(flag.mean()*1000),threshold_exceedance_rate=float(flag.mean()),threshold=float(threshold))
