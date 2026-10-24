from common11 import *
from stats11 import weighted_ap,weighted_roc
from sklearn.metrics import average_precision_score,roc_auc_score
def main():
 gate();checks={};ids=np.load(B/'user_ids.npy');official=np.load(P/'OFFICIAL.npy');affected=np.load(P/'AFFECTED.npy');assignment=np.load(P/'FOLD_ASSIGNMENT.npy');rng=np.random.default_rng(42);expected=np.full(4000,-1,np.int8)
 for mask,alloc in [(official,[2,1,1,1]),(affected&~official,[6]*4),(~affected,[992,993,993,993])]:
  ix=np.flatnonzero(mask);ix=rng.permutation(ix[np.argsort(ids[ix],kind='stable')]);start=0
  for k,n in enumerate(alloc,1):expected[ix[start:start+n]]=k;start+=n
 checks['exact_stratified_default_rng42_fold_reconstruction']=bool(np.array_equal(assignment,expected));checks['all_fold_training_users_exclude_own_heldout']=all(np.array_equal(np.load(P/f'FOLD{k}_TRAIN_USERS.npy'),np.flatnonzero(assignment!=k)) and np.array_equal(np.load(P/f'FOLD{k}_HELDOUT.npy'),np.flatnonzero(assignment==k)) for k in range(1,5))
 # Independently compare weighted tied-score formulas with literal cluster duplication.
 y=np.array([0,1,1,0,0,1,0,1],np.int8);u=np.array([0,0,1,1,2,2,3,3],np.int32);p=np.array([.1,.2,.2,.3,.3,.7,.7,.9]);weights=np.array([[1,1,1,1],[2,0,1,1],[0,2,2,0],[1,3,0,0]],np.int16);aporder=np.argsort(-p,kind='stable');ends=np.r_[np.flatnonzero(np.diff(p[aporder])),len(p)-1];actual=weighted_ap(y[aporder],u[aporder],ends,weights);expanded=[np.repeat(np.arange(len(y)),row[u]) for row in weights];checks['weighted_AP_exact_sklearn_ties_and_cluster_duplication']=bool(np.allclose(actual,[average_precision_score(y[ix],p[ix]) for ix in expanded],atol=1e-12,rtol=1e-12));order=np.argsort(p,kind='stable');ends=np.r_[np.flatnonzero(np.diff(p[order])),len(p)-1];actual=weighted_roc(y[order],u[order],ends,weights);checks['weighted_ROC_exact_sklearn_ties_and_cluster_duplication']=bool(np.allclose(actual,[roc_auc_score(y[ix],p[ix]) for ix in expanded],atol=1e-12,rtol=1e-12))
 labelchecks=[];oversampling=[];daily=np.load(B/'malicious_day_labels.npy',mmap_mode='r');sp=read(OUT/'FOLD_RECEIPT.json');nt=sp['n_train_days'];nv=sp['n_validation_days'];manifests=list((P/'data').glob('*/manifest.json'))
 for path in manifests:
  z=read(path);users=np.load(P/f'FOLD{z["fold"]}_TRAIN_USERS.npy');d=path.parent
  for part,lo,hi in [('train',0,nt),('validation',nt,nt+nv)]:
   starts=np.arange(lo,hi-19);original=np.empty(len(users)*len(starts),np.int8)
   for a,i in enumerate(users):original[a*len(starts):(a+1)*len(starts)]=np.lib.stride_tricks.sliding_window_view(daily[i,lo:hi],20).max(1)
   expected=original
   if z['condition']=='C2' and part=='train':
    ix=np.load(d/'oversampled_r62_row_indices.npy');expected=original[ix];freq=np.bincount(ix,minlength=len(original));pos=original>0;oversampling.append(bool(np.all(freq[~pos]==1) and freq[pos].min()>=1 and freq[pos].max()-freq[pos].min()<=1 and expected.mean()>=.02));
   n6=len(expected);actual=np.load(d/f'{part}_y.npy',mmap_mode='r');labelchecks.append(bool(np.array_equal(actual[:n6],expected)))
   if z['condition'] in ('C1','C2'):labelchecks.append(bool(np.array_equal(actual[n6:],np.load(HP/f'tensors/{part}_y.npy',mmap_mode='r'))))
 checks['all_prepared_TRAIN_VALIDATION_labels_exact_independent_reconstruction']=all(labelchecks);checks['oversampling_only_r62_positive_TRAIN_even_repeats_two_percent']=all(oversampling);checks['no_validation_oversampling']=all(not z['periods']['validation']['validation_oversampled'] and z['periods']['validation']['r62_original_windows']==z['periods']['validation']['r62_effective_windows'] for z in [read(p) for p in manifests]);dump(OUT/'NUMERICAL_AUDIT.json',dict(utc=utc(),all_checks_passed=all(checks.values()),checks=checks,prepared_conditions=len(manifests),oversampling_conditions_checked=len(oversampling)));print(json.dumps(checks,indent=2));assert all(checks.values())
if __name__=='__main__':main()
