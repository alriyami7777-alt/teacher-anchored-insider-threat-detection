from common6 import *
from numba import njit,prange,set_num_threads
set_num_threads(2)
@njit(parallel=True)
def weighted_ap(y,u,ends,counts):
 ap=np.empty(len(counts))
 for r in prange(len(counts)):
  tp=0.;total=0.;lasttp=0.;area=0.;e=0
  for i in range(len(y)):
   w=float(counts[r,u[i]]);total+=w;tp+=w*y[i]
   if i==ends[e]:
    dtp=tp-lasttp
    if dtp>0 and total>0:area+=dtp*tp/total
    lasttp=tp;e+=1
  ap[r]=area/tp if tp>0 else np.nan
 return ap
def counts(n):
 rng=np.random.default_rng(42)
 return np.array([np.bincount(rng.integers(0,n,size=n),minlength=n) for _ in range(2000)],np.int16)
def bootstrap(y,p,u,c,t=None):
 order=np.argsort(-p,kind='stable');sp=p[order];ends=np.r_[np.flatnonzero(np.diff(sp)),len(sp)-1]
 ap=weighted_ap(np.asarray(y,np.int8)[order],u[order],ends,c)
 if t is None:return ap
 flag=p>=t;n=c.shape[1]
 tp=np.bincount(u,weights=(y==1)&flag,minlength=n);fp=np.bincount(u,weights=(y==0)&flag,minlength=n);fn=np.bincount(u,weights=(y==1)&~flag,minlength=n)
 a=c@tp;b=c@fp;d=c@fn;den=2*a+b+d;f1=np.divide(2*a,den,out=np.zeros_like(a),where=den>0)
 return dict(PR_AUC=ap,F1=f1)
def ci(values,estimate):
 a=np.asarray(values);v=a[np.isfinite(a)];lo,hi=np.percentile(v,[2.5,97.5]) if len(v) else [np.nan,np.nan]
 return dict(estimate=float(estimate),ci95_low=float(lo),ci95_high=float(hi),valid_bootstrap_replicates=len(v),attempted_replicates=len(a),bootstrap_seed=42,cluster='user')
def selfcheck():
 from sklearn.metrics import average_precision_score,f1_score
 y=np.array([1,0,1,0,0,1]);p=np.array([.9,.9,.6,.4,.4,.1]);u=np.array([0,1,0,1,2,2]);c=np.array([[1,1,1],[2,0,1],[0,1,2]])
 out=bootstrap(y,p,u,c,.5)
 assert np.allclose(out['PR_AUC'],[average_precision_score(y,p,sample_weight=r[u]) for r in c])
 assert np.allclose(out['F1'],[f1_score(y,p>=.5,sample_weight=r[u]) for r in c])
if __name__=='__main__':selfcheck();print('Paired user bootstrap verified')
