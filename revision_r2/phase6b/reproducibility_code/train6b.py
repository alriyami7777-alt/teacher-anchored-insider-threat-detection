from common6b import *
import argparse,torch
from torch import nn
from sklearn.metrics import average_precision_score
p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--seed',required=True,type=int);a=p.parse_args();name=a.model;s=a.seed
dv=device();started=time.perf_counter()
if name in ('AL_PRECURSOR','T-OPT','TA2'):
 rt.PRIVATE=PRIVATE/'training/orderfree';rt.OUT=OUT;rt.gate=lambda:None;rt.data=lambda:loadbundle('orderfree')
 original=rt.forward
 def forward(*args,**kwargs):
  out=original(*args,**kwargs);time.sleep(.002);return out
 rt.forward=forward
 path=rt.PRIVATE/'results'/f'{name}_{s}.json';assert not path.exists();rt.train_run(name,s,path)
else:
 path=resultpath(name,s);assert not path.exists();b=rt.data();tr=b['train'];va=b['validation'];rt.seed_all(s);ck=PRIVATE/'training'/name/f'seed{s}/best.joblib';ck.parent.mkdir(parents=True,exist_ok=True)
 if name in ('RF-260','XGBoost-260','LightGBM-260'):
  source={'RF-260':'RF_40','XGBoost-260':'XGBoost_40','LightGBM-260':'LightGBM_40'}[name];frozen=oldspec(source,s)
  params=dict(frozen.get('params',frozen.get('config',{}).get('params',{})));params['n_jobs']=2
  if name=='RF-260':
   from sklearn.ensemble import RandomForestClassifier
   m=RandomForestClassifier(**params)
  elif name=='XGBoost-260':
   from xgboost import XGBClassifier
   m=XGBClassifier(**params)
  else:
   from lightgbm import LGBMClassifier
   m=LGBMClassifier(**params)
  m.fit(tr['X'].reshape(len(tr['X']),260),tr['y'].astype(np.int32));q=m.predict_proba(va['X'].reshape(len(va['X']),260))[:,1]
  import joblib
  if name=='XGBoost-260':ck=ck.with_suffix('.json');m.save_model(ck)
  else:joblib.dump(m,ck)
  best_epoch=epochs=params['n_estimators'];history=[];threshold=threshold4(va['y'],q) if name=='LightGBM-260' else rt.threshold(va['y'],q)
 else:
  assert name=='MLP-40';m=nn.Sequential(nn.Linear(40,128),nn.ReLU(),nn.Dropout(.2),nn.Linear(128,64),nn.ReLU(),nn.Dropout(.2),nn.Linear(64,1)).to(dv)
  loader=torch.utils.data.DataLoader(torch.utils.data.TensorDataset(torch.from_numpy(tr['X40']),torch.from_numpy(tr['y'])),batch_size=1024,shuffle=True,generator=torch.Generator().manual_seed(s),num_workers=0)
  vl=torch.utils.data.DataLoader(torch.utils.data.TensorDataset(torch.from_numpy(va['X40'])),batch_size=1024,shuffle=False,num_workers=0)
  opt=torch.optim.Adam(m.parameters(),lr=.001);crit=nn.BCEWithLogitsLoss(pos_weight=torch.tensor([.25*(591000-3040)/3040],device=dv));best=-1.;left=4;history=[];ck=ck.with_suffix('.pt')
  for epochs in range(1,16):
   m.train();loss_sum=0.;t0=time.perf_counter()
   for x,y in loader:
    opt.zero_grad(set_to_none=True);out=m(x.to(dv)).squeeze(-1);loss=crit(out,y.to(dv));assert torch.isfinite(loss);loss.backward();nn.utils.clip_grad_norm_(m.parameters(),1.);opt.step();loss_sum+=loss.item()*len(x);time.sleep(.002)
   m.eval();q=[]
   with torch.inference_mode():
    for (x,) in vl:q.append(m(x.to(dv)).squeeze(-1).cpu().numpy())
   q=rt.probs(np.concatenate(q));ap=float(average_precision_score(va['y'],q));history.append(dict(epoch=epochs,development_AP=ap,train_loss=loss_sum/591000,seconds=time.perf_counter()-t0));print(name,s,history[-1],flush=True)
   if ap>best:best=ap;best_epoch=epochs;best_q=q.copy();torch.save(dict(model_state_dict={k:v.detach().cpu().clone() for k,v in m.state_dict().items()}),ck);left=4
   else:left-=1
   if left<=0:break
  q=best_q;threshold=threshold4(va['y'],q);params=dict(optimizer='Adam',learning_rate=.001,batch_size=1024,positive_weight=.25*(591000-3040)/3040,gradient_clip=1.,max_epochs=15,patience=4,hidden=[128,64],dropout=.2,input_width=40)
 r=dict(model=name,seed=s,status='ok',checkpoint=str(ck),sha256=sha(ck),threshold=threshold,development_AP=float(average_precision_score(va['y'],q)),epochs=epochs,best_epoch=best_epoch,wall_seconds=time.perf_counter()-started,params=params,history=history,development_only=True)
 dump(path,r)
print('TRAINING_RUN_COMPLETE',name,s,flush=True)
