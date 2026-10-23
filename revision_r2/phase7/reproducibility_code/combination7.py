from common7 import *
sys.path.insert(0,str(CODE.parent/'phase6b_staging'))
from bootstrap6b import bootstrap,selfcheck
def main():
 selfcheck();m,o=metadata();y=m['y'];u=m['cluster'];c=np.load(P4P/'BOOTSTRAP_USER_MULTIPLICITIES.npy');f=read(OUT/'DEVELOPMENT_THRESHOLDS_FROZEN.json');results=[];contrasts=[];boots={};points={};(PRIVATE/'combination').mkdir(exist_ok=True)
 for s in SEEDS:
  p=combination(score('TRACE',s),score('XGBoost-40',s));t=next(r['threshold'] for r in f['P5_combination_thresholds'] if r['seed']==s);np.save(PRIVATE/f'combination/rank_average_{s}.npy',p)
  for n,pn,tn in [('Rank-average',p,t),('TRACE',score('TRACE',s),spec('TRACE',s)['threshold']),('XGBoost-40',score('XGBoost-40',s),spec('XGBoost-40',s)['threshold'])]:
   row=dict(model=n,seed=s,**metrics(y,pn,tn),**ops(m,o,pn,tn));results.append(row);points[n,s]=row
   if n=='Rank-average':bb=bootstrap(y,pn,u,c,tn)
   else:
    ap=np.load(P4P/f"bootstrap/pooled_completed_{spec(n,s)['model']}_{s}.npy");flag=pn>=tn;tp=c@np.bincount(u,weights=(y==1)&flag,minlength=500);fp=c@np.bincount(u,weights=(y==0)&flag,minlength=500);fn=c@np.bincount(u,weights=(y==1)&~flag,minlength=500);den=2*tp+fp+fn;bb=dict(PR_AUC=ap,F1=np.divide(2*tp,den,out=np.zeros_like(tp),where=den>0))
   bb['insiders_detected']=c@detected(m,pn,tn).astype(float);boots[n,s]=bb;np.savez_compressed(PRIVATE/f'combination/bootstrap_{n}_{s}.npz',**bb)
  status('RANK_AVERAGE_ANALYSED',seed=s)
 for n in ('Rank-average','TRACE','XGBoost-40'):
  rows=[points[n,s] for s in SEEDS];results.append(dict(model=n,seed='mean_three',**{k:float(np.mean([r[k] for r in rows])) for k in ('PR_AUC','F1','precision','recall','insiders_detected','noninsiders_flagged','alert_windows')},insiders_total=25,noninsiders_total=475,threshold=None))
 for other in ('TRACE','XGBoost-40'):
  for metric in ('PR_AUC','F1','insiders_detected'):
   d=[];e=[]
   for s in SEEDS:
    bb=boots['Rank-average',s][metric]-boots[other,s][metric];ee=points['Rank-average',s][metric]-points[other,s][metric];d.append(bb);e.append(ee);contrasts.append(dict(contrast=f'Rank-average minus {other}',metric=metric,seed=s,**summary(bb,ee)))
   contrasts.append(dict(contrast=f'Rank-average minus {other}',metric=metric,seed='mean_three',**summary(np.mean(d,0),np.mean(e))))
 assert len(contrasts)==24
 sensitivity=[]
 for n in ('TRACE','XGBoost-40','L1'):
  for s in SEEDS:
   p=score(n,s);thresholds=[dict(rule='original_max_F1',threshold=spec(n,s)['threshold'],target_attained=None)]+[r for r in f['P6_thresholds'] if r['model']==n and r['seed']==s]
   for r in thresholds:sensitivity.append(dict(model=n,seed=s,rule=r['rule'],development_target_attained=r['target_attained'],**metrics(y,p,r['threshold']),**ops(m,o,p,r['threshold'])))
 csv('P5_RANK_AVERAGE_RESULTS.csv',results);csv('P5_RANK_AVERAGE_CONTRASTS.csv',contrasts);csv('P6_THRESHOLD_SENSITIVITY.csv',sensitivity)
 dump(OUT/'COMBINATION_SENSITIVITY_RESULTS.json',dict(utc=utc(),P5_metrics=results,P5_contrasts=contrasts,P6_metrics=sensitivity,combination_count=1,rank_method='average / within-split N',threshold_manifest_sha256=sha(OUT/'DEVELOPMENT_THRESHOLDS_FROZEN.json'),new_holdout_inference=False,bootstrap_B=2000));status('COMBINATION_SENSITIVITY_COMPLETE',P5_contrasts=24,P6_rows=len(sensitivity))
if __name__=='__main__':main()
