from common11 import *
from stats11 import interval
METRICS=('PR_AUC','user_ROC_official','user_ROC_affected')
def main():
 gate();plans=[(f'{c}_TA2_{{s}}',f'{c}_XGBoost_40_{{s}}') for c in ('C1','C2','C3')]+[(f'C1_{n}_{{s}}',f'C3_{n}_{{s}}') for n in MODELS];rows=[]
 for left,right in plans:
  for metric in METRICS:
   for seed in (*SEEDS,'mean'):
    seeds=SEEDS if seed=='mean' else (seed,);lp=[P/f'metrics/{left.format(s=s)}.json' for s in seeds];rp=[P/f'metrics/{right.format(s=s)}.json' for s in seeds];row=dict(left=left,right=right,seed=seed,metric=metric,status='NOT RUN',p_unadjusted=1.)
    if all(p.exists() for p in lp+rp):
     lpoint=float(np.mean([read(p)[metric] for p in lp]));rpoint=float(np.mean([read(p)[metric] for p in rp]));lrep=np.mean([np.load(p.with_suffix('.npz'))[metric] for p in lp],axis=0);rrep=np.mean([np.load(p.with_suffix('.npz'))[metric] for p in rp],axis=0);row.update(status='ok',**interval(lrep-rrep,lpoint-rpoint))
    rows.append(row)
 assert len(rows)==60;ps=np.array([x['p_unadjusted'] for x in rows]);order=np.argsort(ps,kind='stable');adjusted=np.maximum.accumulate(np.minimum(1,ps[order]*(len(rows)-np.arange(len(rows)))))
 for j,i in enumerate(order):rows[i].update(p_Holm=float(adjusted[j]),Holm_reject=bool(adjusted[j]<.05))
 dump(OUT/'PHASE11_CONTRASTS.json',dict(utc=utc(),fixed_family_size=60,contrasts=rows));pd.DataFrame(rows).to_csv(OUT/'PHASE11_CONTRASTS.csv',index=False);print('CONTRASTS_COMPLETE',sum(x['status']=='ok' for x in rows),flush=True)
if __name__=='__main__':main()
