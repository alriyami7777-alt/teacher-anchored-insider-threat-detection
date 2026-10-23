from common8 import *
from routing8 import Routes
import argparse,subprocess
def one(name,seed):
 import torch
 gate();s=spec(name,seed);assert sha(s['checkpoint'])==s['sha256'];freeze=read(OUT/'MODELS_FROZEN_PHASE8.json');assert all(sha(CODE/n)==h for n,h in freeze['scoring_code'].items());dv=device();model=loadmodel(s,dv)
 dev=np.load(HP/'tensors/validation_X.npy',mmap_mode='r');test=np.array(dev[:16]);
 with torch.inference_mode():pre=model.predict_proba(rt.aggregate_common13_windows(test)[0])[:,1] if name=='XGBoost_40' else rt.probs(rt.student_forward(model,torch.as_tensor(test,device=dv))['logit'].cpu().numpy())
 assert np.isfinite(pre).all();co=np.load(P4P/'HOLDOUT_COHORT.npz');x=co['X'];n=len(x);lock=PRIVATE/f'score_receipts/{name}_{seed}.json';assert not lock.exists();dump(lock,dict(utc=utc(),state='CONSUMED',model=name,seed=seed,checkpoint_sha256=s['sha256'],threshold=s['threshold'],freeze_sha256=sha(OUT/'MODELS_FROZEN_PHASE8.json')))
 p=np.lib.format.open_memmap(PRIVATE/f'scores/{name}_{seed}.npy',mode='w+',dtype=np.float64,shape=(n,));routes=Routes(name,seed,n) if name in ('TA2','F00') else None
 with torch.inference_mode():
  for lo in range(0,n,512):
   hi=min(lo+512,n);a=x[lo:hi]
   if name=='XGBoost_40':p[lo:hi]=model.predict_proba(rt.aggregate_common13_windows(a)[0])[:,1].astype(float)
   else:
    out=rt.student_forward(model,torch.as_tensor(a,device=dv));p[lo:hi]=rt.probs(out['logit'].cpu().numpy());routes.add(lo,hi,out)
   time.sleep(.002)
 assert np.isfinite(p).all();p.flush()
 if routes:routes.finish(captured_during_single_new_Q1_scoring=True,checkpoint_sha256=s['sha256'])
 r=read(lock);r.update(state='COMPLETE',completed_utc=utc(),prediction_sha256=sha(PRIVATE/f'scores/{name}_{seed}.npy'),windows=n,development_preflight_finite=True);dump(lock,r);print('Q1_SCORED_ONCE',name,seed,flush=True)
def main():
 gate();train=read(OUT/'TRAINING_RESULTS_PHASE8.json');models=[r for r in train if r['model'] in ('TA2','F00','XGBoost_40') and r['status']=='ok'];freeze=OUT/'MODELS_FROZEN_PHASE8.json'
 if not freeze.exists():dump(freeze,dict(utc=utc(),models=models,all_training_runs=train,amendment8_sha256=read(OUT/'AMENDMENT8_RECEIPT.json')['sha256'],scoring_code={n:sha(CODE/n) for n in ('common8.py','score8.py','routing8.py')},original_prediction_hashes=read(P4/'SCORING_COMPLETE.json')['prediction_hashes'],consensus_seeds=OLD,preregistration_sha256=sha(H/'PREREGISTRATION_R2_HOLDOUT.md')))
 for p in ('scores','score_receipts','routes'):(PRIVATE/p).mkdir(exist_ok=True)
 outcomes=[]
 for s in models:
  name,seed=s['model'],s['seed'];receipt=PRIVATE/f'score_receipts/{name}_{seed}.json'
  if receipt.exists():r=read(receipt)|dict(status='ok' if read(receipt)['state']=='COMPLETE' else 'FAILED',reason='Previously consumed receipt; no repeat')
  else:
   status('Q1_SINGLE_SCORING',model=name,seed=seed)
   with (PRIVATE/f'logs/score_{name}_{seed}.log').open('w',encoding='utf-8') as h:
    p=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/'score8.py'),'--model',name,'--seed',str(seed)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    try:rc=p.wait(timeout=7200)
    except subprocess.TimeoutExpired:p.kill();p.wait();rc='TIMEOUT'
   r=read(receipt)|dict(status='ok') if rc==0 and receipt.exists() and read(receipt)['state']=='COMPLETE' else dict(model=name,seed=seed,status='TIMEOUT' if rc=='TIMEOUT' else 'FAILED',reason=f'Exit {rc}; no repeated scoring')
  outcomes.append(r);dump(OUT/'Q1_SCORING_OUTCOMES.json',outcomes)
 dump(OUT/'Q1_SCORING_COMPLETE.json',dict(utc=utc(),outcomes=outcomes,successful=sum(r['status']=='ok' for r in outcomes),planned=15));status('Q1_SCORING_COMPLETE',successful=sum(r['status']=='ok' for r in outcomes))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--model');p.add_argument('--seed',type=int);a=p.parse_args();one(a.model,a.seed) if a.model else main()
