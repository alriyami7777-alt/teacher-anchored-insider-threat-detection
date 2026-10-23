from common8 import *
import argparse
def main(name,seed):
 gate();f=read(OUT/'TRAINING_CODE_FROZEN.json');assert sha(ROOT/'phase2_runtime.py')==f['runtime_sha256'];assert all(sha(CODE/n)==h for n,h in f['code'].items());assert seed in NEW
 b=bundle();dv=device();original_recipe=rt.recipe;rt.PRIVATE=PRIVATE/'training';rt.OUT=OUT;rt.gate=gate;rt.data=lambda:b
 def recipe(n,s,data):
  cfg=original_recipe(n,s,data)
  if n=='XGBoost_40':cfg['params']['n_jobs']=2
  return cfg
 rt.recipe=recipe
 def ensemble(data,uni,d):
  assert not uni;return np.load(HP/'teacher_cache/bi_train_ensemble_logits.npy')
 rt.ensemble=ensemble;original_forward=rt.forward
 def forward(*args,**kwargs):
  out=original_forward(*args,**kwargs);time.sleep(.002);return out
 rt.forward=forward;path=resultpath(name,seed);assert not path.exists();rt.train_run(name,seed,path)
 r=read(path);r.update(consensus_seeds=list(OLD) if name=='TA2' else [],matched_teacher_seed=seed if name in ('TA2','F00') else None,development_only=True,validation_only_checkpoint_and_threshold=True,source_runtime_sha256=f['runtime_sha256'],code_sha256=sha(__file__));dump(path,r)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--seed',type=int,required=True);a=p.parse_args();main(a.model,a.seed)
