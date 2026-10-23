from common6c import *
import argparse,torch
from torch import nn
from sklearn.metrics import average_precision_score
p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--seed',required=True,type=int);a=p.parse_args();model=a.model;seed=a.seed
bundle=rt.data();rt.OUT=OUT;rt.PRIVATE=PRIVATE/'training';rt.gate=lambda:None;dv=device();path=rt.PRIVATE/'results'/f'{model}_{seed}.json';assert not path.exists();cfg=rt.recipe('XGBoost_40' if model=='XGBoost-40-aug' else model,seed,bundle);start=time.perf_counter();sc=scaler();stage={'AL_PRECURSOR':0,'T-OPT':1,'TA2':2,'XGBoost-40-aug':3}[model];rng=np.random.default_rng(np.random.SeedSequence([42,seed,stage]));augstats=[]
if model=='XGBoost-40-aug':
 from xgboost import XGBClassifier
 dest=rt.PRIVATE/f'XGBoost_augmented40_seed{seed}.npy';x=bundle['train']['X'];tab=np.lib.format.open_memmap(dest,mode='w+',dtype=np.float32,shape=(len(x),40))
 for lo in range(0,len(x),1024):
  z,st=augment(x[lo:lo+1024],rng,sc);tab[lo:lo+len(z)]=aggregate(z);augstats.append(st)
 tab.flush();cfg['params']['n_jobs']=2;m=XGBClassifier(**cfg['params']);m.fit(tab,bundle['train']['y'].astype(np.int32));q=m.predict_proba(bundle['validation']['X40'])[:,1].astype(np.float64);ck=rt.checkpoint(model,seed).with_suffix('.json');ck.parent.mkdir(parents=True,exist_ok=True);m.save_model(ck)
 r=dict(model=model,seed=seed,status='ok',checkpoint=str(ck),sha256=sha(ck),config=cfg,threshold=rt.threshold(bundle['validation']['y'],q),dev_validation_pr_auc=float(average_precision_score(bundle['validation']['y'],q)),epochs=300,best_epoch=300,wall_seconds=time.perf_counter()-start,augmented_training_rows=len(tab),augmented_summary_sha256=sha(dest),augmentation_totals={k:sum(z[k] for z in augstats) for k in augstats[0]})
else:
 precursor=model=='AL_PRECURSOR';teacher_stage=model=='T-OPT';rt.seed_all(seed,primary=not precursor);tr,va=rt.loaders(bundle,seed,precursor=precursor);kind='precursor' if precursor else 'odst';teachers={}
 if precursor:
  m=rt.build('precursor').to(dv);opt=torch.optim.Adam(m.parameters(),lr=.001,weight_decay=0.);scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(opt,mode='max',factor=.5,patience=2,min_lr=1e-5)
 elif teacher_stage:
  m=rt.build('odst');pre=torch.load(rt.checkpoint('AL_PRECURSOR',seed),map_location='cpu',weights_only=False)['model_state_dict'];inherited={k:v for k,v in pre.items() if k.startswith(('lstm.','attention.','linear_head.'))};missing,unexpected=m.load_state_dict(inherited,strict=False);assert not unexpected and not any(k.startswith(('lstm.','attention.','linear_head.')) for k in missing);m.apply_frozen_node_trainability();m.to(dv)
  init,_=next(iter(tr));ix,st=augment(init.numpy(),rng,sc);m.data_aware_initialize_from_batch(torch.from_numpy(ix).to(dv));opt=rt.build_teacher_optimizer(m);scheduler=None
 else:
  m=rt.load_model('T-OPT',seed,dv);rt.enable_student(m);opt=rt.build_student_optimizer(m);scheduler=None
  with torch.random.fork_rng(devices=[0]):
   for s in SEEDS:teachers[s]=rt.load_model('T-OPT',s,dv);rt.freeze_teacher(teachers[s])
 ratio=(len(bundle['train']['y'])-int(bundle['train']['y'].sum()))/int(bundle['train']['y'].sum());criterion=nn.BCEWithLogitsLoss(pos_weight=torch.tensor([ratio*(1 if precursor else .25)],device=dv));best=-1.;left=4;history=[];best_state=None
 for epoch in range(1,16):
  m.train()
  if teacher_stage:m.lstm.eval();m.attention.eval();m.linear_head.eval();m.dropout.eval()
  total=0.;t0=time.perf_counter();counts={k:0 for k in ('windows','source_dropped','noised','both')}
  for xb,yb in tr:
   xx,st=augment(xb.numpy(),rng,sc)
   for k,v in st.items():counts[k]+=v
   xx=torch.from_numpy(xx).to(dv);yy=yb.to(dv);opt.zero_grad(set_to_none=True);s=rt.forward(m,xx,kind);loss=criterion(s['logit'],yy)
   if teachers:
    with torch.no_grad():targets={z:rt.student_forward(t,xx) for z,t in teachers.items()};target=torch.stack([targets[z]['logit'] for z in SEEDS]).mean(0)
    loss=loss+.5*rt.et1_ensemble_logit_mse(s['logit'],target)+.5*rt.route_consistency_loss(s['choices'],targets[seed]['choices'])
   assert torch.isfinite(loss);loss.backward();nn.utils.clip_grad_norm_([p for p in m.parameters() if p.requires_grad],1.);opt.step();total+=loss.item()*len(yb);time.sleep(.002)
  if precursor:
   m.eval()
   with torch.no_grad():
    for vx,vy in va:criterion(m(vx.to(dv))[0],vy.to(dv))
  logits=rt.logits(m,va,dv,kind)
  if teachers:rt.logits(teachers[seed],va,dv)
  q=torch.sigmoid(torch.from_numpy(logits)).numpy() if precursor else rt.probs(logits);ap=float(average_precision_score(bundle['validation']['y'],q))
  if scheduler:scheduler.step(ap)
  history.append(dict(epoch=epoch,dev_validation_pr_auc=ap,train_loss=total/len(bundle['train']['y']),seconds=time.perf_counter()-t0,augmentation=counts));print(model,seed,history[-1],flush=True);dump(rt.PRIVATE/'progress'/f'{model}_{seed}.json',dict(history=history))
  if ap>best+(1e-6 if precursor else 0):best=ap;best_epoch=epoch;best_state=rt.clone_state(m);best_q=q.copy();left=4
  else:left-=1
  if left<=0:break
 assert best_state is not None;ck=rt.checkpoint(model,seed);ck.parent.mkdir(parents=True,exist_ok=True);threshold=rt.threshold(bundle['validation']['y'],best_q);torch.save(dict(model_state_dict=best_state,model=model,seed=seed,config=cfg,frozen_threshold=threshold,development_only=True,holdout_scored=False,test_read=False),ck)
 r=dict(model=model,seed=seed,status='ok',checkpoint=str(ck),sha256=sha(ck),config=cfg,threshold=threshold,dev_validation_pr_auc=best,epochs=len(history),best_epoch=best_epoch,wall_seconds=time.perf_counter()-start,history=history,online_teachers_same_augmented_input=bool(teachers))
r.update(augmentation=dict(source_probability=.3,noise_probability=.3,noise_grid=NOISE,order='source_then_noise',rng=f'SeedSequence([42,{seed},{stage}])'),development_only=True,validation_clean=True);dump(path,r);print('TRAINING_RUN_COMPLETE',model,seed,flush=True)
