from common6 import *
import pandas as pd,pyarrow.dataset as ds,zipfile,csv as csvlib
from datetime import date
def selected_npz(path,member,indices):
 # Seek past excluded users' payload; only selected numeric rows become arrays.
 with zipfile.ZipFile(path) as z, z.open(member+'.npy') as f:
  version=np.lib.format.read_magic(f)
  reader=np.lib.format.read_array_header_1_0 if version==(1,0) else np.lib.format.read_array_header_2_0
  shape,fortran,dtype=reader(f)
  assert not fortran and not dtype.hasobject
  offset=f.tell();width=int(np.prod(shape[1:])) if len(shape)>1 else 1;size=dtype.itemsize*width
  result=np.empty((len(indices),*shape[1:]),dtype=dtype)
  breaks=np.r_[0,np.flatnonzero(np.diff(indices)!=1)+1,len(indices)]
  for lo,hi in zip(breaks[:-1],breaks[1:]):
   f.seek(offset+int(indices[lo])*size);result[lo:hi]=np.frombuffer(f.read((hi-lo)*size),dtype=dtype).reshape(result[lo:hi].shape)
  return result
def selected_csv(path,indices,column):
 wanted=set(map(int,indices));out=[]
 with Path(path).open(encoding='utf-8-sig',newline='') as f:
  for i,row in enumerate(csvlib.DictReader(f)):
   if i in wanted:out.append(float(row[column]))
 return np.asarray(out)
def main():
 dest=PRIVATE/'inference';dest.mkdir(exist_ok=True)
 assert not (OUT/'INFERENCE_PROTOCOL_FROZEN.json').exists(),'No preparation after freeze'
 dev=devusers();devset=set(dev)
 with np.load(HP/'tensors/validation_metadata.npz') as z:meta={k:z[k] for k in z.files}
 with np.load(FEAS/'data/processed/r5.2/tensors/r52_T20_s1_validation.npz',allow_pickle=True) as z:
  users=z['user'].astype(str);idx=np.flatnonzero(np.isin(users,dev));assert np.array_equal(users[idx],meta['user'])
  assert np.array_equal(z['end_date'][idx].astype(str),meta['end_date'])
 np.save(dest/'original_row_indices.npy',idx)
 scaler=read(REPO/'review/editor006a_preinference_freeze/EDITOR006A_SCALER.json');mean=np.array(scaler['mean']);scale=np.array(scaler['scale'])
 raw=ds.dataset(FEAS/'data/processed/r5.2/interval_level/r52_user_day_intervals_dense.parquet',format='parquet').to_table(columns=['user','interval_date',*FEATURES,'is_malicious_interval'],filter=ds.field('user').isin(dev)&(ds.field('interval_date')>=date(2011,2,19))&(ds.field('interval_date')<=date(2011,4,10))).to_pandas()
 raw['interval_date']=pd.to_datetime(raw.interval_date);raw=raw.sort_values(['user','interval_date'])
 x=np.lib.format.open_memmap(dest/'original_validation_X.npy',mode='w+',dtype=np.float32,shape=(48000,20,13));dm=np.empty(48000,np.int16)
 for u,g in raw.groupby('user',sort=True):
  pos=np.flatnonzero(meta['user']==u);starts=np.searchsorted(g.interval_date.to_numpy(),meta['start_date'][pos].astype('datetime64[ns]'));ix=starts[:,None]+np.arange(20)
  x[pos]=((g[FEATURES].to_numpy(np.float64)[ix]-mean)/scale).astype(np.float32);dm[pos]=g.is_malicious_interval.to_numpy()[ix].sum(1)
 assert np.array_equal(dm>0,np.load(HP/'tensors/validation_y.npy')>0)
 x.flush();del x;np.save(dest/'multi_day_counts.npy',dm)
 np.save(dest/'y.npy',np.load(HP/'tensors/validation_y.npy'))
 np.savez_compressed(dest/'metadata.npz',**meta)
 refs=read(R2/'explanation/TRAIN_REFERENCES.json');np.save(dest/'TRAIN_MEDIANS.npy',np.array([refs['TA2_scaled_feature_medians'][n] for n in FEATURES],np.float32))
 frozen=read(R2/'phase5/MODELS_AND_METHODS_FROZEN_PHASE5.json')['models']['original'];specs=[];predrows=[]
 for s in frozen:
  if s['model']!='TA2':continue
  assert sha(s['checkpoint'])==s['sha256'];s=dict(s,model='TRACE');s['frozen_predictions']=str(Path(s['checkpoint']).parent/'val_logits.npy');s['predictions_sha256']=sha(s['frozen_predictions'])
  logit=np.load(s['frozen_predictions'],mmap_mode='r');p=rt.probs(np.asarray(logit[idx]).ravel());np.save(dest/f'TRACE_{s["seed"]}_T0.npy',p);specs.append(s)
 SI=Path(r'C:\PhD\07_Projects\cert-r52-same-information-baselines\outputs\objective2\r52_same_information_baselines_v1')
 for model,dirname in [('XGBoost-260','xgboost'),('MLP-260','mlp'),('RF-260','random_forest'),('Logistic-260','logistic_regression')]:
  for seed in SEEDS:
   folder=SI/f'{dirname}_seed{seed}';summary=read(folder/'summary.json');pfile=folder/'validation_predictions.npz'
   p=selected_npz(pfile,'y_proba',idx).astype(np.float64);yy=selected_npz(pfile,'y_true',idx);assert np.array_equal(yy,np.load(dest/'y.npy'))
   np.save(dest/f'{model}_{seed}_T0.npy',p)
   ck=folder/('model.json' if model=='XGBoost-260' else 'model.pt' if model=='MLP-260' else 'model.joblib')
   assert sha(ck)==summary['model_sha256']
   spec=dict(model=model,seed=seed,threshold=summary['validation_metrics']['threshold'],checkpoint=str(ck),sha256=sha(ck),frozen_predictions=str(pfile),predictions_sha256=sha(pfile))
   if (folder/'scaler.joblib').exists():spec.update(scaler=str(folder/'scaler.joblib'),scaler_sha256=sha(folder/'scaler.joblib'))
   specs.append(spec)
 for seed in SEEDS:
  folder=FEAS/f'outputs/objective2/r52_odst_confirmation/attention_linear_seed{seed}';file=folder/'validation_predictions.csv';p=selected_csv(file,idx,'probability');assert len(p)==48000
  np.save(dest/f'Attention-linear_{seed}_T0.npy',p);thr=read(folder/'threshold.json');threshold=thr.get('threshold',thr.get('best_threshold',thr.get('selected_threshold')));assert threshold is not None
  specs.append(dict(model='Attention-linear',seed=seed,threshold=threshold,checkpoint=str(folder/'best.pt'),sha256=sha(folder/'best.pt'),frozen_predictions=str(file),predictions_sha256=sha(file)))
 # Reconstruct frozen cohort G: at least two malicious days plus all benign windows.
 dump(OUT/'INFERENCE_PROTOCOL_FROZEN.json',dict(utc=utc(),models=specs,cohort=dict(users=1500,windows=48000,positive_windows=int(np.sum(dm>0)),multi_day_positives=int(np.sum(dm>=2)),multi_day_users=len(set(meta['user'][dm>=2])),negatives=int(np.sum(dm==0)),historical_all_user_multiday_positives=613,historical_all_user_multiday_users=26,exclusions='500 HOLDOUT users omitted before feature access and all metrics'),methods=dict(shuffle_seed=2026,partial_history='TRAIN medians from frozen original TRAIN_REFERENCES.json',bootstrap_replicates=2000,bootstrap_seed=42,attention_cases='Each seed: deterministic stable probability ranks 25/50/75 percentiles within TP/TN/FP/FN; seed42 median heatmap',attention_interventions='existing objective3_attention_faithfulness.forward_with_timestep_mask: zero invalid timestep vectors and masked-softmax invalid energies, positions retained; top-k deletion and sufficiency against 25 matched controls',attention_protocol_seed=20260724,attention_484_inconsistency='484/151 belongs to r4.2; use actual r5.2 deterministic case protocol, restricted development cohort',historical_all_user_TRACE_AP=.942842),files={str(p):sha(p) for p in dest.glob('*')},code_hashes={str(p):sha(p) for p in CODE.glob('*.py') if p.name in ('common6.py','bootstrap6.py','prepare_inference6.py','inference6.py')}))
 status('INFERENCE_PREPARED',model_seeds=len(specs))
if __name__=='__main__':main()
