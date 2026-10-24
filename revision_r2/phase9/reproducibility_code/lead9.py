from common9 import *
from stats9 import *
def main():
 gate();m=holdmeta();o=operational();u=m['cluster'];dates=m['end_date'].astype('datetime64[D]');cal=o['calendar'].astype('datetime64[D]');ins=np.flatnonzero(o['insider']);w=counts(500);points=[];contrasts=[];detail=[]
 for n in ('TA2','XGBoost_40','L1'):
  for lead in (1,3,5,7):
   allrep=[];allpoint=[]
   for s in SEEDS:
    p=original(n,s);records=[]
    for ui in ins:
     first=cal[np.flatnonzero(o['daily_y'][ui])[0]];d=first-np.timedelta64(lead,'D');row=np.flatnonzero((u==ui)&(dates==d));ctrl=np.flatnonzero((dates==d)&~o['insider'][u]);reason='missing completed window' if len(row)!=1 else 'no same-date noninsider controls' if not len(ctrl) else None
     if reason:detail.append(dict(model=n,seed=s,lead=lead,user=o['user'][ui],eligible=False,reason=reason));continue
     ix=row[0];assert m['y'][ix]==0;cp=p[ctrl];rate=(cp<p[ix]).astype(float)+.5*(cp==p[ix]);percentile=100*rate.mean();records.append((ui,percentile,u[ctrl],rate));detail.append(dict(model=n,seed=s,lead=lead,user=o['user'][ui],eligible=True,end_date=str(d),first_malicious_day=str(first),control_windows=len(ctrl),rank_percentile=percentile,AUC_pair_rate=float(rate.mean())))
    if not records:raise RuntimeError('No eligible lead-time windows')
    ids=np.array([r[0] for r in records]);pct=np.array([r[1] for r in records]);values=np.array([r[3].mean() for r in records]);iw=w[:,ids];den=iw.sum(1);wins=[]
    for ui,pct0,cu,rate in records:
     cw=w[:,cu];cd=cw.sum(1);wins.append(np.divide(cw@rate,cd,out=np.full(len(w),np.nan),where=cd>0))
    auc=np.sum(iw*np.array(wins).T,1)/den;median=[]
    for wr in iw:
     expanded=np.repeat(pct,wr.astype(int));median.append(np.median(expanded) if len(expanded) else np.nan)
    rep=dict(matched_AUC=auc,median_rank_percentile=np.array(median),top1_share=(iw@(pct>=99))/den,top5_share=(iw@(pct>=95))/den);point=dict(matched_AUC=float(values.mean()),median_rank_percentile=float(np.median(pct)),top1_share=float((pct>=99).mean()),top5_share=float((pct>=95).mean()));allrep.append(rep);allpoint.append(point)
    for k,v in point.items():points.append(dict(model=n,seed=s,lead=lead,metric=k,eligible_insiders=len(records),total_insiders=25,**interval(rep[k],v,null=.5 if k=='matched_AUC' else 0,one_sided=k=='matched_AUC')))
   for i in range(4):
    ix=range(3) if i==3 else [i];a=np.mean([allrep[j]['matched_AUC'] for j in ix],0);v=np.mean([allpoint[j]['matched_AUC'] for j in ix]);row=dict(model=n,lead=lead,seed='mean' if i==3 else SEEDS[i],metric='matched_AUC',**interval(a,v,null=.5,one_sided=True));row['forecasting_signal_CI_rule']=row['ci95_low']>.5;contrasts.append(row)
 holm(contrasts,'L3',48);csv('L3_LEAD_TIME_METRICS.csv',points);csv('L3_CONTRASTS.csv',contrasts);csv('L3_PER_INSIDER_RANKS.csv',detail);dump(OUT/'L3_RESULTS.json',dict(utc=utc(),points=points,contrasts=contrasts,detail=detail,Holm_family_size=48,scores_reused=True))
if __name__=='__main__':main()
