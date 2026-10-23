from pathlib import Path
import os,sys,json,hashlib,time
sys.dont_write_bytecode=True
for n in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMBA_NUM_THREADS'):os.environ[n]='2'
import numpy as np,pandas as pd
from scipy.stats import rankdata
from sklearn.metrics import average_precision_score,f1_score,precision_score,recall_score,precision_recall_curve
CODE=Path(__file__).resolve().parent
R2=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision')
ROOT=Path(r'C:\PhD\07_Projects\r2_holdout');OUT=R2/'phase7';PRIVATE=OUT/'private'
HP=R2/'holdout/private';P4=R2/'holdout/phase4';P4P=HP/'phase4';B6P=R2/'phase6b/private';EXPL=R2/'explanation/holdout';P5=R2/'phase5'
PYTHON=ROOT/'phase4/.venv/Scripts/python.exe';SEEDS=(42,52,62)
NAMES={'TA2':'TRACE','F00':'F00','L1':'L1','XGBoost_40':'XGBoost-40','LightGBM_40':'LightGBM-40','Transformer':'Transformer'}
FEATURES=['total_events','logon_count','device_count','file_count','email_count','http_count','active_duration_minutes','has_logon_activity','has_device_activity','has_file_activity','has_email_activity','has_http_activity','is_active_day']
SOURCE_GROUPS={'logon':[1,7],'device':[2,8],'file':[3,9],'email':[4,10],'http':[5,11],'shared/activity':[0,6,12]}
def utc():
 from datetime import datetime,timezone
 return datetime.now(timezone.utc).isoformat()
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def clean(x):
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(list,tuple,set)):return [clean(v) for v in x]
 if isinstance(x,np.ndarray):return clean(x.tolist())
 if isinstance(x,np.generic):return clean(x.item())
 if isinstance(x,Path):return str(x)
 if isinstance(x,float) and not np.isfinite(x):return None
 return x
def dump(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(clean(x),indent=2,allow_nan=False),encoding='utf-8');os.replace(tmp,p)
def csv(name,rows):
 p=OUT/name
 if isinstance(rows,pd.DataFrame):rows.to_csv(p,index=False)
 else:pd.DataFrame(clean(rows)).to_csv(p,index=False)
def status(stage,**kw):dump(OUT/'STATUS.json',dict(utc=utc(),stage=stage,**kw));print(utc(),stage,kw,flush=True)
def specs():return [r for r in read(P4/'MODELS_FROZEN_PHASE4.json')['models'] if r['model'] in NAMES]
def spec(name,seed):return next(r for r in specs() if NAMES[r['model']]==name and r['seed']==seed)
def score(name,seed):
 s=spec(name,seed);z=np.load(P4P/f"scores/{s['model']}_{seed}.npz");assert float(z['threshold'])==s['threshold'];return z['scores'].astype(np.float64)
def metadata():
 z=dict(np.load(B6P/'cohorts/T20_metadata.npz'));o=dict(np.load(P5/'private/HOLDOUT_OPERATIONAL_METADATA.npz'));assert np.array_equal(z['end_date'].astype('datetime64[D]'),o['rowdate']);assert np.array_equal(z['user'],o['user'][z['cluster']]);return z,o
def metrics(y,p,t):
 f=p>=t
 return dict(PR_AUC=float(average_precision_score(y,p)),F1=float(f1_score(y,f,zero_division=0)),precision=float(precision_score(y,f,zero_division=0)),recall=float(recall_score(y,f,zero_division=0)),threshold=float(t),alert_windows=int(f.sum()))
def detected(m,p,t):
 return np.bincount(m['cluster'],weights=((m['y']==1)&(p>=t)),minlength=500)>0
def flagged(m,o,p,t):return np.bincount(m['cluster'],weights=(p>=t)&(~o['insider'][m['cluster']]),minlength=500)>0
def ops(m,o,p,t):return dict(insiders_detected=int(detected(m,p,t).sum()),insiders_total=25,noninsiders_flagged=int(flagged(m,o,p,t).sum()),noninsiders_total=475)
def summary(a,estimate):
 a=np.asarray(a);v=a[np.isfinite(a)];lo,hi=np.percentile(v,[2.5,97.5]) if len(v) else (np.nan,np.nan)
 return dict(estimate=float(estimate),ci95_low=float(lo),ci95_high=float(hi),CI_direction='above' if lo>0 else 'below' if hi<0 else 'compatible_with_zero',attempted_replicates=len(a),valid_replicates=len(v),undefined_replicates=len(a)-len(v),bootstrap_seed=42,cluster='user',multiplicity_adjusted=False)
def percentile(p):return rankdata(p,method='average')/len(p)
def combination(a,b):return (percentile(a)+percentile(b))/2
def original_threshold(y,p):
 # Exact producing TRACE/XGBoost max-F1 rule retained, including first maximum.
 candidates=sorted(set(np.linspace(.01,.99,99).tolist())|set(float(q) for q in np.quantile(p,np.linspace(.01,.99,50))))
 fs=[f1_score(y,p>=t,zero_division=0) for t in candidates];return float(candidates[int(np.argmax(fs))])
def rule_thresholds(y,p):
 precision,recall,t=precision_recall_curve(y,p);pr=precision[:-1];re=recall[:-1]
 a=np.flatnonzero(re>=.9);i=int(a[-1]);r=[dict(rule='recall_ge_0.90',threshold=float(t[i]),validation_precision=float(pr[i]),validation_recall=float(re[i]),target_attained=True)]
 a=np.flatnonzero(pr>=.5);attain=bool(len(a))
 if not len(a):a=np.flatnonzero(pr==pr.max())
 best=re[a].max();i=int(a[re[a]==best][0]);r.append(dict(rule='precision_ge_0.50',threshold=float(t[i]),validation_precision=float(pr[i]),validation_recall=float(re[i]),target_attained=attain))
 return r
