from common6 import *
import pandas as pd,pyarrow.dataset as ds
from datetime import date
def build(config,daily,features,length,periods):
 dest=PRIVATE/'data'/config;dest.mkdir(parents=True,exist_ok=True)
 assert not (dest/'manifest.json').exists(),'Completed preparation must not be overwritten'
 daily=daily.sort_values(['user','interval_date'],kind='mergesort').copy()
 daily['interval_date']=pd.to_datetime(daily.interval_date)
 tr=daily.loc[(daily.interval_date>=periods['train'][0])&(daily.interval_date<=periods['train'][1]),features].to_numpy(np.float64)
 med=np.nanmedian(tr,axis=0);assert np.isfinite(med).all()
 tr=np.where(np.isnan(tr),med,tr);mean=tr.mean(0);scale=tr.std(0);scale[scale==0]=1
 dump(dest/'scaler.json',dict(features=features,median=med,mean=mean,scale=scale,fit_partition='TRAIN',fit_daily_rows=len(tr),n_features=len(features),missing_indicator_columns=[]))
 manifest=dict(config=config,length=length,features=features,periods=periods,scaler_sha256=sha(dest/'scaler.json'),splits={})
 for split,(start,end) in periods.items():
  d=daily.loc[(daily.interval_date>=start)&(daily.interval_date<=end)]
  days=(pd.Timestamp(end)-pd.Timestamp(start)).days+1;users=sorted(d.user.unique());per=days-length+1;n=len(users)*per
  X=np.lib.format.open_memmap(dest/f'{split}_X.npy',mode='w+',dtype=np.float32,shape=(n,length,len(features)))
  summary=np.lib.format.open_memmap(dest/f'{split}_X40.npy',mode='w+',dtype=np.float32,shape=(n,40)) if len(features)==13 else None
  y=np.empty(n,np.int8);meta={k:[] for k in ('user','start_date','end_date','sequence_id')};cursor=0
  for u,g in d.groupby('user',sort=True):
   assert str(u) not in excluded()
   assert len(g)==days and g.interval_date.nunique()==days
   raw=g[features].to_numpy(np.float64);raw=np.where(np.isnan(raw),med,raw)
   z=((raw-mean)/scale).astype(np.float32);ix=np.arange(per)[:,None]+np.arange(length)[None,:]
   x=z[ix];sl=slice(cursor,cursor+per);X[sl]=x;y[sl]=g.is_malicious_interval.to_numpy()[ix].max(1)
   if summary is not None:summary[sl]=aggregate(x)
   dates=g.interval_date.to_numpy().astype('datetime64[D]').astype(str)
   meta['user'].extend([str(u)]*per);meta['start_date'].extend(dates[:per]);meta['end_date'].extend(dates[length-1:]);meta['sequence_id'].extend([f'{pseudo(u)}_{split}_{d}' for d in dates[length-1:]])
   cursor+=per
  assert cursor==n and np.isfinite(X).all()
  X.flush();del X
  if summary is not None:summary.flush();del summary
  np.save(dest/f'{split}_y.npy',y);np.savez_compressed(dest/f'{split}_metadata.npz',**{k:np.array(v) for k,v in meta.items()})
  manifest['splits'][split]=dict(windows=n,positives=int(y.sum()),users=len(users))
 dump(dest/'manifest.json',manifest);status('DATA_READY',config=config,counts=manifest['splits']);return manifest
def main():
 assert (R2/'phase5/CHATGPT_PHASE5_REPORT.md').read_text(encoding='utf-8').rstrip().endswith('PHASE5_COMPLETE')
 pr=(H/'PREREGISTRATION_R2_HOLDOUT.md').read_bytes();assert b'## Amendment 4: final-model re-runs (exploratory)' in pr
 PRIVATE.mkdir(parents=True,exist_ok=True)
 dump(OUT/'AMENDMENT4_RECEIPT.json',dict(amendment4_sha256='1152334b1a702a3084b1a16b0dd0545ef05fc38003b8945f23bafd242ba32542',previous_bytes=14211,previous_sha256='1c3b65854f364eeee13bbbe0d5e76ade6835a1e3d02e51d927cb1c15f65943d6',utc='2026-10-22T08:07:12.6588409Z',preregistration_final_sha256=sha(H/'PREREGISTRATION_R2_HOLDOUT.md')))
 dev=devusers();assert len(dev)==1500 and not set(dev)&excluded()
 periods=dict(train=['2010-01-02','2011-02-18'],validation=['2011-02-19','2011-04-10'])
 path=FEAS/'data/processed/r5.2/interval_level/r52_user_day_intervals_dense.parquet'
 filt=ds.field('user').isin(dev)&(ds.field('interval_date')>=date(2010,1,2))&(ds.field('interval_date')<=date(2011,4,10))
 daily=ds.dataset(path,format='parquet').to_table(columns=['user','interval_date',*FEATURES,'is_malicious_interval'],filter=filt).to_pandas()
 assert set(daily.user)==set(dev) and len(daily)==1500*464
 manifests=[]
 for length in (10,30):manifests.append(build(f'r52_T{length}_F13',daily,FEATURES,length,periods))
 cat=read(STUDY/'revision_v0.2/feature_catalog_v0.2.json')['schemas']
 manifests.append(build('r52_T20_F6',daily,cat['F6_PRIMITIVES'],20,periods))
 # Map only the selected user slices; never materialize any excluded user's daily values.
 cache=STUDY/'implementation_runs';tr=cache/'full_train_preflight_20261007_r1';va=cache/'validation_preflight_20261007_r1'
 order=read(tr/'COHORT_LOCAL.json')['users'];positions=[order.index(u) for u in dev]
 frames=[];parity=[]
 for folder,split,days in ((tr,'train',413),(va,'validation',51)):
  mm=np.load(folder/f'{split}_daily_F29.npy',mmap_mode='r');assert mm.shape==(2000,days,29)
  selected=np.asarray(mm[positions],np.float64);assert len(selected)==1500
  dates=pd.date_range(*periods[split]);frame=pd.DataFrame(selected.reshape(-1,29),columns=cat['F29']);frame.insert(0,'interval_date',np.tile(dates,len(dev)));frame.insert(0,'user',np.repeat(dev,days))
  expected=daily.copy();expected['interval_date']=pd.to_datetime(expected.interval_date);expected=expected.loc[expected.interval_date.between(*periods[split])].sort_values(['user','interval_date'])
  assert np.array_equal(frame.user.to_numpy(),expected.user.to_numpy())
  assert np.allclose(frame[FEATURES].to_numpy(),expected[FEATURES].to_numpy(),equal_nan=True)
  frame['is_malicious_interval']=expected.is_malicious_interval.to_numpy();frames.append(frame);parity.append(dict(split=split,development_F13_daily_parity=True,excluded_user_slices_read=0))
 manifests.append(build('r52_T20_F29',pd.concat(frames),cat['F29'],20,periods));del frames,daily
 # r4.2 TRAIN+VALIDATION only. Existing completed-window metadata establishes boundaries.
 p=FEAS/'data/processed/tensors';meta={}
 for s in ('train','validation'):
  with np.load(p/f'r42_T20_s1_{s}.npz',allow_pickle=True) as z:meta[s]={k:z[k] for k in ('user','start_date','end_date')}
 users=sorted(set(meta['train']['user'].astype(str))-excluded());rperiod={s:[str(m['start_date'].min()),str(m['end_date'].max())] for s,m in meta.items()}
 rp=FEAS/'data/processed/interval_level/r42_user_day_intervals_dense.parquet'
 f=ds.field('user').isin(users)&(ds.field('interval_date')>=date.fromisoformat(rperiod['train'][0]))&(ds.field('interval_date')<=date.fromisoformat(rperiod['validation'][1]))
 d=ds.dataset(rp,format='parquet').to_table(columns=['user','interval_date',*FEATURES,'is_malicious_interval'],filter=f).to_pandas()
 manifests.append(build('r42_T20_F13',d,FEATURES,20,rperiod))
 dump(OUT/'DATA_MANIFEST_PHASE6.json',dict(utc=utc(),r52_test_read=False,holdout_data_read=False,development_user_list_sha256=sha(HP/'DEVELOPMENT_USERS.txt'),holdout_list_used_for_exclusion_only=True,configs=manifests,F29_parity=parity,r42_excluded_overlap=1000-len(users)))
 status('PREPARATION_COMPLETE')
if __name__=='__main__':main()
