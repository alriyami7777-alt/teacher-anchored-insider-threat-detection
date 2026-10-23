from pathlib import Path
import os,sys,json,hashlib,time
sys.dont_write_bytecode=True
for n in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMBA_NUM_THREADS'):os.environ[n]='2'
import numpy as np,pandas as pd
CODE=Path(__file__).resolve().parent;R2=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision');ROOT=Path(r'C:\PhD\07_Projects\r2_holdout')
OUT=R2/'phase8';PRIVATE=OUT/'private';H=R2/'holdout';HP=H/'private';P4=H/'phase4';P4P=HP/'phase4';B6P=R2/'phase6b/private';EXPL=R2/'explanation/holdout';P5=R2/'phase5'
PYTHON=ROOT/'phase4/.venv/Scripts/python.exe';OLD=(42,52,62);NEW=(72,82,92,102,112);ALL=OLD+NEW
FEATURES=['total_events','logon_count','device_count','file_count','email_count','http_count','active_duration_minutes','has_logon_activity','has_device_activity','has_file_activity','has_email_activity','has_http_activity','is_active_day']
sys.path.insert(0,str(ROOT));import phase2_runtime as rt
def utc():
 from datetime import datetime,timezone
 return datetime.now(timezone.utc).isoformat()
def sha(p):return rt.sha(p)
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def clean(x):
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(list,tuple,set)):return [clean(v) for v in x]
 if isinstance(x,np.ndarray):return clean(x.tolist())
 if isinstance(x,np.generic):return clean(x.item())
 if isinstance(x,Path):return str(x)
 if isinstance(x,float) and not np.isfinite(x):return None
 return x
def dump(p,x):rt.dump(p,clean(x))
def csv(name,rows):pd.DataFrame(clean(rows)).to_csv(OUT/name,index=False)
def status(stage,**kw):dump(OUT/'STATUS.json',dict(utc=utc(),stage=stage,**kw));print(utc(),stage,kw,flush=True)
def gate():
 a=read(OUT/'AMENDMENT8_RECEIPT.json');b=(H/'PREREGISTRATION_R2_HOLDOUT.md').read_bytes();assert hashlib.sha256(b[:a['hashed_bytes']]).hexdigest()==a['sha256'];assert read(R2/'phase7/FINAL_AUDIT.json')['all_checks_passed']
def oldspec(name,s):return next(r for r in read(P4/'MODELS_FROZEN_PHASE4.json')['models'] if r['model']==name and r['seed']==s)
def resultpath(name,s):return PRIVATE/f'training/results/{name}_{s}.json'
def spec(name,s):return oldspec(name,s) if s in OLD else read(resultpath(name,s))
def device():
 import torch
 torch.set_num_threads(2);assert torch.cuda.is_available();torch.cuda.set_per_process_memory_fraction(.35);return torch.device('cuda')
def bundle():return {part:{'X':np.load(HP/f'tensors/{part}_X.npy',mmap_mode='c'),'X40':np.load(HP/f'tensors/{part}_X40.npy',mmap_mode='c'),'y':np.load(HP/f'tensors/{part}_y.npy').astype(np.float32)} for part in ('train','validation')}
def loadmodel(s,dv):
 import torch
 assert sha(s['checkpoint'])==s['sha256'];name=s['model']
 if name=='XGBoost_40':
  from xgboost import XGBClassifier
  m=XGBClassifier();m.load_model(s['checkpoint']);m.set_params(n_jobs=2);return m
 m=rt.build('odst',name.startswith('uni'))
 if name=='L1':m.linear_head=torch.nn.Linear(128,1)
 m.load_state_dict(torch.load(s['checkpoint'],map_location='cpu',weights_only=False)['model_state_dict']);return m.to(dv).eval()
def metadata():return dict(np.load(B6P/'cohorts/T20_metadata.npz'))
def point(y,p,t):
 from sklearn.metrics import average_precision_score,f1_score,precision_score,recall_score
 return dict(PR_AUC=float(average_precision_score(y,p)),F1=float(f1_score(y,p>=t,zero_division=0)),precision=float(precision_score(y,p>=t,zero_division=0)),recall=float(recall_score(y,p>=t,zero_division=0)),threshold=float(t),windows=len(y),positive_windows=int(y.sum()))
def probability(name,s):return np.load(P4P/f'scores/{name}_{s}.npz')['scores'] if s in OLD else np.load(PRIVATE/f'scores/{name}_{s}.npy')
def ci(a,est):
 v=np.asarray(a);v=v[np.isfinite(v)];lo,hi=np.percentile(v,[2.5,97.5]) if len(v) else (np.nan,np.nan)
 return dict(estimate=float(est),ci95_low=float(lo),ci95_high=float(hi),attempted_replicates=len(a),valid_replicates=len(v),undefined_replicates=len(a)-len(v),CI_direction='above' if lo>0 else 'below' if hi<0 else 'compatible_with_zero',bootstrap_seed=42,cluster='user',multiplicity_adjusted=False)
