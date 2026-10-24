from stats10 import *
def main():
 gate();defs={1:[],2:[],3:[],4:[]}
 for n in MODELS:defs[1].append((f'P1_{n}_{{s}}_r62',f'zero_{n}_{{s}}_r62',('insiders_detected','noninsiders_flagged')))
 defs[2]=[('within_TA2_{s}_r62','within_XGBoost_40_{s}_r62',METRICS),('within_TA2_{s}_r62','within_F00_{s}_r62',METRICS),('within_TA2_{s}_r62','zero_TA2_{s}_r62',METRICS)]
 for frac in (10,25):
  for prefix,n in [('adapt','TA2'),('xadapt','XGBoost_40')]:defs[3].append((f'{prefix}{frac}_{n}_{{s}}_r62',f'zero_{n}_{{s}}_r62',METRICS))
  defs[3].append((f'adapt{frac}_TA2_{{s}}_r62',f'xadapt{frac}_XGBoost_40_{{s}}_r62',METRICS))
 for n in MODELS:
  defs[4].extend([(f'pooled_{n}_{{s}}_r62',f'within_{n}_{{s}}_r62',METRICS),(f'pooled_{n}_{{s}}_r62',f'zero_{n}_{{s}}_r62',METRICS),(f'pooled_{n}_{{s}}_r52',f'zero_{n}_{{s}}_r52',METRICS)])
 rows=[]
 for priority,triples in defs.items():
  family=[]
  for left,right,endpoints in triples:
   for s in (*SEEDS,'mean'):
    seeds=SEEDS if s=='mean' else (s,);available=all((P/f'metrics/{side.format(s=k)}.json').exists() for side in (left,right) for k in seeds)
    for metric in endpoints:
     r=dict(priority=priority,left=left,right=right,seed=s,metric=metric,status='ok' if available else 'NOT RUN (time)',p_unadjusted=1.)
     if available:
      est=[];reps=[]
      for k in seeds:
       lp=read(P/f'metrics/{left.format(s=k)}.json');rp=read(P/f'metrics/{right.format(s=k)}.json');lb=np.load(P/f'metrics/{left.format(s=k)}.npz')[metric];rb=np.load(P/f'metrics/{right.format(s=k)}.npz')[metric];est.append(lp[metric]-rp[metric]);reps.append(lb-rb)
      r.update(interval(np.mean(reps,axis=0),float(np.mean(est))))
     family.append(r)
  expected={1:24,2:60,3:120,4:180}[priority];assert len(family)==expected;ps=np.array([r['p_unadjusted'] for r in family]);order=np.argsort(ps,kind='stable');adj=np.maximum.accumulate(np.minimum(1,ps[order]*(expected-np.arange(expected))));padj=np.empty(expected);padj[order]=adj
  for r,pv in zip(family,padj):r.update(p_Holm=float(pv),Holm_family_size=expected,Holm_reject=bool(pv<.05 and r['status']=='ok'))
  dump(OUT/f'P{priority}_CONTRASTS.json',dict(utc=utc(),contrasts=family));pd.DataFrame(clean(family)).to_csv(OUT/f'P{priority}_CONTRASTS.csv',index=False);rows+=family
 dump(OUT/'CONTRASTS_COMPLETE.json',dict(utc=utc(),planned=384,computed=sum(r['status']=='ok' for r in rows),all_families_preserved=True))
if __name__=='__main__':main()
