"""Q5 monitor: this module never reads a target-label array."""
from common8 import *
import argparse,subprocess
from scipy.stats import ks_2samp
def prepare():
 import pyarrow.dataset as ds
 from datetime import date
 gate();dest=PRIVATE/'Q5';dest.mkdir(exist_ok=True);f=read(P5/'MODELS_AND_METHODS_FROZEN_PHASE5.json');s0=f['scalers']['original'];s1=f['scalers']['development'];mean0=np.array(s0['mean']);scale0=np.array(s0['scale']);users=(HP/'DEVELOPMENT_USERS.txt').read_text().splitlines();source=Path(r'C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\interval_level\r52_user_day_intervals_dense.parquet');pred=ds.field('user').isin(users)&(ds.field('interval_date')>=date(2010,1,2))&(ds.field('interval_date')<=date(2011,2,18));raw=ds.dataset(source,format='parquet').to_table(columns=FEATURES,filter=pred).to_pandas().to_numpy(float);assert raw.shape==(619500,13)
 mean=raw.mean(0);std=raw.std(0);assert np.allclose(mean,s1['mean']) and np.allclose(np.where(std==0,1,std),s1['scale']);ref=((raw-mean0)/scale0).astype(np.float32);bins=[];rhist=[]
 for j in range(13):
  cuts=np.unique(np.quantile(ref[:,j],np.linspace(.1,.9,9)));edges=np.r_[-np.inf,cuts,np.inf];bins.append(edges);rhist.append(np.histogram(ref[:,j],edges)[0])
 deps={str(P5/'MODELS_AND_METHODS_FROZEN_PHASE5.json'):sha(P5/'MODELS_AND_METHODS_FROZEN_PHASE5.json')};features=[];flags=[];cohorts={}
 for release in ('r5.1','r6.1','r6.2','r5.2_HOLDOUT'):
  if release=='r5.2_HOLDOUT':
   file=R2/'phase7/private/daily_features.npy';rr=np.load(file,mmap_mode='r').reshape(-1,13);dense=((rr-mean0)/scale0).astype(np.float32);targetmean=np.asarray(rr).mean(0);cohorts[release]=dict(daily_rows=len(dense),daily_shape=list(np.load(file,mmap_mode='r').shape),source=str(file),windows=213000,periods='permitted TRAIN+VALIDATION only');deps[str(file)]=sha(file)
  else:
   folder=Path(f['bundles'][release]['folder']);file=folder/'scaled_dense_daily.npy';arr=np.load(file,mmap_mode='r');dense=arr.reshape(-1,13);targetmean=dense.astype(float).mean(0)*scale0+mean0;cohorts[release]=dict(daily_rows=len(dense),daily_shape=list(arr.shape),source=str(file),calendar_source=str(folder/'calendar_dates.npy'),periods='entire frozen cross-release transfer bundle');deps[str(file)]=sha(file);deps[str(folder/'calendar_dates.npy')]=sha(folder/'calendar_dates.npy')
   if release=='r6.1':indices=[folder/'window_user_index.npy',folder/'window_start_index.npy'];windows=len(np.load(indices[0],mmap_mode='r'))
   else:indices=[folder/'window_index.npy'];windows=len(np.load(indices[0],mmap_mode='r'))
   for p in indices:deps[str(p)]=sha(p)
   cohorts[release].update(windows=windows,index_sources=[str(p) for p in indices])
  shifts=np.divide(targetmean-mean,std,out=np.where(targetmean==mean,0.,np.inf),where=std>0);psis=[]
  for j,name in enumerate(FEATURES):
   th=np.histogram(dense[:,j],bins[j])[0];rh=rhist[j];pr=(rh+.5)/(rh.sum()+.5*len(rh));pt=(th+.5)/(th.sum()+.5*len(th));psi=float(np.sum((pt-pr)*np.log(pt/pr)));psis.append(psi);features.append(dict(release=release,feature=name,reference_raw_mean=float(mean[j]),reference_raw_population_SD=float(std[j]),target_raw_mean=float(targetmean[j]),standardized_mean_shift=float(shifts[j]),absolute_standardized_mean_shift=float(abs(shifts[j])),PSI=psi,bins=len(rh),reference_daily_rows=len(raw),target_daily_rows=len(dense),reference_bin_counts=rh.tolist(),target_bin_counts=th.tolist(),bin_edges_original_scaler_float32_coordinates=[str(v) for v in bins[j]]))
  maxshift=float(np.max(np.abs(shifts)));maxpsi=float(max(psis));flags.append(dict(release=release,max_absolute_standardized_feature_shift=maxshift,max_PSI=maxpsi,shift_exceeds_0_25=maxshift>.25,PSI_exceeds_0_25=maxpsi>.25,flagged=maxshift>.25 or maxpsi>.25,expected_flagged=release in ('r6.1','r6.2'),matches_requested_pattern=(maxshift>.25 or maxpsi>.25)==(release in ('r6.1','r6.2'))))
  del dense
 freeze=dict(utc=utc(),reference_daily_rows=619500,reference_population='1500 development users r5.2 TRAIN only',reference_raw_mean=mean,reference_raw_population_SD=std,reference_bins=[e.tolist() for e in bins],features=features,flags=flags,cohorts=cohorts,dependencies=deps,target_labels_read=False,bin_coordinate_note='Reference-only quantiles calculated after exact frozen S0 float32 transform, same coordinates as stored bundles; prevents binary/count inverse-scaling roundoff from inventing bin crossings. Affine mean shifts use raw S1 development reference. Repeated cut points removed; half-count smoothing.',rule='flag iff max(abs(standardized feature mean shift)) > 0.25 OR any PSI > 0.25',code_sha256=sha(__file__))
 dump(OUT/'Q5_INPUT_MONITOR_FROZEN.json',freeze);csv('Q5_FEATURE_SHIFT_PSI.csv',features);csv('Q5_RELEASE_FLAGS.csv',flags);status('Q5_INPUT_MONITOR_FROZEN',flags=[(r['release'],r['flagged']) for r in flags])
def inference(release,seed):
 import torch
 gate();f=read(P5/'MODELS_AND_METHODS_FROZEN_PHASE5.json');dv=device();s=oldspec('TA2',seed);model=loadmodel(s,dv);dest=PRIVATE/'Q5';target=dest/f'{release}_{seed}.npy';lock=dest/f'{release}_{seed}_CONSUMED.json';assert not lock.exists();dump(lock,dict(utc=utc(),release=release,seed=seed,checkpoint_sha256=s['sha256'],label_arrays_read=False))
 if release=='development_TRAIN':
  x=np.load(HP/'tensors/train_X.npy',mmap_mode='r');n=len(x)
  def batch(lo,hi):return np.array(x[lo:hi])
 elif release=='r6.1':
  folder=Path(f['bundles'][release]['folder']);dense=np.load(folder/'scaled_dense_daily.npy',mmap_mode='r');u=np.load(folder/'window_user_index.npy',mmap_mode='r');start=np.load(folder/'window_start_index.npy',mmap_mode='r');n=len(u);s0=f['scalers']['original'];s1=f['scalers']['development'];mu0=np.array(s0['mean']);sc0=np.array(s0['scale']);mu1=np.array(s1['mean']);sc1=np.array(s1['scale'])
  def batch(lo,hi):
   z=dense[np.asarray(u[lo:hi],np.int64)[:,None],np.asarray(start[lo:hi],np.int64)[:,None]+np.arange(20)];return ((z.astype(float)*sc0+mu0-mu1)/sc1).astype(np.float32)
 else:raise ValueError(release)
 p=np.lib.format.open_memmap(target,mode='w+',dtype=np.float64,shape=(n,))
 with torch.inference_mode():
  for lo in range(0,n,512):hi=min(lo+512,n);p[lo:hi]=rt.probs(rt.student_forward(model,torch.as_tensor(batch(lo,hi),device=dv))['logit'].cpu().numpy());time.sleep(.002)
 assert np.isfinite(p).all();p.flush();dump(dest/f'{release}_{seed}_COMPLETE.json',dict(utc=utc(),release=release,seed=seed,windows=n,prediction_sha256=sha(target),checkpoint_sha256=s['sha256'],unlabelled_inputs_only=True));print('Q5_SCORE_DISTRIBUTION_READY',release,seed,n,flush=True)
def main():
 if not (OUT/'Q5_INPUT_MONITOR_FROZEN.json').exists():prepare()
 frozen=read(OUT/'Q5_INPUT_MONITOR_FROZEN.json');f=read(P5/'MODELS_AND_METHODS_FROZEN_PHASE5.json');outcomes=[]
 for release in ('development_TRAIN','r6.1'):
  for seed in OLD:
   result=PRIVATE/f'Q5/{release}_{seed}_COMPLETE.json'
   if result.exists():r=read(result)|dict(status='ok')
   elif (PRIVATE/f'Q5/{release}_{seed}_CONSUMED.json').exists():r=dict(release=release,seed=seed,status='FAILED',reason='Previously consumed incomplete unlabelled inference')
   else:
    status('Q5_UNLABELLED_SCORE_DISTRIBUTION',release=release,seed=seed)
    with (PRIVATE/f'logs/Q5_{release}_{seed}.log').open('w',encoding='utf-8') as h:
     p=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/'shift8.py'),'--release',release,'--seed',str(seed)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
     try:rc=p.wait(timeout=7200)
     except subprocess.TimeoutExpired:p.kill();p.wait();rc='TIMEOUT'
    r=read(result)|dict(status='ok') if rc==0 and result.exists() else dict(release=release,seed=seed,status='TIMEOUT' if rc=='TIMEOUT' else 'FAILED',reason=f'Exit {rc}')
   outcomes.append(r);dump(OUT/'Q5_SCORING_OUTCOMES.json',outcomes)
 score_rows=[];reuse=[]
 for seed in OLD:
  reference=PRIVATE/f'Q5/development_TRAIN_{seed}.npy'
  if not reference.exists():continue
  reference=np.load(reference,mmap_mode='r');t=oldspec('TA2',seed)['threshold']
  for release in ('r5.1','r6.1','r6.2','r5.2_HOLDOUT'):
   if release in ('r5.1','r6.2'):
    path=P5/f'private/transfer/{release}/development_TA2_{seed}.npy';done=read(P5/f'A_{release}_SCORING_COMPLETE.json');assert sha(path)==done['score_hashes'][path.name];matched=next(s for s in f['models']['development'] if s['model']=='TA2' and s['seed']==seed);assert matched['sha256']==oldspec('TA2',seed)['sha256'];target=np.load(path,mmap_mode='r');reuse.append(dict(release=release,seed=seed,prediction_sha256=sha(path),checkpoint_sha256=matched['sha256'],windows=len(target)))
   elif release=='r5.2_HOLDOUT':target=probability('TA2',seed)
   else:
    path=PRIVATE/f'Q5/{release}_{seed}.npy'
    if not path.exists():continue
    target=np.load(path,mmap_mode='r')
   score_rows.append(dict(release=release,seed=seed,reference_windows=len(reference),target_windows=len(target),KS_statistic=float(ks_2samp(reference,target,method='asymp').statistic),share_above_frozen_threshold=float((target>=t).mean()),frozen_threshold=t))
 monitor=dict(utc=utc(),features=frozen['features'],flags=frozen['flags'],score_distributions=score_rows,cohorts=frozen['cohorts'],outcomes=outcomes,reused_score_receipts=reuse,target_labels_read=False,known_transfer_results_not_yet_read=True,input_monitor_sha256=sha(OUT/'Q5_INPUT_MONITOR_FROZEN.json'));dump(OUT/'Q5_MONITOR_FROZEN_BEFORE_TRANSFER_COMPARISON.json',monitor);csv('Q5_SCORE_DISTRIBUTION_SHIFTS.csv',score_rows)
 # Only now read already-published aggregate transfer results, never label arrays.
 known=[];old=read(P5/'A_RESULTS.json')
 for z in old['results']:
  if z['model']=='TRACE' and str(z['seed'])=='mean' and z['view']=='completed':known.append({k:z[k] for k in ('release','block','PR_AUC','F1','precision','recall')})
 hist=pd.read_csv(f['historical_file']);hist=hist[hist.dataset.astype(str).str.contains('r61',case=False)]
 if 'view' in hist:hist=hist[hist['view']=='COMPLETED_WINDOW']
 for family,g in hist.groupby('family'):known.append(dict(release='r6.1',block='historical_'+str(family),PR_AUC=float(g.PR_AUC.mean()),F1=float(g.F1.mean()) if 'F1' in g else None,population_note='historical all-user model; not silently equated to Phase4 development-user checkpoint'))
 csv('Q5_KNOWN_TRANSFER_COMPARISON.csv',known);dump(OUT/'Q5_RESULTS.json',monitor|dict(known_transfer_summary=known,monitor_frozen_before_known_summary=True,monitor_sha256=sha(OUT/'Q5_MONITOR_FROZEN_BEFORE_TRANSFER_COMPARISON.json')));status('Q5_COMPLETE',score_rows=len(score_rows))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--release');p.add_argument('--seed',type=int);a=p.parse_args();prepare() if a.prepare else inference(a.release,a.seed) if a.release else main()
