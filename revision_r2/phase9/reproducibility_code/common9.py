from pathlib import Path
import os,sys,json,hashlib,time,subprocess
sys.dont_write_bytecode=True
for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMBA_NUM_THREADS'):os.environ[k]='2'
import numpy as np,pandas as pd
CODE=Path(__file__).resolve().parent;ROOT=Path(r'C:\PhD\07_Projects\r2_holdout');R2=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision');OUT=R2/'phase9';PRIVATE=OUT/'private';HP=R2/'holdout/private';P4=R2/'holdout/phase4';P4P=HP/'phase4';P5=R2/'phase5';P8=R2/'phase8';B6P=R2/'phase6b/private';EXPL=R2/'explanation/holdout';PYTHON=ROOT/'phase4/.venv/Scripts/python.exe';SEEDS=(42,52,62);ALL=SEEDS+(72,82,92,102,112);CONFIGS=('reduced','flip01','flip05','flip10','backdoor01');RELEASES=('r5.2_HOLDOUT','r5.1','r6.1','r6.2');MODELS=('TA2','F00','L1','XGBoost_40')
FEATURES=['total_events','logon_count','device_count','file_count','email_count','http_count','active_duration_minutes','has_logon_activity','has_device_activity','has_file_activity','has_email_activity','has_http_activity','is_active_day']
sys.path.insert(0,str(ROOT));import phase2_runtime as rt
def utc():
 from datetime import datetime,timezone
 return datetime.now(timezone.utc).isoformat()
def sha(p):return rt.sha(p)
def clean(x):
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(tuple,list,set)):return [clean(v) for v in x]
 if isinstance(x,np.ndarray):return clean(x.tolist())
 if isinstance(x,np.generic):return clean(x.item())
 if isinstance(x,Path):return str(x)
 if isinstance(x,float) and not np.isfinite(x):return None
 return x
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def dump(p,v):rt.dump(p,clean(v))
def csv(n,v):pd.DataFrame(clean(v)).to_csv(OUT/n,index=False)
def status(stage,**kw):dump(OUT/'STATUS.json',dict(utc=utc(),stage=stage,**kw));print(utc(),stage,kw,flush=True)
def pseudo(u):return 'U_'+hashlib.sha256(str(u).encode()).hexdigest()[:10]
def gate():
 a=read(OUT/'AMENDMENT9_RECEIPT.json');p=(R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md').read_bytes();assert hashlib.sha256(p[:a['hashed_bytes']]).hexdigest()==a['sha256'];assert sha(P8/'CHATGPT_PHASE8_REPORT.md')==a['phase8_report_sha256'];assert read(P8/'FINAL_AUDIT.json')['all_checks_passed']
def device():
 import torch
 torch.set_num_threads(2);assert torch.cuda.is_available();torch.cuda.set_per_process_memory_fraction(.35);return torch.device('cuda')
def oldspec(n,s):return next(z for z in read(P4/'MODELS_FROZEN_PHASE4.json')['models'] if z['model']==n and z['seed']==s) if s in SEEDS else read(P8/f'private/training/results/{n}_{s}.json')
def spec(c,n,s):return read(PRIVATE/f'training/{c}/results/{n}_{s}.json')
def loadmodel(sp,dv,features=None):
 import torch
 assert sha(sp['checkpoint'])==sp['sha256'];n=sp['model']
 if n=='XGBoost_40':
  from xgboost import XGBClassifier
  m=XGBClassifier();m.load_model(sp['checkpoint']);m.set_params(n_jobs=2);return m
 arch=dict(rt.ENCODER_ARCH,input_dim=len(features) if features is not None else 13);m=rt.AttentionNodeEnsemble(**arch)
 if n=='L1':m.linear_head=torch.nn.Linear(128,1)
 m.load_state_dict(torch.load(sp['checkpoint'],map_location='cpu',weights_only=False)['model_state_dict']);return m.to(dv).eval()
def aggregate(x,keep=None):
 keep=list(range(13)) if keep is None else list(keep);cols=[];names=[]
 for i,j in enumerate(keep):
  v=x[:,:,i];ops=(('sum',v.sum(1)),('mean',v.mean(1)),('max',v.max(1)),('std',v.std(1))) if j<7 else (('active_days',v.sum(1)),('active_proportion',v.mean(1)))
  for n,a in ops:cols.append(a.astype(np.float32));names.append(FEATURES[j]+'_'+n)
 return np.stack(cols,1),names
def predict(m,n,x,dv,keep=None):
 import torch
 if n=='XGBoost_40':return m.predict_proba(aggregate(x,keep)[0])[:,1].astype(float)
 with torch.no_grad():return rt.probs(rt.forward(m,torch.as_tensor(x,device=dv),'linear' if n=='L1' else 'odst')['logit'].cpu().numpy())
def original(n,s,release='r5.2_HOLDOUT'):
 if release=='r5.2_HOLDOUT':return np.load(P4P/f'scores/{n}_{s}.npz')['scores'] if s in SEEDS else np.load(P8/f'private/scores/{n}_{s}.npy')
 if release in ('r5.1','r6.2'):return np.load(P5/f'private/transfer/{release}/development_{n}_{s}.npy',mmap_mode='r')
 if n=='TA2':return np.load(P8/f'private/Q5/r6.1_{s}.npy',mmap_mode='r')
 return np.load(PRIVATE/f'scores/zero_r6.1_{n}_{s}.npy',mmap_mode='r')
def holdmeta():return dict(np.load(B6P/'cohorts/T20_metadata.npz'))
def operational():return dict(np.load(P5/'private/HOLDOUT_OPERATIONAL_METADATA.npz'))
def bundle(c):return {part:{k:np.load(PRIVATE/f'data/{c}/{part}_{k}.npy',mmap_mode='c') for k in ('X','X40','y')} for part in ('train','validation')}
def scaler():return read(P5/'MODELS_AND_METHODS_FROZEN_PHASE5.json')['scalers']
class Cohort:
 def __init__(self,release,labels=False):
  self.release=release
  if release=='r5.2_HOLDOUT':
   self.meta=holdmeta() if labels else None;self.x=np.load(P4P/'HOLDOUT_COHORT.npz')['X'];self.n=len(self.x)
   if labels:self.u=self.meta['cluster'];self.y=self.meta['y'];self.N=500;self.ids=operational()['user']
  else:
   self.folder=Path(read(P5/'MODELS_AND_METHODS_FROZEN_PHASE5.json')['bundles'][release]['folder']);self.dense=np.load(self.folder/'scaled_dense_daily.npy',mmap_mode='r')
   if release=='r6.1':self.u=np.load(self.folder/'window_user_index.npy');self.start=np.load(self.folder/'window_start_index.npy')
   else:ix=np.load(self.folder/'window_index.npy');self.u=ix[:,0];self.start=ix[:,1]
   self.n=len(self.u);self.N=len(self.dense);self.ids=np.array([f'U_{i:06d}' for i in range(self.N)])
   if labels:self.y=np.load(self.folder/'completed_window_labels.npy')
 def batch(self,lo,hi,mode='zero',keep=None):
  if self.release=='r5.2_HOLDOUT':x=np.array(self.x[lo:hi])
  else:
   x=self.dense[self.u[lo:hi,None].astype(int),self.start[lo:hi,None].astype(int)+np.arange(20)].astype(float);s=scaler();x=x*np.array(s['original']['scale'])+np.array(s['original']['mean']);st=s['development'] if mode=='zero' else read(OUT/'L1_TARGET_SCALERS_FROZEN.json')['releases'][self.release];x=((x-np.array(st['mean']))/np.array(st['scale'])).astype(np.float32)
  return x if keep is None else x[:,:,keep]
def consume(name,**kw):
 p=PRIVATE/f'consumed/{name}.json';p.parent.mkdir(exist_ok=True)
 with p.open('x',encoding='utf-8') as h:json.dump(clean(dict(utc=utc(),condition=name,**kw)),h,indent=2)
 return p
def child(script,args,key):
 log=PRIVATE/f'logs/{key}.log'
 with log.open('w',encoding='utf-8') as h:
  p=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/script),*map(str,args)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  try:rc=p.wait(timeout=7200)
  except subprocess.TimeoutExpired:p.kill();p.wait();rc='TIMEOUT'
 r=dict(utc=utc(),key=key,script=script,args=args,exit=rc,status='ok' if rc==0 else 'TIMEOUT' if rc=='TIMEOUT' else 'FAILED',log=str(log));dump(PRIVATE/f'outcomes/{key}.json',r);return r
