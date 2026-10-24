from common11 import *
from metadata11 import ensure_metadata
from numba import njit,prange,set_num_threads
from sklearn.metrics import average_precision_score,roc_auc_score
set_num_threads(2)
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
@njit(parallel=True)
def weighted_roc(y,u,ends,w):
 out=np.empty(len(w))
 for r in prange(len(w)):
  area=0.;positives=0.;negatives=0.;gp=0.;gn=0.;e=0
  for i in range(len(y)):
   v=float(w[r,u[i]])
   if y[i]:gp+=v
   else:gn+=v
   if i==ends[e]:
    area+=gp*(negatives+.5*gn);positives+=gp;negatives+=gn;gp=0.;gn=0.;e+=1
  out[r]=area/(positives*negatives) if positives>0 and negatives>0 else np.nan
 return out
def counts():
 p=P/'bootstrap_counts_4000.npy'
 if not p.exists():
  rng=np.random.default_rng(42);np.save(p,np.array([np.bincount(rng.integers(0,4000,4000),minlength=4000) for _ in range(2000)],np.int16))
 return np.load(p)
def interval(values,estimate):
 v=np.asarray(values);finite=v[np.isfinite(v)];lo,hi=np.percentile(finite,[2.5,97.5]) if len(finite) else (np.nan,np.nan);p=min(1.,2*min((1+np.count_nonzero(finite<=0))/(1+len(finite)),(1+np.count_nonzero(finite>=0))/(1+len(finite)))) if len(finite) else 1.
 return dict(estimate=estimate,ci95_low=lo,ci95_high=hi,attempted_replicates=len(v),valid_replicates=len(finite),p_unadjusted=p)
def user_metrics(key,p,u,end,y,users,thresholds,metadata,daily_budget=True):
 users=np.asarray(users);N=len(users);local=np.searchsorted(users,u);assert np.array_equal(users[local],u);official=metadata['official'][users].astype(bool);affected=metadata['affected'][users].astype(bool);normal=~affected;names=metadata['pseudonyms'][users];mx=np.full(N,-np.inf);np.maximum.at(mx,local,p);assert np.isfinite(mx).all();rank=np.lexsort((names,-mx));ranks=np.empty(N,int);ranks[rank]=np.arange(1,N+1);eligible=official|normal;userroc=lambda target,mask:float(roc_auc_score(target[mask],mx[mask])) if len(np.unique(target[mask]))==2 else None
 threshold_user=np.asarray(thresholds);threshold_user=np.full(N,float(threshold_user)) if threshold_user.ndim==0 else threshold_user;flag=mx>=threshold_user;malicious_detection=np.bincount(local,weights=(y==1)&(p>=threshold_user[local]),minlength=N)>0
 result=dict(key=key,users=N,official_total=int(official.sum()),affected_total=int(affected.sum()),normal_total=int(normal.sum()),user_ROC_official=userroc(official,eligible),user_ROC_affected=userroc(affected,np.ones(N,bool)),official_flagged=int((flag&official).sum()),affected_flagged=int((flag&affected).sum()),normal_flagged=int((flag&normal).sum()),official_malicious_window_detected=int((malicious_detection&official).sum()),affected_malicious_window_detected=int((malicious_detection&affected).sum()),official_with_positive_windows=int(np.sum((np.bincount(local,weights=y,minlength=N)>0)&official)),affected_with_positive_windows=int(np.sum((np.bincount(local,weights=y,minlength=N)>0)&affected)),official_ranks=[dict(pseudonym=str(names[i]),scenario=str(metadata['scenarios'][users[i]]),rank=int(ranks[i])) for i in np.flatnonzero(official)],top_budgets=[])
 for fraction in (.01,.02,.05):
  selected=rank[:int(np.ceil(fraction*N))];result['top_budgets'].append(dict(fraction=fraction,users_budget=len(selected),official=int(official[selected].sum()),affected=int(affected[selected].sum())))
 result['fold_threshold_detection']=[]
 for fold in sorted(set(metadata['fold'][users].tolist())):
  mask=metadata['fold'][users]==fold
  result['fold_threshold_detection'].append(dict(fold=int(fold),threshold=float(threshold_user[np.flatnonzero(mask)[0]]),users=int(mask.sum()),official_total=int((mask&official).sum()),affected_total=int((mask&affected).sum()),normal_total=int((mask&normal).sum()),official_flagged=int((mask&official&flag).sum()),affected_flagged=int((mask&affected&flag).sum()),normal_flagged=int((mask&normal&flag).sum()),official_malicious_window_detected=int((mask&official&malicious_detection).sum()),affected_malicious_window_detected=int((mask&affected&malicious_detection).sum())))
 if daily_budget:
  gate();rawdaily=np.load(B/'malicious_day_labels.npy',mmap_mode='r');bits=np.load(B/'answer_scenario_day_bitmask.npy',mmap_mode='r');hits=[];caught={budget:set() for budget in (5,10,20)};enddates=np.unique(end);first={int(i):int(np.flatnonzero(rawdaily[i])[0]) for i in users[affected]}
  for day in enddates:
   ix=np.flatnonzero(end==day);assert len(ix)==N and len(np.unique(u[ix]))==N;sort=np.lexsort((metadata['pseudonyms'][u[ix]],-p[ix]));ordered=ix[sort]
   for budget in (5,10,20):
    for j in ordered[:budget]:
     account=int(u[j])
     if rawdaily[account,day]>0:
      caught[budget].add(account);bitmask=int(bits[account,day]);scenarios=','.join(str(number) for number in range(1,6) if bitmask&(1<<(number-1)));hits.append(dict(key=key,budget=budget,pseudonym=str(metadata['pseudonyms'][account]),official=bool(metadata['official'][account]),calendar_date=str(metadata['dates'][day]),scenario=scenarios,scenario_day_since_first_malicious=int(day)-first[account]+1,malicious_day_ordinal=int(np.count_nonzero(rawdaily[account,:int(day)+1])),daily_rank=int(np.flatnonzero(ordered==j)[0])+1))
  result['daily_budgets']=[dict(budget=budget,ending_window_days=len(enddates),official_caught=int(sum(metadata['official'][i] for i in values)),affected_caught=len(values),distinct_caught_pseudonyms=sorted(str(metadata['pseudonyms'][i]) for i in values)) for budget,values in caught.items()];pd.DataFrame(hits,columns=['key','budget','pseudonym','official','calendar_date','scenario','scenario_day_since_first_malicious','malicious_day_ordinal','daily_rank']).to_csv(OUT/f'DAILY_HITS_{key}.csv',index=False)
 return result,mx
def full(c,n,s,metadata):
 key=f'{c}_{n}_{s}';path=P/f'metrics/{key}.json'
 if path.exists():return
 receipts=[P/f'complete/{c}_fold{k}_{n}_{s}_r62.json' for k in range(1,5)]
 if not all(p.exists() for p in receipts):return
 gate();Nw=len(metadata['y']);p=np.empty(Nw,float);thresholds=np.empty(4000);peruser=Nw//4000
 for k,receiptpath in enumerate(receipts,1):
  receipt=read(receiptpath);users=np.load(P/f'FOLD{k}_HELDOUT.npy');values=np.load(P/f'scores/{receipt["key"]}.npy',mmap_mode='r');assert len(values)==len(users)*peruser;p.reshape(4000,peruser)[users]=values.reshape(len(users),peruser);thresholds[users]=receipt['threshold']
 y=metadata['y'];u=metadata['u'];point,mx=user_metrics(key,p,u,metadata['end'],y,np.arange(4000),thresholds,metadata);ap=float(average_precision_score(y,p));point.update(condition=c,model=n,seed=s,windows=len(y),positive_windows=int(y.sum()),prevalence=float(y.mean()),PR_AUC=ap,AP_over_prevalence=ap/y.mean(),window_ROC_AUC=float(roc_auc_score(y,p)),utc=utc(),OOF_all_four_folds=True)
 w=counts();order=np.argsort(-p,kind='stable');ends=np.r_[np.flatnonzero(np.diff(p[order])),len(p)-1];replicates=dict(PR_AUC=weighted_ap(y[order],u[order],ends,w));official=metadata['official'].astype(bool);affected=metadata['affected'].astype(bool)
 for name,labels,mask in [('user_ROC_official',official,official|~affected),('user_ROC_affected',affected,np.ones(4000,bool))]:
  ix=np.flatnonzero(mask);order=ix[np.argsort(mx[ix],kind='stable')];ends=np.r_[np.flatnonzero(np.diff(mx[order])),len(order)-1];replicates[name]=weighted_roc(labels[order],order.astype(np.int32),ends,w)
 point['metric_CIs']={name:{k:v for k,v in interval(values,point[name]).items() if k!='p_unadjusted'} for name,values in replicates.items()};(P/'metrics').mkdir(exist_ok=True);np.savez_compressed(P/f'metrics/{key}.npz',**replicates);dump(path,point);print('OOF_METRICS_COMPLETE',key,flush=True)
def cost(receipt):
 key=receipt['key'];path=P/f'cost/{key}.json'
 if path.exists():return
 z=dict(np.load(R2/'phase6b/private/cohorts/T20_metadata.npz'));op=dict(np.load(P5/'private/HOLDOUT_OPERATIONAL_METADATA.npz'));y=z['y'];u=z['cluster'].astype(int);ins=op['insider'].astype(bool);p=np.load(P/f'scores/{key}.npy',mmap_mode='r');flag=np.bincount(u,weights=p>=receipt['threshold'],minlength=500)>0;det=np.bincount(u,weights=(y==1)&(p>=receipt['threshold']),minlength=500)>0;dump(path,dict(key=key,condition=receipt['condition'],model=receipt['model'],seed=receipt['seed'],fold=1,PR_AUC=float(average_precision_score(y,p)),insiders_detected=int((det&ins).sum()),insiders_flagged_any_window=int((flag&ins).sum()),normal_flagged=int((flag&~ins).sum()),insiders_total=int(ins.sum()),normal_total=int((~ins).sum()),threshold=receipt['threshold'],evaluation_only=True))
def posthoc(metadata):
 gate();users=np.load(P10/'private/HOLDOUT_indices.npy');wi=np.load(B/'window_index.npy',mmap_mode='r');sp=read(OUT/'FOLD_RECEIPT.json');nt=sp['n_train_days'];nv=sp['n_validation_days'];mask=np.isin(wi[:,0],users)&((wi[:,1]<=nt-20)|((wi[:,1]>=nt)&(wi[:,1]<=nt+nv-20)));rows=np.flatnonzero(mask);u=wi[rows,0];end=wi[rows,1]+19;y=np.load(B/'completed_window_labels.npy',mmap_mode='r')[rows];oldmodels=read(P4/'MODELS_FROZEN_PHASE4.json')['models']
 for condition in ('zero','within'):
  for n in ('TA2','F00','XGBoost_40'):
   for seed in SEEDS:
    key=f'POSTHOC_{condition}_{n}_{seed}';dest=P/f'posthoc/{key}.json'
    if dest.exists():continue
    gate()
    if condition=='zero':p=np.load(P5/f'private/transfer/r6.2/development_{n}_{seed}.npy',mmap_mode='r')[rows];threshold=next(z['threshold'] for z in oldmodels if z['model']==n and z['seed']==seed)
    else:
     p=np.load(P10/f'private/scores/within_{n}_{seed}_r62.npy',mmap_mode='r');threshold=read(P10/f'private/complete/within_{n}_{seed}_r62.json')['threshold']
    result,_=user_metrics(key,p,u,end,y,users,threshold,metadata);result.pop('fold_threshold_detection');result.update(condition=condition,model=n,seed=seed,threshold=threshold,label='POST HOC, DESCRIPTIVE: original Phase10 held-out subset only; not Phase11 OOF; no formal contrast',utc=utc());dump(dest,result);print('POSTHOC_COMPLETE',key,flush=True)
def scan():
 gate();f=read(OUT/'ANALYSIS_CODE_FROZEN.json');assert all(sha(CODE/name)==value for name,value in f['code'].items());metadata=ensure_metadata()
 for c in ('C1','C2','C3','C4'):
  for n in (('F00',) if c=='C4' else MODELS):
   for seed in SEEDS:full(c,n,seed,metadata)
 for path in sorted((P/'complete').glob('*_r52.json')):cost(read(path))
 posthoc(metadata);dump(OUT/'METRICS_SCAN_COMPLETE.json',dict(utc=utc(),OOF_metric_rows=len(list((P/'metrics').glob('*.json'))),posthoc_rows=len(list((P/'posthoc').glob('*.json'))),cost_rows=len(list((P/'cost').glob('*.json')))))
if __name__=='__main__':scan()
