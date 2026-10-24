from common10 import *
def main():
 for x in ('logs','outcomes','scores','complete','frozen','consumed'): (P/x).mkdir(exist_ok=True)
 rows=read(OUT/'EXECUTION_LOG.json') if (OUT/'EXECUTION_LOG.json').exists() else []
 def run(script,args,key):
  if time.time()>=DEADLINE:return False
  r=child(script,args,key);rows.append(r);dump(OUT/'EXECUTION_LOG.json',rows);return r['status']=='ok'
 def prepare(c):return (P/f'data/{c}/manifest.json').exists() or run('prepare10.py',[c],'prepare_'+c)
 def train(c,n,s):
  p=P/f'training/{c}/results/{n}_{s}.json'
  if p.exists():return True
  if n=='T-OPT' and not (P/f'training/{c}/results/AL_PRECURSOR_{s}.json').exists():return False
  if n in ('TA2','F00') and not c.startswith('adapt'):
   required=SEEDS if n=='TA2' else (s,)
   if not all((P/f'training/{c}/results/T-OPT_{k}.json').exists() for k in required):return False
  return run('train10.py',[c,n,s],f'train_{c}_{n}_{s}')
 def score(c,n,s,release='r62'):
  return (P/f'complete/{c}_{n}_{s}_{release}.json').exists() or run('infer10.py',[c,n,s,release],f'infer_{c}_{n}_{s}_{release}')
 def chain(c,s):
  if not prepare(c):return
  for k in SEEDS:
   for n in ('AL_PRECURSOR','T-OPT'):train(c,n,k)
  # All prerequisite teachers are necessary for the first seed42 TRACE.
  for n in ('TA2','F00','XGBoost_40'):
   if train(c,n,s):
    score(c,n,s)
    if c=='pooled':score(c,n,s,'r52')
 try:
  # P1 seed42 already completed first under standalone launch.
  chain('within',42)
  for frac in (10,25):
   c=f'adapt{frac}'
   if prepare(c) and train(c,'TA2',42):score(c,'TA2',42)
   c=f'xadapt{frac}'
   if prepare(c) and train(c,'XGBoost_40',42):score(c,'XGBoost_40',42)
  chain('pooled',42)
  conditions=[('within',n) for n in MODELS]+[(f'{prefix}{frac}',n) for frac in (10,25) for prefix,n in [('adapt','TA2'),('xadapt','XGBoost_40')]]
  required=[P/f'complete/{c}_{n}_42_r62.json' for c,n in conditions]+[P/f'complete/pooled_{n}_42_{r}.json' for n in MODELS for r in ('r62','r52')]
  if all(p.exists() for p in required):
   for s in (52,62):
    if not (OUT/f'P1_THRESHOLDS_{s}.json').exists():run('p1_10.py',[s],f'p1_{s}')
    for n in MODELS:
     if train('within',n,s):score('within',n,s)
    for frac in (10,25):
     for c,n in [(f'adapt{frac}','TA2'),(f'xadapt{frac}','XGBoost_40')]:
      if train(c,n,s):score(c,n,s)
    for n in MODELS:
     if train('pooled',n,s):score('pooled',n,s);score('pooled',n,s,'r52')
 except AssertionError as e:
  dump(OUT/'STOP_REASON.json',dict(utc=utc(),reason=str(e)))
 finally:
  dump(OUT/'COMPUTATION_FINISHED.json',dict(utc=utc(),execution_entries=len(rows),before_deadline=time.time()<DEADLINE));print('WORKER_FINISHED',utc(),flush=True)
if __name__=='__main__':main()
