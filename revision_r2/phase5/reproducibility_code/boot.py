from p5common import *
from numba import njit,prange,set_num_threads
set_num_threads(2)
@njit(parallel=True)
def weighted_curves(y,u,ends,counts):
    ap=np.empty(len(counts));roc=np.empty(len(counts))
    for r in prange(len(counts)):
        tp=0.;total=0.;lasttp=0.;lastfp=0.;area=0.;discord=0.;e=0
        for i in range(len(y)):
            w=float(counts[r,u[i]]);total+=w;tp+=w*y[i]
            if i==ends[e]:
                fp=total-tp;dtp=tp-lasttp;dfp=fp-lastfp
                if dtp>0 and total>0:area+=dtp*tp/total;discord+=dtp*(fp-.5*dfp)
                lasttp=tp;lastfp=fp;e+=1
        ap[r]=area/tp if tp>0 else np.nan
        roc[r]=1-discord/(tp*(total-tp)) if tp>0 and total>tp else np.nan
    return ap,roc
def counts_for(n):
    rng=np.random.default_rng(42)
    return np.array([np.bincount(rng.integers(0,n,size=n),minlength=n) for _ in range(2000)],np.int16)
def bootstrap(y,p,u,counts):
    order=np.argsort(-p,kind='stable');sp=p[order];ends=np.r_[np.flatnonzero(np.diff(sp)),len(sp)-1]
    return weighted_curves(y[order],u[order],ends,counts)
def contrast(a,b,point):
    d=np.asarray(a)-np.asarray(b);valid=d[np.isfinite(d)];lo,hi=np.percentile(valid,[2.5,97.5]) if len(valid) else (np.nan,np.nan)
    return dict(estimate=float(point),ci95_low=float(lo),ci95_high=float(hi),valid_bootstrap_replicates=len(valid),decision='ranks below' if hi<0 else ('ranks above (bounded to the evaluated cohort)' if lo>0 else 'comparable / not distinguishable'))
def selfcheck():
    from sklearn.metrics import average_precision_score,roc_auc_score
    y=np.array([1,0,1,0,0,1],np.int8);p=np.array([.9,.9,.6,.4,.4,.1]);u=np.array([0,1,0,1,2,2],np.int16);c=np.array([[1,1,1],[2,0,1],[0,1,2]],np.int16)
    ap,roc=bootstrap(y,p,u,c)
    assert np.allclose(ap,[average_precision_score(y,p,sample_weight=r[u]) for r in c],atol=1e-13)
    assert np.allclose(roc,[roc_auc_score(y,p,sample_weight=r[u]) for r in c],atol=1e-13)
if __name__=='__main__':selfcheck();print('AP and ROC user-weighted tie checks passed')
