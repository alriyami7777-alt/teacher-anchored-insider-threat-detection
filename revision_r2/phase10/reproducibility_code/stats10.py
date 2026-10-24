from common10 import *
from numba import njit,prange,set_num_threads
from sklearn.metrics import average_precision_score
set_num_threads(2)
METRICS=('PR_AUC','AP_over_prevalence','insiders_detected','noninsiders_flagged','top1_insider_recall')
@njit(parallel=True)
def weighted_ap(y,u,ends,w):
 out=np.empty(len(w))
 for r in prange(len(w)):
  tp=0.;total=0.;last=0.;area=0.;e=0
  for i in range(len(y)):
   v=float(w[r,u[i]]);total+=v;tp+=v*y[i]
   if i==ends[e]:
    if tp>last and total>0:area+=(tp-last)*tp/total
    last=tp;e+=1
  out[r]=area/tp if tp>0 else np.nan
 return out
def counts(N):
 p=P/f'bootstrap_counts_{N}.npy'
 if not p.exists():
  rng=np.random.default_rng(42);np.save(p,np.array([np.bincount(rng.integers(0,N,N),minlength=N) for _ in range(2000)],np.int16))
 return np.load(p)
def interval(v,estimate):
 v=np.asarray(v);finite=v[np.isfinite(v)];lo,hi=np.percentile(finite,[2.5,97.5]) if len(finite) else (np.nan,np.nan);pv=min(1.,2*min((1+np.count_nonzero(finite<=0))/(1+len(finite)),(1+np.count_nonzero(finite>=0))/(1+len(finite)))) if len(finite) else 1.
 return dict(estimate=estimate,ci95_low=lo,ci95_high=hi,attempted_replicates=len(v),valid_replicates=len(finite),p_unadjusted=pv,CI_direction='above' if lo>0 else 'below' if hi<0 else 'compatible')
def one(key,release,p,t,co,reference=None):
 d=P/'metrics';d.mkdir(exist_ok=True);jp=d/f'{key}.json';bp=d/f'{key}.npz'
 if jp.exists():return
 gate();u=co['u'];y=co['y'];N=co['N'];ins=co['ins'].astype(bool);w=counts(N);pos=np.bincount(u,weights=y,minlength=N);total=np.bincount(u,minlength=N);prev=y.mean()
 if reference:
  rp=read(d/f'{reference}.json');rb=dict(np.load(d/f'{reference}.npz'));ap=rp['PR_AUC'];aprep=rb['PR_AUC'];toprep=rb['top1_insider_recall'];top=rp['top1_insider_recall']
 else:
  order=np.argsort(-p,kind='stable');ends=np.r_[np.flatnonzero(np.diff(p[order])),len(p)-1];ap=average_precision_score(y,p);aprep=weighted_ap(y[order].astype(np.int8),u[order].astype(np.int32),ends,w);mx=np.full(N,-np.inf);np.maximum.at(mx,u,p);rank=np.lexsort((co['ids'],-mx));topset=np.zeros(N);topset[rank[:int(np.ceil(.01*N))]]=1;top=(topset*ins).sum()/ins.sum();den=w@ins;toprep=np.divide(w@(topset*ins),den,out=np.full(len(w),np.nan),where=den>0)
 gate();det=np.bincount(u,weights=(y==1)&(p>=t),minlength=N)>0;flags=(np.bincount(u,weights=p>=t,minlength=N)>0)&~ins;prevrep=(w@pos)/(w@total);point=dict(key=key,release=release,PR_AUC=float(ap),AP_over_prevalence=float(ap/prev),insiders_detected=int(det.sum()),noninsiders_flagged=int(flags.sum()),top1_insider_recall=float(top),insiders_total=int(ins.sum()),noninsiders_total=int((~ins).sum()),insiders_with_eligible_positive_windows=int(np.sum((pos>0)&ins)),windows=len(y),positive_windows=int(y.sum()),prevalence=prev,threshold=t,top1_user_budget=int(np.ceil(.01*N)),utc=utc());reps=dict(PR_AUC=aprep,AP_over_prevalence=aprep/prevrep,insiders_detected=w@det,noninsiders_flagged=w@flags,top1_insider_recall=toprep);np.savez_compressed(bp,**reps);point['metric_CIs']={k:{a:b for a,b in interval(v,point[k]).items() if a!='p_unadjusted'} for k,v in reps.items()};dump(jp,point);print('METRICS_COMPLETE',key,flush=True)
def scan():
 gate();co=cohort();co5=None
 for s in SEEDS:
  for n in MODELS:
   key=f'zero_{n}_{s}_r62'
   if not (P/f'metrics/{key}.json').exists():one(key,'r62',cached(n,s,co),oldspec(n,s)['threshold'],co)
  f=OUT/f'P1_THRESHOLDS_{s}.json'
  if f.exists():
   for row in read(f)['records']:
    n=row['model'];one(f'P1_{n}_{s}_r62','r62',cached(n,s,co),row['threshold'],co,f'zero_{n}_{s}_r62')
 for f in sorted((P/'complete').glob('*.json')):
  z=read(f);key=z['key'];release=key.rsplit('_',1)[1]
  if (P/f'metrics/{key}.json').exists():continue
  if release=='r52' and co5 is None:co5=cohort('r52')
  one(key,release,np.load(P/f'scores/{key}.npy',mmap_mode='r'),z['threshold'],co if release=='r62' else co5)
  if release=='r52':
   c,n,s,rel=key.split('_',1)[0],None,None,None
   # Recover model/seed without splitting the XGBoost_40 model name.
   for model in MODELS:
    for seed in SEEDS:
     if key==f'pooled_{model}_{seed}_r52':one(f'zero_{model}_{seed}_r52','r52',cached(model,seed,co5,'r52'),oldspec(model,seed)['threshold'],co5)
 dump(OUT/'METRICS_SCAN_COMPLETE.json',dict(utc=utc(),metric_files=len(list((P/'metrics').glob('*.json')))))
if __name__=='__main__':scan()
