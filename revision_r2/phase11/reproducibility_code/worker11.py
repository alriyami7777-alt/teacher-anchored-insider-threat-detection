from common11 import *
def main():
 rows=read(OUT/'EXECUTION_LOG.json') if (OUT/'EXECUTION_LOG.json').exists() else []
 def run(script,args,key):
  if time.time()>=DEADLINE:return False
  if (P/f'outcomes/{key}.json').exists():return read(P/f'outcomes/{key}.json')['status']=='ok'
  result=child(script,args,key);rows.append(result);dump(OUT/'EXECUTION_LOG.json',rows);return result['status']=='ok'
 def train(c,k,n,s):
  if result_path(c,k,n,s).exists():return True
  if n=='T-OPT' and not result_path(c,k,'AL_PRECURSOR',s).exists():return False
  if n in ('TA2','F00') and not all(result_path(c,k,'T-OPT',seed).exists() for seed in (SEEDS if n=='TA2' else (s,))):return False
  return run('train11.py',[c,k,n,s],f'train_{c}_fold{k}_{n}_{s}')
 def score(c,k,n,s,release='r62'):
  key=f'{c}_fold{k}_{n}_{s}_{release}'
  return (P/f'complete/{key}.json').exists() or run('infer11.py',[c,k,n,s,release],'infer_'+key)
 try:
  assert read(OUT/'CROSS_RELEASE_USER_DISJOINTNESS.json')['all_release_ID_overlap']==0
  for seed in SEEDS:
   for c in ('C1','C2','C3','C4'):
    for k in range(1,5):
     if not (data_dir(c,k)/'manifest.json').exists():
      if not run('prepare11.py',[data_condition(c),k],f'prepare_{data_condition(c)}_fold{k}'):continue
     if c!='C4' and seed==42:
      for teacher_seed in SEEDS:
       for name in ('AL_PRECURSOR','T-OPT'):train(c,k,name,teacher_seed)
     for name in (('F00',) if c=='C4' else MODELS):
      if train(c,k,name,seed):
       score(c,k,name,seed)
       if k==1 and c in ('C1','C2','C4'):score(c,k,name,seed,'r52')
 except Exception as error:
  dump(OUT/'COORDINATOR_ERROR.json',dict(utc=utc(),type=type(error).__name__,message=str(error)));raise
 finally:dump(OUT/'COMPUTATION_FINISHED.json',dict(utc=utc(),execution_entries=len(rows),before_safety_stop=time.time()<DEADLINE));print('WORKER_FINISHED',utc(),flush=True)
if __name__=='__main__':main()
