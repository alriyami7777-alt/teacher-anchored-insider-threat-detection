from pathlib import Path
import os,sys,json,hashlib,time
sys.dont_write_bytecode=True
for n in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[n]='2'
os.environ['PYTHONUTF8']='1'
ROOT=Path(r'C:\PhD\07_Projects\r2_holdout')
CODE=Path(__file__).resolve().parent
R2=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision')
OUT=R2/'phase6b';PRIVATE=OUT/'private';H=R2/'holdout';HP=H/'private'
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

P4=H/'phase4';P4P=HP/'phase4';PYTHON=ROOT/'phase4/.venv/Scripts/python.exe'
EXPL=R2/'explanation/holdout'
def threshold4(y,p):
 from sklearn.metrics import precision_recall_curve
 precision,recall,t=precision_recall_curve(y,p)
 f=np.divide(2*precision[:-1]*recall[:-1],precision[:-1]+recall[:-1],out=np.zeros_like(t),where=precision[:-1]+recall[:-1]>0)
 return float(t[np.argmax(f)])
def oldspecs():return read(P4/'MODELS_FROZEN_PHASE4.json')['models']
def oldspec(name,s):return next(r for r in oldspecs() if r['model']==name and r['seed']==s)
def resultpath(name,s):return PRIVATE/'training'/name/'results'/f'{name}_{s}.json'
def orderfree(x):
 out=np.empty_like(x)
 for i in range(len(x)):out[i]=x[i,np.random.default_rng(np.random.SeedSequence([42,i])).permutation(20)]
 return out
def loadmodel(spec,dv):
 import torch,joblib
 name=spec['model']
 if name.startswith('XGBoost'):
  from xgboost import XGBClassifier
  m=XGBClassifier();m.load_model(spec['checkpoint']);m.set_params(n_jobs=2);return m
 if name.startswith(('RF','LightGBM')):
  m=joblib.load(spec['checkpoint']);m.n_jobs=2;return m
 if name=='MLP-40':
  from torch import nn
  m=nn.Sequential(nn.Linear(40,128),nn.ReLU(),nn.Dropout(.2),nn.Linear(128,64),nn.ReLU(),nn.Dropout(.2),nn.Linear(64,1))
  m.load_state_dict(torch.load(spec['checkpoint'],map_location='cpu',weights_only=False)['model_state_dict'])
 else:
  m=rt.build('odst');m.load_state_dict(torch.load(spec['checkpoint'],map_location='cpu',weights_only=False)['model_state_dict'])
 return m.to(dv).eval()
def predict(m,spec,x,dv):
 import torch
 name=spec['model'];out=[]
 with torch.inference_mode():
  for lo in range(0,len(x),1024):
   a=np.asarray(x[lo:lo+1024],np.float32)
   if name in ('XGBoost-260','RF-260','LightGBM-260'):v=m.predict_proba(a.reshape(len(a),-1))[:,1]
   elif name.startswith(('XGBoost','RF','LightGBM')):v=m.predict_proba(aggregate(a))[:,1]
   elif name=='MLP-40':v=rt.probs(m(torch.as_tensor(aggregate(a),device=dv)).squeeze(-1).cpu().numpy())
   else:v=rt.probs(rt.student_forward(m,torch.as_tensor(a,device=dv))['logit'].cpu().numpy())
   out.append(v);time.sleep(.002)
 return np.concatenate(out).astype(np.float64)

