from common9 import *
from stats9 import cachedmetrics
import argparse
def one(release):
 gate();co=Cohort(release,True);rows=[]
 for n in MODELS:
  for s in (ALL if release=='r5.2_HOLDOUT' and n!='L1' else SEEDS):
   key=f'zero_{release}_{n}_{s}';pt,b=cachedmetrics(key,co,original(n,s,release),oldspec(n,s)['threshold']);rows.append(dict(model=n,seed=s,PR_AUC=pt['PR_AUC']));print('BASELINE_METRICS_CACHED',release,n,s,flush=True)
 dump(OUT/f'BASELINE_CACHE_{release}_COMPLETE.json',dict(utc=utc(),rows=rows,no_model_inference=True))
def main():
 rows=[]
 for release in ('r5.1','r6.2'):
  p=OUT/f'BASELINE_CACHE_{release}_COMPLETE.json'
  if not p.exists():rows.append(child('precache9.py',['--release',release],f'baseline_cache_{release}'))
 dump(OUT/'BASELINE_CACHE_WORKER_COMPLETE.json',dict(utc=utc(),outcomes=rows,no_model_inference=True));print('BASELINE_CACHE_WORKER_FINISHED',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--release');a=p.parse_args();one(a.release) if a.release else main()
