from pathlib import Path
import os,sys,json,hashlib,time
sys.dont_write_bytecode=True
for n in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[n]='2'
os.environ['PYTHONUTF8']='1'
ROOT=Path(r'C:\PhD\07_Projects\r2_holdout')
CODE=Path(__file__).resolve().parent
R2=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision')
OUT=R2/'phase6';PRIVATE=OUT/'private';H=R2/'holdout';HP=H/'private'
FEAS=Path(r'C:\PhD\07_Projects\cert-r42-feasibility')
STUDY=Path(r'C:\PhD\07_Projects\cert-feature-selection-expansion-study')
REPO=Path(r'C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor023')
sys.path.insert(0,str(ROOT))
import numpy as np
import phase2_runtime as rt
SEEDS=(42,52,62)
FEATURES=['total_events','logon_count','device_count','file_count','email_count','http_count','active_duration_minutes','has_logon_activity','has_device_activity','has_file_activity','has_email_activity','has_http_activity','is_active_day']
def utc():
 from datetime import datetime,timezone
 return datetime.now(timezone.utc).isoformat()
def sha(p):return rt.sha(p)
def clean(x):
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(list,tuple)):return [clean(v) for v in x]
 if isinstance(x,np.ndarray):return clean(x.tolist())
 if isinstance(x,np.generic):return clean(x.item())
 if isinstance(x,Path):return str(x)
 if isinstance(x,float) and not np.isfinite(x):return None
 return x
def dump(p,x):rt.dump(p,clean(x))
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def pseudo(s):return 'U_'+hashlib.sha256(str(s).encode()).hexdigest()[:10]
def status(stage,**kw):
 dump(OUT/'STATUS.json',dict(utc=utc(),stage=stage,**kw));print(utc(),stage,kw,flush=True)
def devusers():return sorted(HP.joinpath('DEVELOPMENT_USERS.txt').read_text().split())
def excluded():return set(HP.joinpath('HOLDOUT_USERS.txt').read_text().split())
def device():
 import torch
 torch.set_num_threads(2)
 assert torch.cuda.is_available()
 torch.cuda.set_per_process_memory_fraction(.35)
 return torch.device('cuda')
def csv(name,rows):
 import pandas as pd
 pd.DataFrame(rows).to_csv(OUT/name,index=False)
def metrics(y,p,t):
 from sklearn.metrics import average_precision_score,f1_score,precision_score,recall_score
 return dict(windows=len(y),positive_windows=int(np.sum(y)),PR_AUC=float(average_precision_score(y,p)),F1=float(f1_score(y,p>=t,zero_division=0)),precision=float(precision_score(y,p>=t,zero_division=0)),recall=float(recall_score(y,p>=t,zero_division=0)),threshold=t)
def aggregate(x):
 # Same producing 40 summaries with the timestep dimension generalized to T1's 10/30 days.
 parts=[]
 for j in range(7):
  z=x[:,:,j];parts.extend([z.sum(1),z.mean(1),z.max(1),z.std(1)])
 for j in range(7,13):
  z=x[:,:,j];parts.extend([z.sum(1),z.mean(1)])
 return np.column_stack(parts).astype(np.float32)
def loadbundle(config,splits=('train','validation')):
 p=PRIVATE/'data'/config
 return {s:{'X':np.load(p/f'{s}_X.npy',mmap_mode='c'),'y':np.load(p/f'{s}_y.npy').astype(np.float32),**({'X40':np.load(p/f'{s}_X40.npy',mmap_mode='c')} if (p/f'{s}_X40.npy').exists() else {})} for s in splits}
