from common6c import *
import argparse,subprocess
def freeze():
 assert (OUT/'TRAINING_COMPLETE.json').exists();am=read(OUT/'AMENDMENT6_RECEIPT.json');assert sha(H/'PREREGISTRATION_R2_HOLDOUT.md')==am['preregistration_final_sha256'];runs=read(OUT/'TRAINING_RESULTS_PHASE6C.json');new=[]
 for r in runs:
  if r['status']=='ok':assert sha(r['checkpoint'])==r['sha256']
  if r['status']=='ok' and r['model'] in ('TA2','XGBoost-40-aug'):new.append(r|dict(model='TRACE-aug' if r['model']=='TA2' else r['model'],source_model=r['model']))
 original=[oldspec(m,s)|dict(model='TRACE' if m=='TA2' else 'XGBoost-40',source_model=m) for m in ('TA2','XGBoost_40') for s in SEEDS]
 for r in original:assert sha(r['checkpoint'])==r['sha256']
 checks=[];dv=device();x=np.array(rt.data()['validation']['X'][:16])
 for r in new:
  m=b.loadmodel(r,dv);p=b.predict(m,r,x,dv);assert np.isfinite(p).all();checks.append(dict(model=r['model'],seed=r['seed'],development_only=True,finite=True));del m
 import torch,shutil
 torch.cuda.empty_cache();snapshot=PRIVATE/'code_snapshot';snapshot.mkdir(exist_ok=True)
 for source in CODE.glob('*.py'):shutil.copyfile(source,snapshot/source.name)
 old_predictions={}
 for r in original:
  for source,level in conditions():
   p=P4P/f"scores/{r['source_model']}_{r['seed']}.npz" if level==0 else P5/f"private/robustness/{key(source,level)}_{r['source_model']}_{r['seed']}.npy";old_predictions[str(p)]=sha(p)
 f=dict(utc=utc(),new_models=[{k:v for k,v in r.items() if k!='history'} for r in new],original_models=original,original_prediction_hashes=old_predictions,all_training_runs=[{k:v for k,v in r.items() if k!='history'} for r in runs],development_preflight=checks,code_hashes={n:sha(CODE/n) for n in ('score6c.py','common6c.py')},preregistration_sha256=am['preregistration_final_sha256'],Phase5_perturbation_receipts_sha256=sha(P5/'B_PERTURBATION_RECEIPTS.json'),helper_hashes=read(OUT/'DEVELOPMENT_VERIFICATION.json')['Phase5_helper_hashes'],r52_test_sealed=True)
 dump(OUT/'MODELS_FROZEN_PHASE6C.json',f);return f
def job(name,seed):
 f=read(OUT/'MODELS_FROZEN_PHASE6C.json');assert all(sha(CODE/n)==h for n,h in f['code_hashes'].items());assert sha(H/'PREREGISTRATION_R2_HOLDOUT.md')==f['preregistration_sha256'];assert all(sha(REPO/'src'/n)==h for n,h in f['helper_hashes'].items());spec=next(r for r in f['new_models'] if r['model']==name and r['seed']==seed);assert sha(spec['checkpoint'])==spec['sha256'];dv=device();m=b.loadmodel(spec,dv);x=np.load(P4P/'HOLDOUT_COHORT.npz')['X'];assert x.shape==(213000,20,13)
 expected={r['condition']:r['perturbed_tensor_sha256'] for r in read(P5/'B_PERTURBATION_RECEIPTS.json')};scores=PRIVATE/'scores';receipts=PRIVATE/'score_receipts';scores.mkdir(exist_ok=True);receipts.mkdir(exist_ok=True)
 for source,level in conditions():
  c=key(source,level);lock=receipts/f'{name}_{seed}_{c}.json';dest=scores/f'{name}_{seed}_{c}.npy'
  if lock.exists():raise RuntimeError('Refuse repeated scoring of consumed model/condition')
  with lock.open('x',encoding='utf-8') as h:json.dump(dict(utc=utc(),state='CONSUMED',model=name,seed=seed,condition=c,checkpoint_sha256=spec['sha256'],no_reruns=True),h)
  xp=perturb(x,source,level);tensorhash=hashlib.sha256(xp.tobytes()).hexdigest()
  if level:assert tensorhash==expected[c],'Perturbations must exactly match Phase 5'
  p=b.predict(m,spec,xp,dv);assert len(p)==213000 and np.isfinite(p).all();np.save(dest,p);dump(lock,dict(utc=utc(),state='COMPLETE',model=name,seed=seed,condition=c,source=source,severity=level,checkpoint_sha256=spec['sha256'],prediction_sha256=sha(dest),perturbed_tensor_sha256=tensorhash,Phase5_tensor_hash_equal=bool(level),windows=len(p)));print('C2_CONDITION_COMPLETE',name,seed,c,flush=True)
 dump(PRIVATE/f'SCORING_{name}_{seed}_COMPLETE.json',dict(utc=utc(),model=name,seed=seed,conditions=27,clean_passes=1));print('C2_SEED_COMPLETE',name,seed,flush=True)
def main():
 f=read(OUT/'MODELS_FROZEN_PHASE6C.json') if (OUT/'MODELS_FROZEN_PHASE6C.json').exists() else freeze();outcomes=[]
 for r in f['new_models']:
  name,s=r['model'],r['seed'];done=PRIVATE/f'SCORING_{name}_{s}_COMPLETE.json';log=PRIVATE/'logs'/f'score_{name}_{s}.log'
  if done.exists():outcome=read(done)|dict(status='ok')
  else:
   status('C2_HOLDOUT_SCORING',model=name,seed=s)
   with log.open('w',encoding='utf-8') as h:
    p=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/'score6c.py'),'--model',name,'--seed',str(s)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    try:rc=p.wait(timeout=7200)
    except subprocess.TimeoutExpired:p.kill();p.wait();rc='TIMEOUT'
   outcome=read(done)|dict(status='ok') if rc==0 and done.exists() else dict(model=name,seed=s,status='TIMEOUT' if rc=='TIMEOUT' else 'FAILED',reason=f'Exit {rc}; consumed conditions not repeated')
  outcomes.append(outcome);dump(OUT/'C2_SCORING_OUTCOMES.json',outcomes)
 dump(OUT/'C2_SCORING_COMPLETE.json',dict(utc=utc(),outcomes=outcomes,new_model_seeds=len(f['new_models']),r52_test_read=False));status('C2_SCORING_COMPLETE',model_seeds=len(outcomes))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--model');p.add_argument('--seed',type=int);a=p.parse_args();job(a.model,a.seed) if a.model else main()
