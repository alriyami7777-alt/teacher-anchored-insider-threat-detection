from common8 import *
sys.path.insert(0,str(CODE.parent/'phase6b_staging'));from bootstrap6b import bootstrap,selfcheck
def main():
 selfcheck();m=metadata();c=np.load(P4P/'BOOTSTRAP_USER_MULTIPLICITIES.npy');point={};boots={};rows=[];missing=[]
 views={'pooled_completed':(np.ones(len(m['y']),bool),m['y']),'train_completed':(m['partition']=='train',m['y']),'validation_completed':(m['partition']=='validation',m['y']),'pooled_offset0':(m['offset0'],m['y']),'pooled_endpoint':(np.ones(len(m['y']),bool),m['endpoint'])};(PRIVATE/'bootstrap').mkdir(exist_ok=True)
 for n in ('TA2','F00','XGBoost_40'):
  for s in ALL:
   try:sp=spec(n,s);p=probability(n,s)
   except (FileNotFoundError,StopIteration):missing.append(dict(model=n,seed=s,reason='No completed model/score'));continue
   for view,(mask,labels) in views.items():
    rr=dict(model=n,seed=s,view=view,**pointmetrics(labels[mask],p[mask],sp['threshold']));rr.update(insiders_detected=int(len(np.unique(m['user'][mask&(labels==1)&(p>=sp['threshold'])]))),insiders_total=25);rows.append(rr)
    if view=='pooled_completed':point[n,s]=rr['PR_AUC']
   cache=PRIVATE/f'bootstrap/AP_{n}_{s}.npy'
   if s in OLD:bb=np.load(P4P/f'bootstrap/pooled_completed_{n}_{s}.npy')
   elif cache.exists():bb=np.load(cache)
   else:bb=bootstrap(m['y'],p,m['cluster'],c);np.save(cache,bb)
   boots[n,s]=bb
 means=[]
 for n in ('TA2','F00','XGBoost_40'):
  for group,ss in [('original_three',OLD),('new_five',NEW),('all_eight',ALL)]:
   rr=[r for r in rows if r['model']==n and r['view']=='pooled_completed' and r['seed'] in ss];complete=len(rr)==len(ss);means.append(dict(model=n,seed_group=group,planned_seeds=len(ss),available_seeds=len(rr),status='ok' if complete else 'unavailable_incomplete_requested_group',**{k:float(np.mean([r[k] for r in rr])) if complete else None for k in ('PR_AUC','F1','precision','recall','insiders_detected')}))
 contrasts=[]
 for other in ('F00','XGBoost_40'):
  for group,ss in [(s,(s,)) for s in ALL]+[('all_eight',ALL),('new_five',NEW)]:
   if not all(('TA2',s) in boots and (other,s) in boots for s in ss):contrasts.append(dict(contrast=f'TRACE minus {other}',seed=group,status='unavailable_missing_planned_seed',planned_seeds=list(ss)));continue
   values=np.mean([boots['TA2',s]-boots[other,s] for s in ss],0);est=np.mean([point['TA2',s]-point[other,s] for s in ss]);contrasts.append(dict(contrast=f'TRACE minus {other}',seed=group,status='ok',metric='PR_AUC',**ci(values,est)))
 wins=sum(point['TA2',s]>point['F00',s] for s in ALL if ('TA2',s) in point and ('F00',s) in point);den=sum(('TA2',s) in point and ('F00',s) in point for s in ALL)
 csv('Q1_ALL_MODEL_VIEW_METRICS.csv',rows);csv('Q1_SEED_GROUP_MEANS.csv',means);csv('Q1_PAIRED_AP_CONTRASTS.csv',contrasts);dump(OUT/'Q1_RESULTS.json',dict(utc=utc(),per_seed_all_views=rows,seed_group_means=means,contrasts=contrasts,strict_TRACE_minus_F00_positive_seeds=wins,available_paired_seeds=den,planned_paired_seeds=8,missing=missing,bootstrap_B=2000));status('Q1_ANALYSIS_COMPLETE',positive_TRACE_F00_seeds=wins,available=den)
def pointmetrics(y,p,t):return point(y,p,t)
if __name__=='__main__':main()
