from pathlib import Path
import os,sys,time,json,hashlib,subprocess
sys.dont_write_bytecode=True
for name in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMBA_NUM_THREADS'):os.environ[name]='2'
import numpy as np,pandas as pd
from datetime import datetime,timezone
CODE=Path(__file__).resolve().parent;ROOT=Path(r'C:\PhD\07_Projects\r2_holdout');R2=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision');OUT=R2/'phase11';P=OUT/'private';HP=R2/'holdout/private';P4=R2/'holdout/phase4';P5=R2/'phase5';P10=R2/'phase10';B=Path(r'C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006c_bundle');PY=ROOT/'phase4/.venv/Scripts/python.exe';DEADLINE=float('inf');RUN_LIMIT=5400;SEEDS=(42,52,62);MODELS=('TA2','XGBoost_40')
sys.path.insert(0,str(ROOT));import phase2_runtime as rt
def utc():return datetime.now(timezone.utc).isoformat()
def sha(p):return rt.sha(p)
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def clean(x):
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(tuple,list)):return [clean(v) for v in x]
 if isinstance(x,np.ndarray):return clean(x.tolist())
 if isinstance(x,np.generic):return clean(x.item())
 if isinstance(x,Path):return str(x)
 if isinstance(x,float) and not np.isfinite(x):return None
 return x
def dump(p,x):rt.dump(p,clean(x))
def data_condition(c):return 'C1' if c=='C4' else c
def data_dir(c,k):return P/f'data/{data_condition(c)}_fold{k}'
def train_dir(c,k):return P/f'training/{data_condition(c)}_fold{k}'
def result_path(c,k,n,s):return train_dir(c,k)/f'results/{n}_{s}.json'
def spec(c,k,n,s):return read(result_path(c,k,n,s))
def scalers():return read(P5/'MODELS_AND_METHODS_FROZEN_PHASE5.json')['scalers']
_integrity_last_check=-float('inf')
def gate():
 global _integrity_last_check
 assert time.time()<DEADLINE,'Phase 11 overall deadline removed by Qasim 24Oct05:53+08'
 now=time.monotonic()
 if now-_integrity_last_check<30:return
 a=read(OUT/'AMENDMENT11_RECEIPT.json');b=(R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md').read_bytes();assert hashlib.sha256(b[:a['hashed_bytes']]).hexdigest()==a['sha256']
 f=read(OUT/'PREREQUISITES_FROZEN.json');assert sha(OUT/'FOLD_RECEIPT.json')==f['fold_receipt_sha256'] and sha(OUT/'R62_FOLD_ASSIGNMENT.csv')==f['fold_csv_sha256']
 _integrity_last_check=now

def device():
 import torch
 torch.set_num_threads(2);torch.cuda.set_per_process_memory_fraction(.35);return torch.device('cuda')
def agg(x):return rt.aggregate_common13_windows(x)[0]
def bundle(c,k):return {part:{key:np.load(data_dir(c,k)/f'{part}_{key}.npy',mmap_mode='c') for key in ('X','X40','y')} for part in ('train','validation')}
def cohort(k=None):
 sp=read(OUT/'FOLD_RECEIPT.json');nt=sp['n_train_days'];nv=sp['n_validation_days'];users=np.arange(4000) if k is None else np.load(P/f'FOLD{k}_HELDOUT.npy');starts=np.r_[np.arange(nt-19),np.arange(nt,nt+nv-19)];u=np.repeat(users,len(starts));st=np.tile(starts,len(users));return dict(global_u=u,start=st,users=users,windows_per_user=len(starts),end=st+19)
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
def child(script,args,key):
 import psutil
 gate();log=P/f'logs/{key}.log';log.parent.mkdir(parents=True,exist_ok=True);start=time.time();dump(OUT/'STATUS.json',dict(utc=utc(),stage=key,safety_stop_local=None))
 with log.open('w',encoding='utf8') as h:
  proc=subprocess.Popen([str(PY),'-X','utf8','-B',str(CODE/script),*map(str,args)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  dump(P/f'active/{key}.json',dict(pid=proc.pid,key=key,script=script,started_utc=utc()))
  reason=None
  while proc.poll() is None:
   now=time.time()
   if now>=DEADLINE or now-start>=RUN_LIMIT:
    reason='NOT RUN (time)' if now>=DEADLINE else 'TIMEOUT'
    try:
     owner=psutil.Process(proc.pid)
     for descendant in reversed(owner.children(recursive=True)):
      if str(CODE/script) in descendant.cmdline():descendant.kill()
     owner.kill()
    except psutil.NoSuchProcess:pass
    break
   time.sleep(.5)
  proc.wait();rc=reason or proc.returncode
 r=dict(utc=utc(),key=key,exit=rc,status='ok' if rc==0 else str(rc),wall_seconds=time.time()-start,log=str(log));dump(P/f'outcomes/{key}.json',r);return r
