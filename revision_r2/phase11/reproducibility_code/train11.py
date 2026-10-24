from common11 import *
def main(c,k,n,s):
 import torch
 gate();f=read(OUT/'TRAINING_CODE_FROZEN.json');assert all(sha(CODE/name)==value for name,value in f['code'].items());assert sha(ROOT/'phase2_runtime.py')==f['runtime_sha256'];b=bundle(c,k);device()
 source=(ROOT/'phase2_runtime.py').read_text(encoding='utf8').replace('for epoch in range(1,16):','for epoch in range(1,16):\n        gate()').replace('for batch in tr:\n','for batch in tr:\n            gate()\n');exec(compile(source,str(ROOT/'phase2_runtime.py'),'exec'),rt.__dict__);rt.OUT=OUT;rt.PRIVATE=train_dir(c,k);rt.gate=gate;rt.data=lambda:b;original=rt.recipe
 def recipe(name,seed,data):
  cfg=original(name,seed,data);cfg.update(condition=c,fold=k,development_only=True,fold_k_excluded=True)
  if name=='XGBoost_40':cfg['params']['n_jobs']=2
  return cfg
 rt.recipe=recipe;forward=rt.forward
 def shared(*a,**kw):gate();value=forward(*a,**kw);time.sleep(.002);return value
 rt.forward=shared;dest=result_path(c,k,n,s);assert not dest.exists();rt.train_run(n,s,dest);r=read(dest);r.update(condition=c,fold=k,scaler_sha256=sha(data_dir(c,k)/'scaler.json'),development_only=True,fold_k_excluded=True);dump(dest,r)
if __name__=='__main__':main(sys.argv[1],int(sys.argv[2]),sys.argv[3],int(sys.argv[4]))
