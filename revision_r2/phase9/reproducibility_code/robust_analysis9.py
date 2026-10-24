from common9 import *
from stats9 import *
import argparse
def main(L,condition):
 co=Cohort('r5.2_HOLDOUT',True);groups=[];points=[];contrasts=[];eps=None
 if L=='L7':attack,epsstr=condition.split(':');eps=float(epsstr)
 drops={}
 for n in ('TA2','XGBoost_40'):
  arr=[]
  for s in SEEDS:
   cleanp,cleanb=cachedmetrics(f'zero_r5.2_HOLDOUT_{n}_{s}',co,original(n,s),oldspec(n,s)['threshold']);key=f'L7_{attack}_{eps:.2f}_{s}_{n}' if L=='L7' else f'new_r5.2_HOLDOUT_{n}_{s}_{condition}';p=np.load(PRIVATE/f'scores/{key}.npy');t=oldspec(n,s)['threshold'] if L=='L7' else spec(condition,n,s)['threshold'];pt,bt=cachedmetrics(key,co,p,t);pt.update(AP_retention=pt['PR_AUC']/cleanp['PR_AUC'],median_malicious_score_drop=float(np.median(original(n,s)[co.y==1]-p[co.y==1])));bt['AP_retention']=bt['PR_AUC']/cleanb['PR_AUC'];points.append(dict(model=n,seed=s,condition=condition,**pt));arr.append((pt,bt,cleanp,cleanb))
   if L=='L8' and condition=='backdoor01':
    tp=np.load(PRIVATE/f'scores/trigger_r5.2_HOLDOUT_{n}_{s}_backdoor01.npy');op=operational()
    for label,mask in (('all_insider_windows',op['insider'][co.u]),('malicious_containing_insider_windows',co.y==1)):
     u=co.u[mask];success=(tp[mask]<t);w=counts(co.N);den=w[:,u].sum(1);asrb=(w[:,u]@success)/den;points.append(dict(model=n,seed=s,condition='backdoor01_triggered',ASR_population=label,attack_success_rate=float(success.mean()),successes=int(success.sum()),triggered_windows=int(mask.sum()),clean_poisoned_model_below_threshold_rate=float((p[mask]<t).mean()),ASR_CI=interval(asrb,success.mean())))
  drops[n]=arr
 if L=='L7':
  for i in range(4):
   ss=range(3) if i==3 else [i]
   for metric in ('insiders_detected','AP_retention'):
    a=np.mean([drops['TA2'][j][1][metric]-drops['XGBoost_40'][j][1][metric] for j in ss],0);v=np.mean([drops['TA2'][j][0][metric]-drops['XGBoost_40'][j][0][metric] for j in ss]);contrasts.append(dict(attack=attack,epsilon=eps,seed='mean' if i==3 else SEEDS[i],metric=metric,contrast='TRACE minus XGBoost on identical condition',**interval(a,v)))
 else:
  for i in range(4):
   ss=range(3) if i==3 else [i]
   for metric in ('PR_AUC','insiders_detected'):
    bs={};vs={}
    for n in drops:
     bs[n]=np.mean([drops[n][j][1][metric]-drops[n][j][3][metric] for j in ss],0);vs[n]=np.mean([drops[n][j][0][metric]-drops[n][j][2][metric] for j in ss]);contrasts.append(dict(condition=condition,model=n,seed='mean' if i==3 else SEEDS[i],metric=metric,contrast='poisoned minus unpoisoned',**interval(bs[n],vs[n])))
    contrasts.append(dict(condition=condition,model='TRACE minus XGBoost',seed='mean' if i==3 else SEEDS[i],metric=metric,contrast='TRACE minus XGBoost difference of poisoning changes',**interval(bs['TA2']-bs['XGBoost_40'],vs['TA2']-vs['XGBoost_40'])))
 dest=condition.replace(':','_');dump(OUT/f'{L}_{dest}_RESULTS.json',dict(utc=utc(),points=points,contrasts=contrasts));print('ROBUST_ANALYSED',L,condition,flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--test');p.add_argument('--condition');a=p.parse_args();main(a.test,a.condition)
