from common6 import *
from bootstrap6 import bootstrap,counts,ci
import torch,pandas as pd
from torch import nn
P=PRIVATE/'inference'
class MLP(nn.Module):
 def __init__(self):
  super().__init__();self.net=nn.Sequential(nn.Linear(260,128),nn.ReLU(),nn.Dropout(.2),nn.Linear(128,64),nn.ReLU(),nn.Dropout(.2),nn.Linear(64,1))
 def forward(self,x):return self.net(x).squeeze(-1)
def load(spec,dv):
 if spec['model']=='XGBoost-260':
  from xgboost import XGBClassifier
  m=XGBClassifier();m.load_model(spec['checkpoint']);m.set_params(n_jobs=2);return m
 if spec['model']=='MLP-260':m=MLP();payload=torch.load(spec['checkpoint'],map_location='cpu',weights_only=False);m.load_state_dict(payload['state_dict'])
 else:m=rt.build('odst');m.load_state_dict(torch.load(spec['checkpoint'],map_location='cpu',weights_only=False)['model_state_dict'])
 return m.to(dv).eval()
def predict(m,spec,x,dv):
 import joblib
 scaler=joblib.load(spec['scaler']) if 'scaler' in spec else None
 p=[]
 with torch.inference_mode():
  for lo in range(0,len(x),1024):
   a=np.asarray(x[lo:lo+1024],np.float32)
   if spec['model']=='XGBoost-260':q=m.predict_proba(a.reshape(len(a),-1))[:,1]
   elif spec['model']=='MLP-260':
    tab=a.reshape(len(a),-1);tab=scaler.transform(tab).astype(np.float32);q=torch.sigmoid(m(torch.as_tensor(tab,device=dv))).cpu().numpy()
   else:q=rt.probs(rt.student_forward(m,torch.as_tensor(a,device=dv))['logit'].cpu().numpy())
   p.append(q);time.sleep(.002)
 return np.concatenate(p).astype(np.float64)
def attention(spec,x,y,meta,p,dv):
 from objective3_attention_faithfulness import rank_timesteps,derive_random_selection_seed,random_k_indices,forward_with_timestep_mask
 m=load(spec,dv);pred=p>=spec['threshold'];cases=[];effects=[];heat=[]
 for cat,mask in [('TP',(y==1)&pred),('TN',(y==0)&~pred),('FP',(y==0)&pred),('FN',(y==1)&~pred)]:
  idx=np.flatnonzero(mask);order=idx[np.argsort(p[idx],kind='mergesort')]
  for pct in (25,50,75):
   if not len(order):continue
   row=int(order[round(pct/100*(len(order)-1))]);cases.append(dict(seed=spec['seed'],category=cat,percentile=pct,row=row,user=pseudo(meta['user'][row]),probability=float(p[row]),threshold=spec['threshold']))
 with torch.inference_mode():
  for case in cases:
   i=case['row'];xb=torch.as_tensor(np.asarray(x[i:i+1]),device=dv);out=rt.student_forward(m,xb);att=out['attention_weights'].cpu().numpy().ravel();rank=rank_timesteps(att)
   if spec['seed']==42 and case['percentile']==50:
    heat.extend(dict(**case,day=j-19,attention=float(att[j])) for j in range(20))
   original_pred=int(pred[i]);base=float(p[i]) if original_pred else 1-float(p[i]);sample=str(meta['sequence_id'][i])
   for k in (1,3,5,10):
    masks=[];labels=[]
    for kind in ('delete','retain'):
     for rep in range(-1,25):
      if rep==-1:chosen=rank[:k]
      else:
       seed=derive_random_selection_seed(protocol_seed=20260724,architecture='teacher_anchored_bilstm_attention_odst',model_seed=spec['seed'],sample_id=sample+('|suf' if kind=='retain' else ''),k=k,repetition=rep)
       chosen=random_k_indices(20,k,seed)
      mask=np.ones(20,bool) if kind=='delete' else np.zeros(20,bool);mask[chosen]=kind=='retain';masks.append(mask);labels.append((kind,rep))
    z,_=forward_with_timestep_mask(m,xb.expand(len(masks),-1,-1).contiguous(),torch.as_tensor(np.array(masks),device=dv));probs=torch.sigmoid(z).cpu().numpy();conf=probs if original_pred else 1-probs;deltas=base-conf
    for kind in ('delete','retain'):
     sel=np.array([a==kind for a,b in labels]);v=deltas[sel];effects.append(dict(seed=spec['seed'],category=case['category'],percentile=case['percentile'],row=i,user=case['user'],k=k,intervention=kind,top=float(v[0]),random_mean=float(v[1:].mean()),top_minus_random=float(v[0]-v[1:].mean()),random_controls=25))
    time.sleep(.002)
 del m;torch.cuda.empty_cache();return cases,effects,heat
def main():
 f=read(OUT/'INFERENCE_PROTOCOL_FROZEN.json')
 for s in f['models']:assert sha(s['checkpoint'])==s['sha256'] and sha(s['frozen_predictions'])==s['predictions_sha256']
 for p,h in f['code_hashes'].items():assert sha(p)==h
 with (P/'INFERENCE_STARTED.json').open('x') as h:json.dump(dict(utc=utc(),frozen_protocol_sha256=sha(OUT/'INFERENCE_PROTOCOL_FROZEN.json')),h)
 dv=device();x=np.load(P/'original_validation_X.npy',mmap_mode='r');y=np.load(P/'y.npy')
 with np.load(P/'metadata.npz') as z:meta={k:z[k] for k in z.files}
 assert not set(meta['user'])&excluded();_,u=np.unique(meta['user'],return_inverse=True);u=u.astype(np.int16);c=counts(len(np.unique(u)));np.save(P/'USER_BOOTSTRAP_COUNTS.npy',c)
 med=np.load(P/'TRAIN_MEDIANS.npy');perm=np.random.default_rng(2026).permutation(20)
 rows=[];contrasts=[];boot={};point={};parity=[]
 for spec in f['models']:
  name=spec['model'];s=spec['seed'];t=spec['threshold'];base=np.load(P/f'{name}_{s}_T0.npy');point[(name,s,'T0')]=metrics(y,base,t)
  if name not in ('TRACE','XGBoost-260','MLP-260'):continue
  status('I1_INFERENCE',model=name,seed=s);m=load(spec,dv)
  fresh=predict(m,spec,x,dv);err=float(np.max(np.abs(fresh-base)));parity.append(dict(model=name,seed=s,max_abs_probability_error=err,tolerance=.0005));assert err<.0005
  for cond in ('T0','T1','T2','T3','T4','T5','T6'):
   path=P/f'{name}_{s}_{cond}.npy'
   if cond in ('T0','T6'):p=base
   else:
    if cond=='T1':xx=np.asarray(x[:,::-1,:]).copy()
    elif cond=='T2':xx=np.asarray(x[:,perm,:]).copy()
    else:
     length={'T3':1,'T4':5,'T5':10}[cond];xx=np.broadcast_to(med,x.shape).copy();xx[:,-length:,:]=x[:,-length:,:]
    p=predict(m,spec,xx,dv);del xx
   if cond!='T0':np.save(path,p)
   met=metrics(y,p,t);rows.append(dict(model=name,seed=s,condition=cond,history_days={'T3':1,'T4':5,'T5':10}.get(cond,20),**met));point[(name,s,cond)]=met
   if name=='TRACE':boot[(s,cond)]=bootstrap(y,p,u,c,t)
  del m;torch.cuda.empty_cache()
 for cond in ('T1','T2','T3','T4','T5','T6'):
  for metric in ('PR_AUC','F1'):
   delta=np.mean([boot[(s,cond)][metric]-boot[(s,'T0')][metric] for s in SEEDS],axis=0);est=np.mean([point[('TRACE',s,cond)][metric]-point[('TRACE',s,'T0')][metric] for s in SEEDS]);contrasts.append(dict(comparison=f'TRACE {cond} minus original/20 days',seed='mean_three',metric=metric,**ci(delta,est)))
   for s in SEEDS:contrasts.append(dict(comparison=f'TRACE {cond} minus original/20 days',seed=s,metric=metric,**ci(boot[(s,cond)][metric]-boot[(s,'T0')][metric],point[('TRACE',s,cond)][metric]-point[('TRACE',s,'T0')][metric])))
 csv('I1_ORDER_HISTORY.csv',rows);csv('I1_PAIRED_CIS.csv',contrasts)
 same=[];sameci=[];multi=[];dm=np.load(P/'multi_day_counts.npy');g=(dm>=2)|(y==0)
 for spec in f['models']:
  name=spec['model'];s=spec['seed'];p=np.load(P/f'{name}_{s}_T0.npy');met=metrics(y,p,spec['threshold']);same.append(dict(model=name,seed=s,**met))
  if name in ('TRACE','XGBoost-260','Attention-linear'):multi.append(dict(model=name,seed=s,cohort='multi-day G restricted to DEVELOPMENT',users=len(np.unique(meta['user'][g])),positive_users=len(np.unique(meta['user'][dm>=2])),**metrics(y[g],p[g],spec['threshold'])))
  if name!='TRACE':
   b=bootstrap(y,p,u,c,spec['threshold'])
   for metric in ('PR_AUC','F1'):sameci.append(dict(comparison='TRACE minus '+name,seed=s,metric=metric,**ci(boot[(s,'T0')][metric]-b[metric],point[('TRACE',s,'T0')][metric]-met[metric])))
 for name in ('XGBoost-260','MLP-260','RF-260','Logistic-260','Attention-linear'):
  for metric in ('PR_AUC','F1'):
   ss=[r for r in sameci if r['comparison']=='TRACE minus '+name and r['metric']==metric];# mean-seed CI computed with shared resamples below
   vals=[];ests=[]
   for s in SEEDS:
    spec=next(z for z in f['models'] if z['model']==name and z['seed']==s);p=np.load(P/f'{name}_{s}_T0.npy');b=bootstrap(y,p,u,c,spec['threshold']);vals.append(boot[(s,'T0')][metric]-b[metric]);ests.append(point[('TRACE',s,'T0')][metric]-metrics(y,p,spec['threshold'])[metric])
   sameci.append(dict(comparison='TRACE minus '+name,seed='mean_three',metric=metric,**ci(np.mean(vals,axis=0),np.mean(ests))))
 csv('I2_SAME_INFORMATION.csv',same);csv('I2_PAIRED_CIS.csv',sameci);csv('I3_MULTI_DAY.csv',multi)
 cases=[];effects=[];heat=[]
 for spec in [s for s in f['models'] if s['model']=='TRACE']:
  status('I4_ATTENTION',seed=spec['seed']);a,b,h=attention(spec,x,y,meta,np.load(P/f'TRACE_{spec["seed"]}_T0.npy'),dv);cases+=a;effects+=b;heat+=h
 effectci=[];df=pd.DataFrame(effects)
 for (s,k,kind),a in df.groupby(['seed','k','intervention']):
  groups,inv=np.unique(a.user,return_inverse=True);co=counts(len(groups));sums=np.bincount(inv,weights=a.top_minus_random);ns=np.bincount(inv);values=(co@sums)/(co@ns)
  effectci.append(dict(seed=int(s),k=int(k),intervention=kind,cases=len(a),users=len(groups),**ci(values,a.top_minus_random.mean())))
 csv('I4_CASES.csv',cases);csv('I4_ATTENTION_EFFECTS.csv',effects);csv('I4_ATTENTION_CIS.csv',effectci);csv('I4_ATTENTION_HEATMAP_data.csv',heat)
 os.environ['MPLCONFIGDIR']=str(PRIVATE/'matplotlib_cache');import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
 fig,ax=plt.subplots(figsize=(11,3.5));hh=pd.DataFrame(heat);cats=['TP','TN','FP','FN'];avail=[cat for cat in cats if cat in set(hh.category)];matrix=np.array([hh.loc[hh.category==cat].sort_values('day').attention.to_numpy() for cat in avail]);im=ax.imshow(matrix,aspect='auto',cmap='viridis');ax.set_xticks(range(20),[str(i) for i in range(-19,1)]);ax.set_yticks(range(len(avail)),avail);ax.set(xlabel='Day relative to completed-window endpoint',title='TRACE attention · seed 42 · median-probability validation cases');fig.colorbar(im,ax=ax,label='Attention weight');fig.tight_layout();fig.savefig(OUT/'I4_ATTENTION_HEATMAP.png',dpi=300);plt.close(fig)
 dump(OUT/'I_RESULTS.json',dict(order_history=rows,order_history_CIs=contrasts,same_information=same,same_information_CIs=sameci,multi_day=multi,attention_cases=cases,attention_effects=effects,attention_CIs=effectci,clean_frozen_prediction_parity=parity))
 status('PART_I_COMPLETE')
if __name__=='__main__':main()
