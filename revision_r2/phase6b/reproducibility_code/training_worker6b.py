from common6b import *
import subprocess
def main():
 assert (OUT/'PREPARATION_COMPLETE.json').exists();rows=[];(PRIVATE/'logs').mkdir(parents=True,exist_ok=True)
 order=[(m,s) for m in ('AL_PRECURSOR','T-OPT','TA2','XGBoost-260','RF-260','LightGBM-260','MLP-40') for s in SEEDS]
 for name,s in order:
  op=name in ('AL_PRECURSOR','T-OPT','TA2');path=PRIVATE/'training/orderfree/results'/f'{name}_{s}.json' if op else resultpath(name,s)
  if path.exists():r=read(path);assert sha(r['checkpoint'])==r['sha256']
  else:
   deps=([('AL_PRECURSOR',s)] if name=='T-OPT' else [('T-OPT',a) for a in SEEDS] if name=='TA2' else [])
   missing=[a for a,b in deps if not (PRIVATE/f'training/orderfree/results/{a}_{b}.json').exists()]
   if missing:r=dict(model=name,seed=s,status='SKIPPED',reason='Missing own-teacher prerequisite')
   else:
    status('TRAINING',model=name,seed=s);log=PRIVATE/'logs'/f'{name}_{s}.log';t0=time.perf_counter()
    with log.open('w',encoding='utf-8') as f:
     proc=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/'train6b.py'),'--model',name,'--seed',str(s)],stdout=f,stderr=subprocess.STDOUT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1'),creationflags=subprocess.CREATE_NO_WINDOW)
     try:rc=proc.wait(timeout=7200)
     except subprocess.TimeoutExpired:proc.kill();proc.wait();rc='TIMEOUT'
    r=read(path) if rc==0 and path.exists() else dict(model=name,seed=s,status='TIMEOUT' if rc=='TIMEOUT' else 'FAILED',wall_seconds=time.perf_counter()-t0,reason=f'Exit {rc}; see private log')
  rows.append(dict(**r,orderfree=op));dump(OUT/'TRAINING_RESULTS_PHASE6B.json',rows);csv('TRAINING_LOG_PHASE6B.csv',[{k:v for k,v in r.items() if k not in ('history','config','params')} for r in rows])
 dump(OUT/'TRAINING_COMPLETE.json',dict(utc=utc(),runs=len(rows),ok=sum(r['status']=='ok' for r in rows),all_outcomes=rows,reused_H5=read(OUT/'H5_REUSED_TRAINING.json')));status('TRAINING_COMPLETE',runs=len(rows))
if __name__=='__main__':main()
