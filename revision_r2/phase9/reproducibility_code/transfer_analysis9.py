from common9 import *
from stats9 import *
import argparse
def main(L,release):
 co=Cohort(release,True);groups=[];names=MODELS if L=='L1' else ('TA2','XGBoost_40');endpoints=('PR_AUC','AP_over_prevalence','top1_insider_recall')
 for n in names:
  left=[];right=[]
  for s in SEEDS:
   p=original(n,s,release);right.append(cachedmetrics(f'zero_{release}_{n}_{s}',co,p,oldspec(n,s)['threshold']));key=f'restandard_{release}_{n}_{s}' if L=='L1' else f'new_{release}_{n}_{s}_reduced';p=np.load(PRIVATE/f'scores/{key}.npy',mmap_mode='r');t=oldspec(n,s)['threshold'] if L=='L1' else spec('reduced',n,s)['threshold'];left.append(cachedmetrics(key,co,p,t))
  groups.append((dict(release=release,model=n),left,right))
 # Each release is a bounded analysis child; combine Holm only after all releases.
 pts=[];rows=[]
 for meta,left,right in groups:
  for side,vals in (('new',left),('reference',right)):
   for s,(p,b) in zip(SEEDS,vals):pts.append(meta|dict(side=side,seed=s,**p))
  for i in range(4):
   ss=range(3) if i==3 else [i]
   for k in endpoints:rows.append(meta|dict(seed='mean' if i==3 else SEEDS[i],metric=k,contrast='restandardised minus zero-shot' if L=='L1' else 'reduced minus full',**interval(np.mean([left[j][1][k]-right[j][1][k] for j in ss],0),np.mean([left[j][0][k]-right[j][0][k] for j in ss]))))
 dump(OUT/f'{L}_{release}_RESULTS.json',dict(utc=utc(),points=pts,contrasts=rows));print(L,release,'ANALYSED',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--test');p.add_argument('--release');a=p.parse_args();main(a.test,a.release)
