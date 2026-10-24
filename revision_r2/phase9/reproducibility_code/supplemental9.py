"""Complete predeclared marginal/seed-mean intervals from saved scores and bootstrap caches only."""
from common9 import *
from stats9 import counts,interval
def cached(key):return read(PRIVATE/f'metrics/{key}.json'),dict(np.load(PRIVATE/f'metrics/{key}.npz'))
def cirow(meta,metric,estimate,rep):
 v=interval(rep,estimate);return meta|dict(metric=metric,**{k:x for k,x in v.items() if k not in ('p_unadjusted','null','CI_direction')},interpretation='descriptive marginal interval; no extra null test')
def append_group(rows,meta,values,metrics):
 for i in range(4):
  selected=range(3) if i==3 else [i]
  for metric in metrics:rows.append(cirow(meta|dict(seed='mean' if i==3 else SEEDS[i]),metric,np.mean([values[j][0][metric] for j in selected]),np.mean([values[j][1][metric] for j in selected],0)))
def ensure():
 done=OUT/'SUPPLEMENTAL_INTERVALS_COMPLETE.json'
 if done.exists():return read(done)
 freeze=read(OUT/'SUPPLEMENTAL_STATISTICS_CODE_FROZEN.json');assert all(sha(CODE/n)==h for n,h in freeze['code'].items());rows={k:[] for k in ('L1','L2','L5','L7','L8')};missing=[]
 for L,releases,names in (('L1',('r5.1','r6.1','r6.2'),MODELS),('L2',RELEASES,('TA2','XGBoost_40'))):
  for release in releases:
   for n in names:
    for side in ('new','reference'):
     keys=[f'zero_{release}_{n}_{s}' if side=='reference' else f'restandard_{release}_{n}_{s}' if L=='L1' else f'new_{release}_{n}_{s}_reduced' for s in SEEDS]
     if not all((PRIVATE/f'metrics/{k}.json').exists() for k in keys):missing.append(dict(test=L,release=release,model=n,side=side,reason='missing bounded-child metric cache'));continue
     append_group(rows[L],dict(release=release,model=n,side=side),[cached(k) for k in keys],('PR_AUC','AP_over_prevalence','top1_insider_recall'))
 for f in read(OUT/'L5_THRESHOLDS_FROZEN.json')['thresholds']:
  p,b=cached(f"ensemble_{f['model']}_{f['group']}")
  for metric in ('PR_AUC','insiders_detected','noninsiders_flagged'):rows['L5'].append(cirow(dict(model=f['model'],group=f['group']),metric,p[metric],b[metric]))
 m=holdmeta();mal=m['y']==1;u=m['cluster'][mal];w=counts(500);dropcache=PRIVATE/'supplemental';dropcache.mkdir(exist_ok=True)
 for attack in ('uniform','source_targeted','TRACE_PGD','XGB_greedy'):
  for eps in (.1,.25,.5):
   for n in ('TA2','XGBoost_40'):
    values=[]
    for s in SEEDS:
     key=f'L7_{attack}_{eps:.2f}_{s}_{n}'
     if not (PRIVATE/f'metrics/{key}.json').exists():break
     p,b=cached(key);clean,cb=cached(f'zero_r5.2_HOLDOUT_{n}_{s}');p['AP_retention']=p['PR_AUC']/clean['PR_AUC'];b['AP_retention']=b['PR_AUC']/cb['PR_AUC'];d=original(n,s)[mal]-np.load(PRIVATE/f'scores/{key}.npy')[mal];p['median_malicious_score_drop']=float(np.median(d));file=dropcache/f'{key}_median_drop_boot.npy'
     if file.exists():a=np.load(file)
     else:
      a=np.array([np.median(np.repeat(d,wr[u].astype(int))) if wr[u].sum() else np.nan for wr in w]);np.save(file,a)
     b['median_malicious_score_drop']=a;values.append((p,b))
    if len(values)==3:append_group(rows['L7'],dict(attack=attack,epsilon=eps,model=n),values,('PR_AUC','AP_retention','insiders_detected','median_malicious_score_drop'))
    else:missing.append(dict(test='L7',attack=attack,epsilon=eps,model=n,reason='missing bounded-child metric cache'))
 for condition in CONFIGS[1:]:
  for n in ('TA2','XGBoost_40'):
   keys=[f'new_r5.2_HOLDOUT_{n}_{s}_{condition}' for s in SEEDS]
   if all((PRIVATE/f'metrics/{k}.json').exists() for k in keys):append_group(rows['L8'],dict(condition=condition,model=n),[cached(k) for k in keys],('PR_AUC','insiders_detected'))
   else:missing.append(dict(test='L8',condition=condition,model=n,reason='missing bounded-child metric cache'))
 # Other three L3 endpoint means; the48 primary AUC contrasts remain untouched.
 d=read(OUT/'L3_RESULTS.json');additional=[]
 for n in ('TA2','XGBoost_40','L1'):
  for lead in (1,3,5,7):
   seedvalues={k:[] for k in ('median_rank_percentile','top1_share','top5_share')};seedpoints={k:[] for k in seedvalues}
   for s in SEEDS:
    detail=[z for z in d['detail'] if z['model']==n and z['lead']==lead and z['seed']==s and z['eligible']];ids=np.array([int(np.flatnonzero(operational()['user']==z['user'])[0]) for z in detail]);pct=np.array([z['rank_percentile'] for z in detail]);iw=w[:,ids];den=iw.sum(1);med=np.array([np.median(np.repeat(pct,r.astype(int))) if r.sum() else np.nan for r in iw]);rep=dict(median_rank_percentile=med,top1_share=(iw@(pct>=99))/den,top5_share=(iw@(pct>=95))/den);point=dict(median_rank_percentile=np.median(pct),top1_share=np.mean(pct>=99),top5_share=np.mean(pct>=95))
    for metric in point:seedpoints[metric].append(point[metric]);seedvalues[metric].append(rep[metric])
   for metric in seedpoints:additional.append(cirow(dict(model=n,lead=lead,seed='mean'),metric,np.mean(seedpoints[metric]),np.mean(seedvalues[metric],0)))
 for L,v in rows.items():csv(f'{L}_POINT_METRIC_INTERVALS.csv',v);dump(OUT/f'{L}_POINT_METRIC_INTERVALS.json',dict(utc=utc(),points=v,additional_hypotheses=False))
 csv('L3_ADDITIONAL_SEED_MEAN_METRICS.csv',additional);dump(OUT/'L3_ADDITIONAL_SEED_MEAN_METRICS.json',dict(utc=utc(),points=additional,primary_AUC_contrasts_unchanged=True));result=dict(utc=utc(),counts={k:len(v) for k,v in rows.items()},L3_additional_mean_metric_rows=len(additional),missing=missing,no_new_model_inference=True,no_new_hypotheses=True,code_freeze_sha256=sha(OUT/'SUPPLEMENTAL_STATISTICS_CODE_FROZEN.json'));dump(done,result);print('SUPPLEMENTAL_PREDECLARED_INTERVALS_COMPLETE',result,flush=True);return result
if __name__=='__main__':ensure()
