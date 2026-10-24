from common9 import *
from numba import njit,prange,set_num_threads
from sklearn.metrics import average_precision_score
set_num_threads(2)
@njit(parallel=True)
def ap_weighted(y,u,ends,counts):
 out=np.empty(len(counts))
 for r in prange(len(counts)):
  tp=0.;tot=0.;last=0.;area=0.;e=0
  for i in range(len(y)):
   w=float(counts[r,u[i]]);tot+=w;tp+=w*y[i]
   if i==ends[e]:
    if tp>last and tot>0:area+=(tp-last)*tp/tot
    last=tp;e+=1
  out[r]=area/tp if tp>0 else np.nan
 return out
def counts(N):
 p=PRIVATE/f'bootstrap_counts_{N}.npy'
 if not p.exists():
  rng=np.random.default_rng(42);np.save(p,np.array([np.bincount(rng.integers(0,N,N),minlength=N) for _ in range(2000)],np.int16))
 return np.load(p)
def apboot(y,p,u,w):
 order=np.argsort(-p,kind='stable');sp=p[order];ends=np.r_[np.flatnonzero(np.diff(sp)),len(sp)-1];return ap_weighted(y[order].astype(np.int8),u[order].astype(np.int32),ends,w)
def interval(a,estimate,null=0,one_sided=False):
 v=np.array(a);v=v[np.isfinite(v)];lo,hi=np.percentile(v,[2.5,97.5]) if len(v) else (np.nan,np.nan);p=(1+np.count_nonzero(v-estimate<=-(estimate-null)))/(len(v)+1) if one_sided and len(v) else (1+np.count_nonzero(np.abs(v-estimate)>=abs(estimate-null)))/(len(v)+1) if len(v) else 1.
 return dict(estimate=float(estimate),ci95_low=float(lo),ci95_high=float(hi),attempted_replicates=len(a),valid_replicates=len(v),undefined_replicates=len(a)-len(v),p_unadjusted=float(p),CI_direction='above' if lo>null else 'below' if hi<null else 'compatible',null=null)
def holm(rows,family,planned):
 assert len(rows)==planned,(family,len(rows),planned);ps=np.array([r.get('p_unadjusted',1) if r.get('p_unadjusted') is not None else 1 for r in rows]);order=np.argsort(ps,kind='stable');adj=np.maximum.accumulate(np.minimum(1,ps[order]*(planned-np.arange(planned))));adjusted=np.empty(planned);adjusted[order]=adj
 for r,p in zip(rows,adjusted):r.update(Holm_family=family,Holm_family_size=planned,p_Holm=float(p),Holm_reject_0_05=bool(p<.05),exploratory=True)
 return rows
def metricset(co,p,t):
 y=co.y.astype(np.int8);u=co.u.astype(int);N=co.N;w=counts(N);ins=np.bincount(u,weights=y,minlength=N)>0;positive=np.bincount(u,weights=y,minlength=N);total=np.bincount(u,minlength=N);prevboot=(w@positive)/(w@total);ap=float(average_precision_score(y,p));boots=apboot(y,p,u,w);maxscore=np.full(N,-np.inf);np.maximum.at(maxscore,u,p);k=int(np.ceil(.01*N));order=np.lexsort((co.ids,-maxscore));top=np.zeros(N);top[order[:k]]=1;hit=top*ins;den=w@ins;topboot=np.divide(w@hit,den,out=np.full(len(w),np.nan),where=den>0);det=np.bincount(u,weights=(y==1)&(p>=t),minlength=N)>0;flag=(np.bincount(u,weights=p>=t,minlength=N)>0)&~ins
 point=dict(PR_AUC=ap,AP_over_prevalence=ap/float(y.mean()),AP_minus_prevalence=ap-float(y.mean()),top1_insider_recall=float(hit.sum()/ins.sum()),insiders_detected=int(det.sum()),noninsiders_flagged=int(flag.sum()),insiders_total=int(ins.sum()),noninsiders_total=int((~ins).sum()),windows=len(y),positive_windows=int(y.sum()),prevalence=float(y.mean()),threshold=t,top1_user_budget=k)
 rep=dict(PR_AUC=boots,AP_over_prevalence=boots/prevboot,top1_insider_recall=topboot,insiders_detected=w@det,noninsiders_flagged=w@flag);return point,rep
def cachedmetrics(key,co,p,t):
 dest=PRIVATE/'metrics';dest.mkdir(exist_ok=True);j=dest/f'{key}.json';npz=dest/f'{key}.npz'
 if j.exists():return read(j),dict(np.load(npz))
 point,rep=metricset(co,p,t);np.savez_compressed(npz,**rep);dump(j,point);return point,rep
def compare_metrics(L,groups,endpoints,planned):
 # groups: metadata, list(left point/rep), list(right point/rep)
 points=[];rows=[]
 for meta,left,right in groups:
  for label,values in (('new',left),('reference',right)):
   for i,(p,b) in enumerate(values):points.append(meta|dict(condition_side=label,seed=SEEDS[i],**p))
  for i in range(4):
   selected=range(3) if i==3 else [i];seed='mean' if i==3 else SEEDS[i]
   for metric in endpoints:
    est=float(np.mean([left[k][0][metric]-right[k][0][metric] for k in selected]));rep=np.mean([left[k][1][metric]-right[k][1][metric] for k in selected],0);rows.append(meta|dict(seed=seed,metric=metric,contrast='new minus reference',**interval(rep,est)))
 holm(rows,L,planned);csv(f'{L}_METRICS.csv',points);csv(f'{L}_CONTRASTS.csv',rows);dump(OUT/f'{L}_RESULTS.json',dict(utc=utc(),points=points,contrasts=rows,Holm_family_size=planned));return points,rows
def selfcheck():
 from sklearn.metrics import roc_auc_score
 y=np.array([1,0,1,0,0,1],np.int8);p=np.array([.9,.9,.6,.4,.4,.1]);u=np.array([0,1,0,1,2,2]);w=np.array([[1,1,1],[2,0,1],[0,1,2]],np.int16);a=apboot(y,p,u,w);assert np.allclose(a,[average_precision_score(y,p,sample_weight=r[u]) for r in w]);assert np.array_equal(aggregate(np.zeros((3,20,13),np.float32))[0],rt.aggregate_common13_windows(np.zeros((3,20,13),np.float32))[0]);return True
