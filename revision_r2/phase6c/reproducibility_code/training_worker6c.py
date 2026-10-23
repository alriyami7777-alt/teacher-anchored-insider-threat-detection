from common6c import *
import subprocess
def main():
 assert (OUT/'DEVELOPMENT_VERIFICATION.json').exists();rows=[]
 for model in ('AL_PRECURSOR','T-OPT','TA2','XGBoost-40-aug'):
  for seed in SEEDS:
   path=PRIVATE/f'training/results/{model}_{seed}.json'
   if path.exists():r=read(path);assert sha(r['checkpoint'])==r['sha256']
   else:
    deps=[('AL_PRECURSOR',seed)] if model=='T-OPT' else [('T-OPT',s) for s in SEEDS] if model=='TA2' else [];missing=[m for m,s in deps if not (PRIVATE/f'training/results/{m}_{s}.json').exists()]
    if missing:r=dict(model=model,seed=seed,status='SKIPPED',reason='Missing own augmented-teacher prerequisite')
    else:
     status('TRAINING',model=model,seed=seed);log=PRIVATE/'logs'/f'train_{model}_{seed}.log';started=time.perf_counter()
     with log.open('w',encoding='utf-8') as h:
      p=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/'train6c.py'),'--model',model,'--seed',str(seed)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
      try:rc=p.wait(timeout=7200)
      except subprocess.TimeoutExpired:p.kill();p.wait();rc='TIMEOUT'
     r=read(path) if rc==0 and path.exists() else dict(model=model,seed=seed,status='TIMEOUT' if rc=='TIMEOUT' else 'FAILED',wall_seconds=time.perf_counter()-started,reason=f'Exit {rc}; private log retained')
   rows.append(r);dump(OUT/'TRAINING_RESULTS_PHASE6C.json',rows);csv('TRAINING_LOG_PHASE6C.csv',[{k:v for k,v in z.items() if k not in ('config','history','augmentation')} for z in rows])
 dump(OUT/'TRAINING_COMPLETE.json',dict(utc=utc(),runs=rows,successful=sum(r['status']=='ok' for r in rows)));status('TRAINING_COMPLETE',runs=len(rows))
if __name__=='__main__':main()
