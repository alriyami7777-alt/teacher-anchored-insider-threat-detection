from pathlib import Path
import os,sys,time,json,hashlib,subprocess
sys.dont_write_bytecode=True
for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMBA_NUM_THREADS'):os.environ[k]='2'
import numpy as np,pandas as pd
from datetime import datetime,timezone
CODE=Path(__file__).resolve().parent;ROOT=Path(r'C:\PhD\07_Projects\r2_holdout');R2=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision');OUT=R2/'phase10';P=OUT/'private';HP=R2/'holdout/private';P4=R2/'holdout/phase4';P5=R2/'phase5';B=Path(r'C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006c_bundle');PY=ROOT/'phase4/.venv/Scripts/python.exe';DEADLINE=datetime.fromisoformat('2026-10-23T18:30:00+08:00').timestamp();SEEDS=(42,52,62);MODELS=('TA2','F00','XGBoost_40')
sys.path.insert(0,str(ROOT));import phase2_runtime as rt
def utc():return datetime.now(timezone.utc).isoformat()
def sha(p):return rt.sha(p)
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def clean(x):
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(list,tuple)):return [clean(v) for v in x]
 if isinstance(x,np.ndarray):return clean(x.tolist())
 if isinstance(x,np.generic):return clean(x.item())
 if isinstance(x,Path):return str(x)
 if isinstance(x,float) and not np.isfinite(x):return None
 return x
def dump(p,x):rt.dump(p,clean(x))
def gate():
 assert time.time()<DEADLINE,'HARD STOP 18:30 (+08)'
 a=read(OUT/'AMENDMENT10_RECEIPT.json');cr=read(OUT/'AMENDMENT10_CLARIFICATION_RECEIPT.json');b=(R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md').read_bytes()
 for z in (a,cr):assert hashlib.sha256(b[:z['hashed_bytes']]).hexdigest()==z['sha256']
 f=read(OUT/'PREREQUISITES_FROZEN.json');assert sha(OUT/'R62_SPLIT_RECEIPT.json')==f['split_receipt_sha256']
def device():
 import torch
 torch.set_num_threads(2);torch.cuda.set_per_process_memory_fraction(.35);return torch.device('cuda')
def oldspec(n,s):return next(z for z in read(P4/'MODELS_FROZEN_PHASE4.json')['models'] if z['model']==n and z['seed']==s)
def spec(c,n,s):return read(P/f'training/{c}/results/{n}_{s}.json')
def scalers():return read(P5/'MODELS_AND_METHODS_FROZEN_PHASE5.json')['scalers']
def agg(x):return rt.aggregate_common13_windows(x)[0]
def loadmodel(sp,dv):
 import torch
 assert sha(sp['checkpoint'])==sp['sha256']
 if sp['model']=='XGBoost_40':
  from xgboost import XGBClassifier
  m=XGBClassifier();m.load_model(sp['checkpoint']);m.set_params(n_jobs=2);return m
 m=rt.AttentionNodeEnsemble(**rt.ENCODER_ARCH);m.load_state_dict(torch.load(sp['checkpoint'],map_location='cpu',weights_only=False)['model_state_dict']);return m.to(dv).eval()
def predict(m,n,x,dv):
 import torch
 if n=='XGBoost_40':return m.predict_proba(agg(x))[:,1].astype(float)
 with torch.no_grad():return rt.probs(rt.forward(m,torch.as_tensor(x,device=dv),'odst')['logit'].cpu().numpy())
def cohort(release='r62',development=False):
 if release=='r52':
  z=dict(np.load(R2/'phase6b/private/cohorts/T20_metadata.npz'));op=dict(np.load(P5/'private/HOLDOUT_OPERATIONAL_METADATA.npz'));return dict(u=z['cluster'].astype(int),y=z['y'],N=500,ids=op['user'],ins=op['insider'].astype(bool))
 users=np.load(P/('DEVELOPMENT_indices.npy' if development else 'HOLDOUT_indices.npy'));wi=np.load(B/'window_index.npy',mmap_mode='r');split=read(OUT/'R62_SPLIT_RECEIPT.json');nt=split['n_train_days'];nv=split['n_validation_days'];u=wi[:,0];st=wi[:,1];mask=np.isin(u,users)&((st<=nt-20)|((st>=nt)&(st<=nt+nv-20)));rows=np.flatnonzero(mask);ids=np.load(B/'user_ids.npy');ps=np.array(['U_'+hashlib.sha256(str(ids[i]).encode()).hexdigest()[:10] for i in users]);return dict(u=np.searchsorted(users,u[rows]),y=np.load(B/'completed_window_labels.npy',mmap_mode='r')[rows],rows=rows,start=st[rows],global_u=u[rows],N=len(users),ids=ps,ins=np.load(P/'INSIDER_STATUS.npy')[users])
def cached(n,s,co,release='r62'):
 return np.load(P5/f'private/transfer/r6.2/development_{n}_{s}.npy',mmap_mode='r')[co['rows']] if release=='r62' else np.load(HP/f'phase4/scores/{n}_{s}.npz')['scores']
def bundle(c):return {part:{k:np.load(P/f'data/{c}/{part}_{k}.npy',mmap_mode='c') for k in ('X','X40','y')} for part in ('train','validation')}
def child(script,args,key):
 gate();log=P/f'logs/{key}.log';log.parent.mkdir(parents=True,exist_ok=True);start=time.time();dump(OUT/'STATUS.json',dict(utc=utc(),stage=key,hard_stop_local='18:30 +08'))
 with log.open('w',encoding='utf8') as h:
  proc=subprocess.Popen([str(PY),'-X','utf8','-B',str(CODE/script),*map(str,args)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  dump(P/'ACTIVE_CHILD.json',dict(pid=proc.pid,key=key,started_utc=utc(),owned=True))
  try:rc=proc.wait(timeout=max(.01,min(2700,DEADLINE-time.time())))
  except subprocess.TimeoutExpired:proc.kill();proc.wait();rc='NOT RUN (time)' if time.time()>=DEADLINE-1 else 'TIMEOUT'
 r=dict(utc=utc(),key=key,exit=rc,status='ok' if rc==0 else str(rc),wall_seconds=time.time()-start,log=str(log));dump(P/f'outcomes/{key}.json',r);return r
