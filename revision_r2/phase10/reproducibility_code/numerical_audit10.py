from common10 import *
from stats10 import weighted_ap
from sklearn.metrics import average_precision_score
def main():
 gate();checks={};ids=np.load(B/'user_ids.npy');flags=np.load(P/'INSIDER_STATUS.npy');held=np.load(P/'HOLDOUT_indices.npy');dev=np.load(P/'DEVELOPMENT_indices.npy');rng=np.random.default_rng(42);expected=[]
 for flag,k in ((1,15),(0,1985)):
  ix=np.flatnonzero(flags==flag);ix=ix[np.argsort(ids[ix])];rng.shuffle(ix);expected.extend(ix[:k])
 checks['split_exact_default_rng42_stratified']=np.array_equal(np.sort(expected),held)
 checks['disjoint_2000_2000_15_14']=len(dev)==len(held)==2000 and not len(np.intersect1d(dev,held)) and flags[held].sum()==15 and flags[dev].sum()==14
 small=np.load(P/'ADAPT10_indices.npy');large=np.load(P/'ADAPT25_indices.npy');checks['nested_adaptation_excludes_heldout']=len(small)==200 and len(large)==500 and set(small)<=set(large)<=set(dev) and flags[small].sum()==1 and flags[large].sum()==4
 co=cohort();sp=read(OUT/'R62_SPLIT_RECEIPT.json');nt=sp['n_train_days'];nv=sp['n_validation_days'];checks['eligible_windows_no_boundary_or_future']=len(co['y'])==850000 and np.all((co['start']<=nt-20)|((co['start']>=nt)&(co['start']<=nt+nv-20)))
 y=np.array([1,0,1,0,0,1],np.int8);p=np.array([.9,.9,.6,.4,.4,.1]);u=np.array([0,1,0,1,2,2],np.int32);w=np.array([[1,1,1],[2,0,1],[0,1,2]],np.int16);ends=np.r_[np.flatnonzero(np.diff(p)),len(p)-1];checks['weighted_AP_ties_matches_sklearn']=np.allclose(weighted_ap(y,u,ends,w),[average_precision_score(y,p,sample_weight=r[u]) for r in w]);x=np.random.default_rng(42).normal(size=(8,20,13)).astype(np.float32);checks['summary_40_features_finite']=agg(x).shape==(8,40) and np.isfinite(agg(x)).all()
 datarecords=[];dense=np.load(B/'scaled_dense_daily.npy',mmap_mode='r');daily=np.load(B/'malicious_day_labels.npy',mmap_mode='r');storage=scalers()['original']
 for c in ('within','adapt10','adapt25','xadapt10','xadapt25','pooled'):
  path=P/f'data/{c}/manifest.json'
  if not path.exists():continue
  manifest=read(path);sc=manifest['scaler'];users=np.load(P/({'within':'DEVELOPMENT','pooled':'DEVELOPMENT','adapt10':'ADAPT10','adapt25':'ADAPT25','xadapt10':'ADAPT10','xadapt25':'ADAPT25'}[c]+'_indices.npy'));record=dict(condition=c,files_match=all(sha(P/f'data/{c}/{n}')==h for n,h in manifest['files'].items()),development_users_only=set(users)<=set(dev));valid=True
  labelparity=True
  for part,lo,hi in [('train',0,nt),('validation',nt,nt+nv)]:
   a=np.arange(min(17,hi-lo-19));u0=users[0];raw=dense[u0,lo+a[:,None]+np.arange(20)].astype(float)*np.array(storage['scale'])+np.array(storage['mean']);expected=((raw-np.array(sc['mean']))/np.array(sc['scale'])).astype(np.float32);actual=np.load(P/f'data/{c}/{part}_X.npy',mmap_mode='r')[:len(a)];lab=np.load(P/f'data/{c}/{part}_y.npy',mmap_mode='r')[:len(a)];valid &= np.array_equal(expected,actual) and np.array_equal(lab,daily[u0,lo+a[:,None]+np.arange(20)].max(1))
   starts=np.arange(lo,hi-19);expected_y=np.concatenate([np.lib.stride_tricks.sliding_window_view(daily[user,lo:hi],20).max(1) for user in users]);all_y=np.load(P/f'data/{c}/{part}_y.npy',mmap_mode='r');labelparity &= np.array_equal(all_y[:len(expected_y)],expected_y)
   if manifest['periods'][part]['r52_windows']:labelparity &= np.array_equal(all_y[len(expected_y):],np.load(HP/f'tensors/{part}_y.npy'))
  record['sampled_exact_features_and_labels']=bool(valid);record['all_TRAIN_VALIDATION_labels_exact']=bool(labelparity);datarecords.append(record)
 checks['all_available_prepared_data_integrity']=all(all(r[k] for k in ('files_match','development_users_only','sampled_exact_features_and_labels','all_TRAIN_VALIDATION_labels_exact')) for r in datarecords)
 dump(OUT/'DEVELOPMENT_NUMERICAL_AUDIT.json',dict(utc=utc(),checks=checks,all_checks_passed=all(checks.values()),prepared_data=datarecords,no_target_forward=True));assert all(checks.values()),checks;print('NUMERICAL_AUDIT_PASS',checks,flush=True)
if __name__=='__main__':main()
