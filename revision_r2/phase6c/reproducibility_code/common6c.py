from pathlib import Path
import os,sys,json,time,hashlib
sys.dont_write_bytecode=True
for n in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[n]='2'
os.environ['PYTHONUTF8']='1'
CODE=Path(__file__).resolve().parent
sys.path.insert(0,str(CODE.parent/'phase6b_staging'))
import common6b as b
import numpy as np
rt=b.rt;ROOT=b.ROOT;R2=b.R2;H=b.H;HP=b.HP;P4=b.P4;P4P=b.P4P;PYTHON=b.PYTHON;SEEDS=b.SEEDS;EXPL=b.EXPL;REPO=b.REPO
B6=R2/'phase6b';B6P=B6/'private';P5=R2/'phase5';OUT=R2/'phase6c';PRIVATE=OUT/'private'
utc=b.utc;sha=b.sha;clean=b.clean;dump=b.dump;read=b.read;pseudo=b.pseudo;device=b.device;aggregate=b.aggregate;metrics=b.metrics;oldspec=b.oldspec
SOURCES=('logon','device','file','email','http');NOISE=(.025,.05,.075,.1,.15,.2);VIEWS=('pooled_completed','train_completed','validation_completed','pooled_offset0','pooled_endpoint')
sys.path.append(str(REPO/'src'))
from objective3_missing_source_robustness import apply_missing_source_condition
from objective3_perturbations import gaussian_noise_continuous,apply_paired_perturbation
def csv(name,rows):
 import pandas as pd
 pd.DataFrame(rows).to_csv(OUT/name,index=False)
def status(stage,**kw):
 dump(OUT/'STATUS.json',dict(utc=utc(),stage=stage,**kw));print(utc(),stage,kw,flush=True)
def scaler():
 s=read(HP/'DEVELOPMENT_DAILY_SCALER.json');return dict(mean=np.array(s['mean']),scale=np.array(s['scale']))
def augment(x,rng,sc):
 out=np.array(x,np.float32,copy=True);n=len(out);drop=rng.random(n)<.3;source=rng.integers(0,5,n);noisy=rng.random(n)<.3;level=rng.integers(0,6,n)
 for j,s in enumerate(SOURCES):
  ix=np.flatnonzero(drop&(source==j))
  if len(ix):out[ix]=apply_missing_source_condition(out[ix],'without_'+s,sc)
 for j,l in enumerate(NOISE):
  ix=np.flatnonzero(noisy&(level==j))
  if len(ix):out[ix]=gaussian_noise_continuous(out[ix],l,rng)
 assert np.isfinite(out).all()
 return out,dict(windows=n,source_dropped=int(drop.sum()),noised=int(noisy.sum()),both=int((drop&noisy).sum()))
def conditions():return [('clean',0.)]+[(s,r) for s in SOURCES for r in (.25,.5,.75,1.)]+[('noise',r) for r in NOISE]
def key(s,l):return 'clean' if s=='clean' or l==0 else f'{s}_{l:.3f}'
def perturb(x,s,l):
 if l==0:return x
 if s=='noise':return apply_paired_perturbation(x,'gaussian_noise_continuous',l,perturbation_seed=101)
 full=apply_missing_source_condition(x,'without_'+s,scaler());return ((1-l)*x+l*full).astype(np.float32)
def view(m,v):
 mask=np.ones(len(m['y']),bool)
 if v=='train_completed':mask=m['partition']=='train'
 elif v=='validation_completed':mask=m['partition']=='validation'
 elif v=='pooled_offset0':mask=m['offset0'].astype(bool)
 return np.flatnonzero(mask),m['endpoint'] if v=='pooled_endpoint' else m['y']
def summary(values,est):
 a=np.asarray(values);v=a[np.isfinite(a)];lo,hi=np.percentile(v,[2.5,97.5]) if len(v) else [np.nan,np.nan];p=min(1.,2*min((1+np.sum(v<=0))/(1+len(v)),(1+np.sum(v>=0))/(1+len(v)))) if len(v) else 1.
 return dict(estimate=est,ci95_low=float(lo),ci95_high=float(hi),raw_p=float(p),valid_bootstrap_replicates=len(v),attempted_replicates=len(a),CI_decision='above' if lo>0 else 'below' if hi<0 else 'comparable')
def holm(rows):
 order=np.argsort([r['raw_p'] for r in rows],kind='stable');running=0.;n=len(rows)
 for j,i in enumerate(order):
  r=rows[i];running=max(running,min(1.,(n-j)*r['raw_p']));r.update(Holm_p=running,Holm_family_size=n,Holm_decision='above' if running<.05 and r['estimate']>0 else 'below' if running<.05 and r['estimate']<0 else 'comparable')
 return rows
