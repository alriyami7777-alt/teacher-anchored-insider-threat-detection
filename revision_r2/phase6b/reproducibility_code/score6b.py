from common6b import *
import argparse,subprocess
def build_cohorts():
 import pandas as pd,pyarrow.dataset as ds
 from datetime import date
 users=HP.joinpath('HOLDOUT_USERS.txt').read_text().splitlines();assert len(users)==500 and not set(users)&set(devusers())
 # Retain the exact Phase 4 row order and its cluster numbering.
 old=np.load(P4P/'HOLDOUT_COHORT.npz');p=PRIVATE/'cohorts';p.mkdir(parents=True,exist_ok=True)
 assert old['X'].shape==(213000,20,13) and int(old['y'].sum())==1172
 dates=[]
 for ui,u in enumerate(users):
  for part,lo,hi in [('train','2010-01-02','2011-02-18'),('validation','2011-02-19','2011-04-10')]:
   mask=(old['cluster']==ui)&(old['partition']==part);n=int(mask.sum());assert n==((pd.Timestamp(hi)-pd.Timestamp(lo)).days+1)-19
   assert np.all(old['user'][mask]==pseudo(u));dates.extend(pd.date_range(pd.Timestamp(lo)+pd.Timedelta(days=19),hi).strftime('%Y-%m-%d').tolist())
 np.savez_compressed(p/'T20_metadata.npz',**{k:old[k] for k in ('y','user','cluster','endpoint','offset0','partition')},end_date=np.array(dates))
 for t in (10,30):
  if (p/f'T{t}_BUILD.json').exists():continue
  scpath=R2/f'phase6/private/data/r52_T{t}_F13/scaler.json';sc=read(scpath);assert sc['fit_partition']=='TRAIN' and sc['fit_daily_rows']==619500
  filt=ds.field('user').isin(users)&(ds.field('interval_date')>=date(2010,1,2))&(ds.field('interval_date')<=date(2011,4,10))
  source=FEAS/'data/processed/r5.2/interval_level/r52_user_day_intervals_dense.parquet'
  frame=ds.dataset(source,format='parquet').to_table(columns=['user','interval_date',*FEATURES,'is_malicious_interval'],filter=filt).to_pandas();frame['interval_date']=pd.to_datetime(frame.interval_date)
  assert len(frame)==500*464 and frame.interval_date.max()<=pd.Timestamp('2011-04-10')
  n=500*(464-2*(t-1));x=np.lib.format.open_memmap(p/f'T{t}_X.npy',mode='w+',dtype=np.float32,shape=(n,t,13));meta={k:[] for k in ('y','user','cluster','endpoint','offset0','partition','end_date')};cur=0
  med=np.array(sc['median']);mean=np.array(sc['mean']);scale=np.array(sc['scale'])
  for ui,u in enumerate(users):
   group=frame.loc[frame.user==u].sort_values('interval_date')
   for part,lo,hi in [('train','2010-01-02','2011-02-18'),('validation','2011-02-19','2011-04-10')]:
    g=group.loc[group.interval_date.between(lo,hi)];expected=(pd.Timestamp(hi)-pd.Timestamp(lo)).days+1;assert len(g)==expected and g.interval_date.nunique()==expected and (g.interval_date.diff().dropna()==pd.Timedelta(days=1)).all();raw=g[FEATURES].to_numpy(np.float64);raw=np.where(np.isnan(raw),med,raw);z=((raw-mean)/scale).astype(np.float32);labels=g.is_malicious_interval.to_numpy();per=len(g)-t+1;ix=np.arange(per)[:,None]+np.arange(t)[None,:]
    x[cur:cur+per]=z[ix];meta['y'].extend(labels[ix].max(1));meta['endpoint'].extend(labels[ix[:,-1]]);meta['user'].extend([pseudo(u)]*per);meta['cluster'].extend([ui]*per);meta['offset0'].extend(np.arange(per)%t==0);meta['partition'].extend([part]*per);meta['end_date'].extend(g.interval_date.iloc[t-1:].dt.strftime('%Y-%m-%d').tolist());cur+=per
  assert cur==n and np.isfinite(x).all();x.flush();del x;np.savez_compressed(p/f'T{t}_metadata.npz',**{k:np.array(v) for k,v in meta.items()})
  dump(p/f'T{t}_BUILD.json',dict(length=t,windows=n,positives=int(np.sum(meta['y'])),scaler_sha256=sha(scpath),X_sha256=sha(p/f'T{t}_X.npy'),metadata_sha256=sha(p/f'T{t}_metadata.npz'),fit_on_holdout=False,r52_test_read=False))
 dump(OUT/'COHORT_BUILD.json',dict(utc=utc(),T20_source_sha256=sha(P4P/'HOLDOUT_COHORT.npz'),T10=read(p/'T10_BUILD.json'),T30=read(p/'T30_BUILD.json'),periods=['train','validation'],r52_test_read=False))
def freeze():
 assert (OUT/'TRAINING_COMPLETE.json').exists();receipt=read(OUT/'AMENDMENT5_RECEIPT.json');assert sha(H/'PREREGISTRATION_R2_HOLDOUT.md')==receipt['preregistration_final_sha256']
 specs=[]
 for old,new in [('TA2','TRACE'),('XGBoost_40','XGBoost-40'),('RF_40','RF-40'),('LightGBM_40','LightGBM-40'),('MLP','MLP-260')]:
  for s in SEEDS:
   r=oldspec(old,s);src=P4P/'scores'/f'{old}_{s}.npz';specs.append(r|dict(model=new,source_model=old,length=20,reused_phase4=True,prediction_source=str(src),prediction_sha256=sha(src)))
 for r in read(OUT/'TRAINING_RESULTS_PHASE6B.json'):
  if r['status']!='ok' or r['model'] in ('AL_PRECURSOR','T-OPT'):continue
  specs.append(r|dict(source_model=r['model'],model='TRACE-orderfree' if r['model']=='TA2' else r['model'],length=20,reused_phase4=False))
 specs+=read(OUT/'H5_REUSED_TRAINING.json')
 for r in specs:assert sha(r['checkpoint'])==r['sha256']
 teacher_checks=[];f6=read(R2/'phase6/TRAINING_COMPLETE.json')
 for t in (10,30):
  for name in ('AL_PRECURSOR','T-OPT'):
   for s in SEEDS:
    r=read(R2/f'phase6/private/training/r52_T{t}_F13/results/{name}_{s}.json');assert sha(r['checkpoint'])==r['sha256']==f6['checkpoint_hashes'][r['checkpoint']];teacher_checks.append(dict(length=t,model=name,seed=s,checkpoint=r['checkpoint'],sha256=r['sha256']))
 # Development-only functional checks, including parity of reused Phase 6 predictions.
 dv=device();checks=[]
 for r in specs:
  if r.get('reused_phase4'):continue
  if r['length']==20:x=np.array(rt.data()['validation']['X'][:16])
  else:x=np.array(np.load(R2/f"phase6/private/data/r52_T{r['length']}_F13/validation_X.npy",mmap_mode='r')[:16])
  if r['model']=='TRACE-orderfree':x=orderfree(x)
  m=loadmodel(r,dv);p=predict(m,r,x,dv);assert np.isfinite(p).all();check=dict(model=r['model'],seed=r['seed'],development_only=True,finite=True)
  if r.get('reused_from_phase6'):
   source=R2/f"phase6/private/training/r52_T{r['length']}_F13/results/{r['source_model']}_{r['seed']}_validation.npy";err=float(np.max(np.abs(p-np.load(source)[:16])));assert err<5e-5;check['Phase6_prediction_max_abs_error']=err
  checks.append(check);del m
 import torch
 torch.cuda.empty_cache()
 snapshot=PRIVATE/'code_snapshot';snapshot.mkdir(parents=True,exist_ok=True)
 import shutil
 for source in CODE.glob('*.py'):shutil.copyfile(source,snapshot/source.name)
 frozen=dict(utc=utc(),models=[{k:v for k,v in r.items() if k!='history'} for r in specs],development_preflight=checks,H5_own_teacher_verification=teacher_checks,code_snapshot={p.name:sha(p) for p in snapshot.glob('*.py')},scoring_code={n:sha(CODE/n) for n in ('score6b.py','common6b.py')},amendment5_sha256=receipt['sha256'],preregistration_sha256=receipt['preregistration_final_sha256'],training_results_sha256=sha(OUT/'TRAINING_RESULTS_PHASE6B.json'),r52_test_sealed=True)
 dump(OUT/'MODELS_FROZEN_PHASE6B.json',frozen);return frozen
def bundle(t):
 if t==20:return np.load(P4P/'HOLDOUT_COHORT.npz')['X']
 return np.load(PRIVATE/f'cohorts/T{t}_X.npy',mmap_mode='r')
def job(name,seed,condition):
 import torch
 f=read(OUT/'MODELS_FROZEN_PHASE6B.json')
 for n,h in f['scoring_code'].items():assert sha(CODE/n)==h
 assert sha(H/'PREREGISTRATION_R2_HOLDOUT.md')==f['preregistration_sha256']
 spec=next(r for r in f['models'] if r['model']==name and r['seed']==seed);assert sha(spec['checkpoint'])==spec['sha256']
 path=PRIVATE/'scores'/f'{name}_{seed}_{condition}.npy';lock=PRIVATE/'score_receipts'/f'{name}_{seed}_{condition}.json';lock.parent.mkdir(parents=True,exist_ok=True);path.parent.mkdir(parents=True,exist_ok=True)
 with lock.open('x',encoding='utf-8') as h:json.dump(dict(utc=utc(),state='CONSUMED',model=name,seed=seed,condition=condition,model_sha256=spec['sha256'],no_repeated_pass=True),h)
 assert not path.exists()
 if spec.get('reused_phase4') and condition=='original':
  assert sha(spec['prediction_source'])==spec['prediction_sha256'];p=np.load(spec['prediction_source'])['scores'];method='reused_Phase4_saved_scores'
 else:
  x=bundle(spec['length']);dv=device();m=loadmodel(spec,dv)
  if name=='TRACE-orderfree':x=orderfree(x)
  if condition=='reversed':x=np.ascontiguousarray(x[:,::-1])
  elif condition=='fixed_shuffle':x=np.ascontiguousarray(x[:,np.random.default_rng(2026).permutation(20)])
  elif condition.startswith('recent'):
   k=int(condition[6:]);xx=np.zeros_like(x);xx[:,-k:]=x[:,-k:];x=xx
  p=predict(m,spec,x,dv);del m;torch.cuda.empty_cache();method='single_new_inference_pass'
 assert np.isfinite(p).all() and len(p)==(213000 if spec['length']==20 else 500*(464-2*(spec['length']-1)))
 np.save(path,p);dump(lock,dict(utc=utc(),state='COMPLETE',model=name,seed=seed,condition=condition,model_sha256=spec['sha256'],prediction_sha256=sha(path),method=method,windows=len(p)))
 print('SCORING_COMPLETE',name,seed,condition,flush=True)
def main():
 if (OUT/'MODELS_FROZEN_PHASE6B.json').exists():f=read(OUT/'MODELS_FROZEN_PHASE6B.json')
 else:f=freeze()
 build_cohorts();jobs=[(r['model'],r['seed'],'original') for r in f['models']]
 jobs += [(m,s,c) for m in ('TRACE','XGBoost-260') for s in SEEDS for c in ('reversed','fixed_shuffle','recent1','recent5','recent10') if any(r['model']==m and r['seed']==s for r in f['models'])]
 outcomes=[]
 for name,s,cond in jobs:
  lock=PRIVATE/'score_receipts'/f'{name}_{s}_{cond}.json';log=PRIVATE/'logs'/f'score_{name}_{s}_{cond}.log'
  if lock.exists():
   r=read(lock);assert r['state']=='COMPLETE','A consumed incomplete pass cannot be rerun';outcomes.append(r);continue
  status('HOLDOUT_SCORING',model=name,seed=s,condition=cond);t0=time.perf_counter()
  with log.open('w',encoding='utf-8') as handle:
   proc=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/'score6b.py'),'--model',name,'--seed',str(s),'--condition',cond],stdout=handle,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
   try:rc=proc.wait(timeout=7200)
   except subprocess.TimeoutExpired:proc.kill();proc.wait();rc='TIMEOUT'
  if rc==0:r=read(lock)
  else:r=dict(model=name,seed=s,condition=cond,state='TIMEOUT' if rc=='TIMEOUT' else 'FAILED',seconds=time.perf_counter()-t0,reason=f'Exit {rc}; no repeated pass')
  outcomes.append(r);dump(OUT/'SCORING_OUTCOMES.json',outcomes)
 dump(OUT/'SCORING_COMPLETE.json',dict(utc=utc(),outcomes=outcomes,successful=sum(r['state']=='COMPLETE' for r in outcomes),total=len(outcomes),r52_test_read=False));status('SCORING_COMPLETE',total=len(outcomes))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--model');p.add_argument('--seed',type=int);p.add_argument('--condition');a=p.parse_args()
 if a.model:job(a.model,a.seed,a.condition)
 else:main()
