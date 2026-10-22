from common6 import *
from bootstrap6 import bootstrap,counts,ci
import torch,pandas as pd
from sklearn.metrics import average_precision_score
def model_for(r,dv):
 config=r['phase6_config'];dim=len(read(PRIVATE/'data'/config/'manifest.json')['features']);name=r['model']
 if name=='RF_40':
  import joblib
  m=joblib.load(r['checkpoint']);m.n_jobs=2;return m
 if name=='XGBoost_40':
  from xgboost import XGBClassifier
  m=XGBClassifier();m.load_model(r['checkpoint']);m.set_params(n_jobs=2);return m
 if name=='AL_PRECURSOR':m=rt.SequenceEnsembleModel(input_dim=dim,hidden_size=64,dropout=.2,attention_dim=64,classification_head='linear',temporal_aggregation='attention')
 else:m=rt.AttentionNodeEnsemble(**dict(rt.ENCODER_ARCH,input_dim=dim))
 m.load_state_dict(torch.load(r['checkpoint'],map_location='cpu',weights_only=False)['model_state_dict']);return m.to(dv).eval()
def predict(r,x,dv):
 m=model_for(r,dv);out=[]
 with torch.inference_mode():
  for lo in range(0,len(x),1024):
   a=np.asarray(x[lo:lo+1024])
   if r['model'] in ('RF_40','XGBoost_40'):p=m.predict_proba(aggregate(a))[:,1]
   else:
    xb=torch.as_tensor(a,device=dv);z=m(xb)[0] if r['model']=='AL_PRECURSOR' else rt.student_forward(m,xb)['logit'];p=torch.sigmoid(z).cpu().numpy() if r['model']=='AL_PRECURSOR' else rt.probs(z.cpu().numpy())
   out.append(p);time.sleep(.002)
 del m;torch.cuda.empty_cache();return np.concatenate(out).astype(np.float64)
def r42_test():
 import pyarrow.dataset as ds
 from datetime import date
 config='r42_T20_F13';folder=PRIVATE/'data'/config;scaler=read(folder/'scaler.json');mean=np.array(scaler['mean']);scale=np.array(scaler['scale'])
 path=FEAS/'data/processed/tensors/r42_T20_s1_test.npz'
 with np.load(path,allow_pickle=True) as z:meta={k:z[k] for k in ('user','start_date','end_date','sequence_id')}
 mask=~np.isin(meta['user'].astype(str),list(excluded()));meta={k:v[mask].astype(str) for k,v in meta.items()};users=sorted(set(meta['user']));lo=min(meta['start_date']);hi=max(meta['end_date'])
 assert lo>'2011-03-27'
 d=ds.dataset(FEAS/'data/processed/interval_level/r42_user_day_intervals_dense.parquet',format='parquet').to_table(columns=['user','interval_date',*FEATURES,'is_malicious_interval'],filter=ds.field('user').isin(users)&(ds.field('interval_date')>=date.fromisoformat(lo))&(ds.field('interval_date')<=date.fromisoformat(hi))).to_pandas()
 d['interval_date']=pd.to_datetime(d.interval_date);d=d.sort_values(['user','interval_date']);n=len(meta['user']);x=np.lib.format.open_memmap(folder/'test_X.npy',mode='w+',dtype=np.float32,shape=(n,20,13));y=np.empty(n,np.int8)
 for u,g in d.groupby('user',sort=True):
  pos=np.flatnonzero(meta['user']==u);starts=np.searchsorted(g.interval_date.to_numpy(),meta['start_date'][pos].astype('datetime64[ns]'));ix=starts[:,None]+np.arange(20);assert np.array_equal(g.interval_date.to_numpy()[ix[:,-1]].astype('datetime64[D]').astype(str),meta['end_date'][pos]);x[pos]=((g[FEATURES].to_numpy(np.float64)[ix]-mean)/scale).astype(np.float32);y[pos]=g.is_malicious_interval.to_numpy()[ix].max(1)
 x.flush();np.save(folder/'test_y.npy',y);np.savez_compressed(folder/'test_metadata.npz',**meta)
 dump(OUT/'T3_TEST_COHORT_RECEIPT.json',dict(utc=utc(),release='r4.2',period=[lo,hi],users=len(users),windows=n,positive_windows=int(y.sum()),scaler_fit='TRAIN only',scaler_sha256=sha(folder/'scaler.json'),r52_test_accessed=False,holdout_user_overlap=0,metadata_source_sha256=sha(path)))
 return x,y,meta
def main():
 freeze=read(OUT/'TRAINING_COMPLETE.json');runs=read(OUT/'TRAINING_RESULTS_PHASE6.json');dv=device()
 for p,h in freeze['checkpoint_hashes'].items():assert sha(p)==h
 ok=[r for r in runs if r['status']=='ok'];rows=[];t2ci=[]
 # Same-input matched development T20/F13 reference from the existing Phase2 model.
 base=[];bv=rt.data()['validation'];y=bv['y'].astype(np.int8)
 with np.load(HP/'tensors/validation_metadata.npz') as z:meta={k:z[k] for k in z.files}
 _,u=np.unique(meta['user'],return_inverse=True);u=u.astype(np.int16);co=counts(len(np.unique(u)))
 for seed in SEEDS:
  ck=rt.checkpoint('TA2',seed)
  m=rt.load_model('TA2',seed,dv);out=[]
  with torch.inference_mode():
   for lo in range(0,len(y),1024):out.append(rt.probs(rt.student_forward(m,torch.as_tensor(np.asarray(bv['X'][lo:lo+1024]),device=dv))['logit'].cpu().numpy()));time.sleep(.002)
  p=np.concatenate(out);base.append(p);np.save(PRIVATE/f'DEV_T20_F13_{seed}_validation.npy',p);payload=torch.load(ck,map_location='cpu',weights_only=False);t=payload['frozen_threshold'];rows.append(dict(part='reference',config='r52_T20_F13',model='TRACE',seed=seed,reference='matched development-only original Phase2',**metrics(y,p,t)));del m;torch.cuda.empty_cache()
 original=read(OUT/'INFERENCE_PROTOCOL_FROZEN.json')['models'];old=[]
 for seed in SEEDS:
  p=np.load(PRIVATE/'inference'/f'TRACE_{seed}_T0.npy');old.append(p);spec=next(r for r in original if r['model']=='TRACE' and r['seed']==seed);rows.append(dict(part='reference',config='r52_T20_F13',model='TRACE',seed=seed,reference='original all-user checkpoint on development VALIDATION',**metrics(y,p,spec['threshold'])))
 baseboot=[bootstrap(y,p,u,co) for p in base];oldboot=[bootstrap(y,p,u,co) for p in old]
 t2boots={}
 for r in ok:
  cfg=r['phase6_config'];model=r['model'];seed=r['seed']
  if model not in ('TA2','XGBoost_40','RF_40') and not (cfg=='r42_T20_F13' and model=='AL_PRECURSOR'):continue
  folder=PRIVATE/'data'/cfg;yy=np.load(folder/'validation_y.npy');p=np.load(PRIVATE/'training'/cfg/'results'/f'{model}_{seed}_validation.npy')
  rows.append(dict(part='T3_validation' if cfg=='r42_T20_F13' else 'T2' if cfg.endswith(('F6','F29')) else 'T1',config=cfg,model='TRACE' if model=='TA2' else 'Attention-linear' if model=='AL_PRECURSOR' else model,seed=seed,reference='new development TRAIN fit' if cfg.startswith('r52') else 'new r4.2 TRAIN fit',**metrics(yy,p,r['threshold'])))
  if cfg.endswith(('F6','F29')) and model=='TA2':
   assert np.array_equal(y,yy)
   with np.load(folder/'validation_metadata.npz') as z:assert np.array_equal(z['user'],meta['user']) and np.array_equal(z['end_date'],meta['end_date'])
   b=bootstrap(y,p,u,co);t2boots[(cfg,seed)]=b
   for label,ref,bref in [('matched development 13-feature',base,baseboot),('original all-user 13-feature',old,oldboot)]:
    i=SEEDS.index(seed);t2ci.append(dict(comparison=cfg+' TRACE minus '+label,seed=seed,metric='PR_AUC',**ci(b-bref[i],average_precision_score(y,p)-average_precision_score(y,ref[i]))))
 for cfg in ('r52_T20_F6','r52_T20_F29'):
  if all((cfg,s) in t2boots for s in SEEDS):
   for label,ref,bref in [('matched development 13-feature',base,baseboot),('original all-user 13-feature',old,oldboot)]:
    vals=[t2boots[(cfg,s)]-bref[i] for i,s in enumerate(SEEDS)];ests=[r['estimate'] for r in t2ci if r['comparison']==cfg+' TRACE minus '+label];t2ci.append(dict(comparison=cfg+' TRACE minus '+label,seed='mean_three',metric='PR_AUC',**ci(np.mean(vals,0),np.mean(ests))))
 csv('T_VALIDATION_RESULTS.csv',rows);csv('T2_PAIRED_CIS.csv',t2ci)
 # Freeze before opening r4.2 TEST; one exclusive campaign sentinel.
 selected=[r for r in ok if r['phase6_config']=='r42_T20_F13' and r['model'] in ('TA2','XGBoost_40','RF_40','AL_PRECURSOR')]
 dump(OUT/'T3_MODELS_FROZEN_BEFORE_TEST.json',dict(utc=utc(),models=selected,training_complete_sha256=sha(OUT/'TRAINING_COMPLETE.json'),threshold_selection='VALIDATION only',test_evaluations_per_model=1))
 with (PRIVATE/'R42_TEST_STARTED_ONCE.json').open('x') as f:json.dump(dict(utc=utc(),manifest_sha256=sha(OUT/'T3_MODELS_FROZEN_BEFORE_TEST.json')),f)
 x,yt,mt=r42_test();_,ut=np.unique(mt['user'],return_inverse=True);ut=ut.astype(np.int16);ct=counts(len(np.unique(ut)));testrows=[];testci=[];testboot={};testpoints={}
 for r in selected:
  status('T3_TEST_ONCE',model=r['model'],seed=r['seed']);p=predict(r,x,dv);np.save(PRIVATE/f'R42_TEST_{r["model"]}_{r["seed"]}.npy',p);met=metrics(yt,p,r['threshold']);testrows.append(dict(model='TRACE' if r['model']=='TA2' else 'Attention-linear' if r['model']=='AL_PRECURSOR' else r['model'],seed=r['seed'],**met));testpoints[(r['model'],r['seed'])]=met;testboot[(r['model'],r['seed'])]=bootstrap(yt,p,ut,ct,r['threshold'])
 for r in selected:
  model=r['model'];seed=r['seed'];p=np.load(PRIVATE/f'R42_TEST_{model}_{seed}.npy');flag=p>=r['threshold'];n=ct.shape[1]
  tp=ct@np.bincount(ut,weights=(yt==1)&flag,minlength=n);fp=ct@np.bincount(ut,weights=(yt==0)&flag,minlength=n);fn=ct@np.bincount(ut,weights=(yt==1)&~flag,minlength=n)
  testboot[(model,seed)]['precision']=np.divide(tp,tp+fp,out=np.zeros_like(tp),where=(tp+fp)>0)
  testboot[(model,seed)]['recall']=np.divide(tp,tp+fn,out=np.zeros_like(tp),where=(tp+fn)>0)
 for model in ('XGBoost_40','AL_PRECURSOR'):
  for metric in ('PR_AUC','F1','precision','recall'):
   valid=[s for s in SEEDS if ('TA2',s) in testboot and (model,s) in testboot]
   if not valid:continue
   vals=[];est=[]
   for s in valid:
    d=testboot[('TA2',s)][metric]-testboot[(model,s)][metric];e=testpoints[('TA2',s)][metric]-testpoints[(model,s)][metric];vals.append(d);est.append(e);testci.append(dict(comparison='TRACE minus '+('Attention-linear' if model=='AL_PRECURSOR' else model),seed=s,metric=metric,**ci(d,e)))
   testci.append(dict(comparison='TRACE minus '+('Attention-linear' if model=='AL_PRECURSOR' else model),seed='mean_available_seeds',metric=metric,seeds=valid,**ci(np.mean(vals,0),np.mean(est))))
 csv('T3_TEST_RESULTS.csv',testrows);csv('T3_TEST_PAIRED_CIS.csv',testci);dump(OUT/'T_RESULTS.json',dict(validation=rows,feature_CIs=t2ci,r42_test=testrows,r42_test_CIs=testci));status('PART_T_ANALYSIS_COMPLETE')
if __name__=='__main__':main()
