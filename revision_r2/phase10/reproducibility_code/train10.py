from common10 import *
def main(c,n,s):
 import torch
 gate();f=read(OUT/'TRAINING_CODE_FROZEN.json');assert all(sha(CODE/k)==h for k,h in f['code'].items());assert sha(ROOT/'phase2_runtime.py')==f['runtime_sha256'];b=bundle(c);dv=device()
 # Frozen source derivative changes only epoch-bound config and hard-stop calls.
 source=(ROOT/'phase2_runtime.py').read_text(encoding='utf8');source=source.replace('for epoch in range(1,16):','for epoch in range(1,cfg[\'max_epochs\']+1):\n        gate()').replace('for batch in tr:\n','for batch in tr:\n            gate()\n')
 exec(compile(source,str(ROOT/'phase2_runtime.py'),'exec'),rt.__dict__)
 rt.OUT=OUT;rt.PRIVATE=P/f'training/{c}';rt.gate=gate;rt.data=lambda:b
 origrecipe=rt.recipe
 def recipe(name,seed,data):
  cfg=origrecipe(name,seed,data);cfg.update(condition=c,development_only=True,clean_validation_selection=True)
  if name=='XGBoost_40':cfg['params']['n_jobs']=2
  if c.startswith('adapt'):
   cfg.update(max_epochs=10,encoder_lr=3e-6,attention_lr=3e-6,head_lr=1e-4,initialization='original r5.2 TRACE checkpoint',teacher_target='original r5.2 three-teacher consensus on own selected r6.2 TRAIN')
  return cfg
 rt.recipe=recipe
 if c.startswith('adapt'):
  calls=[0]
  def lm(name,seed,device):
   if name=='T-OPT':
    calls[0]+=1;return loadmodel(oldspec('TA2' if calls[0]==1 else 'T-OPT',seed),device)
   return loadmodel(oldspec(name,seed),device)
  rt.load_model=lm;optimizer=rt.build_student_optimizer
  def opt(m):
   o=optimizer(m)
   for group in o.param_groups:group['lr']/=10
   return o
  rt.build_student_optimizer=opt
  def consensus(data,uni,device):
   p=rt.PRIVATE/'teacher_cache/bi_train_ensemble_logits.npy'
   if p.exists():return np.load(p)
   loader=rt.DataLoader(rt.TensorDataset(torch.from_numpy(data['train']['X'])),batch_size=1024,shuffle=False,num_workers=0);ls=[]
   for k in SEEDS:
    gate();m=loadmodel(oldspec('T-OPT',k),device);rt.freeze_teacher(m);ls.append(rt.logits(m,loader,device));del m;torch.cuda.empty_cache()
   result=np.mean(ls,axis=0);p.parent.mkdir(parents=True,exist_ok=True);np.save(p,result);return result
  rt.ensemble=consensus
 forward=rt.forward
 def shared(*a,**kw):gate();v=forward(*a,**kw);time.sleep(.002);return v
 rt.forward=shared;dest=P/f'training/{c}/results/{n}_{s}.json';assert not dest.exists();rt.train_run(n,s,dest);r=read(dest);r.update(condition=c,scaler_sha256=sha(P/f'data/{c}/scaler.json'),development_only=True);dump(dest,r)
if __name__=='__main__':main(sys.argv[1],sys.argv[2],int(sys.argv[3]))
