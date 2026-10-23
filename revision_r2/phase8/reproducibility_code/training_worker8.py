from common8 import *
import subprocess
def main():
 gate();rows=[]
 for name in ('AL_PRECURSOR','T-OPT','F00','TA2','XGBoost_40'):
  for s in NEW:
   path=resultpath(name,s)
   if path.exists():r=read(path);assert sha(r['checkpoint'])==r['sha256']
   else:
    deps=[('AL_PRECURSOR',s)] if name=='T-OPT' else [('T-OPT',s)] if name in ('F00','TA2') else []
    if any(not resultpath(n,k).exists() for n,k in deps):r=dict(model=name,seed=s,status='SKIPPED',reason='Missing matched prerequisite')
    else:
     status('Q1_TRAINING',model=name,seed=s);start=time.perf_counter();log=PRIVATE/f'logs/train_{name}_{s}.log'
     with log.open('w',encoding='utf-8') as h:
      p=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/'train8.py'),'--model',name,'--seed',str(s)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
      try:rc=p.wait(timeout=7200)
      except subprocess.TimeoutExpired:p.kill();p.wait();rc='TIMEOUT'
     r=read(path) if rc==0 and path.exists() else dict(model=name,seed=s,status='TIMEOUT' if rc=='TIMEOUT' else 'FAILED',reason=f'Exit {rc}; log retained',wall_seconds=time.perf_counter()-start)
   rows.append(r);dump(OUT/'TRAINING_RESULTS_PHASE8.json',rows);csv('Q1_TRAINING_LOG.csv',[{k:v for k,v in z.items() if k not in ('config','history')} for z in rows])
 dump(OUT/'Q1_TRAINING_COMPLETE.json',dict(utc=utc(),runs=25,successful=sum(r['status']=='ok' for r in rows),outcomes=rows));status('Q1_TRAINING_COMPLETE',successful=sum(r['status']=='ok' for r in rows))
if __name__=='__main__':main()
