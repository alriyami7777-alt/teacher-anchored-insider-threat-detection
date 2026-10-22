from common6 import *
import subprocess,traceback,csv as csvlib
PYTHON=ROOT/'phase4/.venv/Scripts/python.exe'
CONFIGS=('r52_T10_F13','r52_T30_F13','r52_T20_F6','r52_T20_F29','r42_T20_F13')
def main():
 (PRIVATE/'logs').mkdir(parents=True,exist_ok=True)
 allruns=[]
 for config in CONFIGS:
  order=[(m,s) for m in ('AL_PRECURSOR','T-OPT','TA2') for s in SEEDS]
  if config in ('r52_T10_F13','r52_T30_F13','r42_T20_F13'):order += [('XGBoost_40',s) for s in SEEDS]
  if config=='r42_T20_F13':order += [('RF_40',s) for s in SEEDS]
  for model,seed in order:
   result=PRIVATE/'training'/config/'results'/f'{model}_{seed}.json'
   if result.exists():
    r=read(result);assert sha(r['checkpoint'])==r['sha256'];allruns.append(dict(phase6_config=config,**r));continue
   deps=[]
   if model=='T-OPT':deps=[('AL_PRECURSOR',seed)]
   if model=='TA2':deps=[('T-OPT',s) for s in SEEDS]
   missing=[f'{m}/{s}' for m,s in deps if not (PRIVATE/'training'/config/'results'/f'{m}_{s}.json').exists()]
   if missing:r=dict(model=model,seed=seed,status='SKIPPED',reason='Missing prerequisite: '+', '.join(missing))
   else:
    log=PRIVATE/'logs'/f'{config}_{model}_{seed}.log';started=time.perf_counter();status('TRAINING',config=config,model=model,seed=seed)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1',PYTHONUTF8='1')
    with log.open('w',encoding='utf-8') as f:
     proc=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/'train6.py'),'--config',config,'--model',model,'--seed',str(seed)],stdout=f,stderr=subprocess.STDOUT,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
     try:exitcode=proc.wait(timeout=7200)
     except subprocess.TimeoutExpired:proc.kill();proc.wait();exitcode='TIMEOUT'
    if exitcode==0 and result.exists():r=read(result)
    else:r=dict(model=model,seed=seed,status='TIMEOUT' if exitcode=='TIMEOUT' else 'FAILED',wall_seconds=time.perf_counter()-started,reason=f'Exit {exitcode}; retained private run log')
   allruns.append(dict(phase6_config=config,**r));dump(OUT/'TRAINING_RESULTS_PHASE6.json',allruns)
   csv('TRAINING_LOG_PHASE6.csv',[{k:v for k,v in r.items() if k not in ('history','config')}|{'config':r['phase6_config']} for r in allruns])
 dump(OUT/'TRAINING_RESULTS_PHASE6.json',allruns)
 dump(OUT/'TRAINING_COMPLETE.json',dict(utc=utc(),runs=len(allruns),ok=sum(r['status']=='ok' for r in allruns),models_frozen=True,r42_test_evaluated=False,checkpoint_hashes={r['checkpoint']:r['sha256'] for r in allruns if r['status']=='ok'}))
 status('TRAINING_COMPLETE',runs=len(allruns))
if __name__=='__main__':main()
