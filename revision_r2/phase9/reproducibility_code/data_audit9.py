from common9 import *
from trigger_precision9 import trigger_precise as trigger
def main():
 gate();dev=set((HP/'DEVELOPMENT_USERS.txt').read_text().split());hu=set((HP/'HOLDOUT_USERS.txt').read_text().split());meta=np.load(HP/'tensors/train_metadata.npz');users=meta['user'];y=np.load(HP/'tensors/train_y.npy');checks={'exact1500_development_users_and500_disjoint_holdout':len(dev)==1500 and len(hu)==500 and not dev&hu and set(users)==dev};s=scaler()['development'];mu=np.array(s['mean']);sd=np.array(s['scale']);records=[]
 for c in CONFIGS:
  dest=PRIVATE/f'data/{c}';f=read(dest/'manifest.json');ix=f['indices'];selected=np.load(dest/'poison_indices.npy');clean=True
  for part in ('train','validation'):
   original=np.load(HP/f'tensors/{part}_X.npy',mmap_mode='r');actual=np.load(dest/f'{part}_X.npy',mmap_mode='r');N=len(original)
   for lo in range(0,len(actual),8192):
    hi=min(lo+8192,len(actual));ids=np.arange(lo,hi);source=ids.copy()
    if c=='backdoor01' and part=='train':source=np.where(ids<N,ids,selected[np.clip(ids-N,0,len(selected)-1)])
    expected=np.array(original[source])
    if c=='backdoor01' and part=='train':
     take=np.isin(source,selected);raw=expected[take].astype(float)*sd+mu;expected[take]=((trigger(raw)-mu)/sd).astype(np.float32)
    expected=expected[:,:,ix];clean&=np.array_equal(expected,actual[lo:hi])
  checks[c+'_feature_transformation_and_untouched_rows_exact']=bool(clean)
  if c.startswith('flip'):
   chosen=np.unique(users[selected]);expected=np.flatnonzero(np.isin(users,chosen)&(y==1));checks[c+'_whole_insider_positives_only']=np.array_equal(selected,expected)
  records.append(dict(config=c,features=len(ix),summary_features=sum(4 if i<7 else 2 for i in ix),modified_positive_windows=len(selected),actual_modified_fraction=f['actual_modified_fraction'],added_copies=f['added_trigger_copies']))
 dump(OUT/'DEVELOPMENT_DATA_AUDIT.json',dict(utc=utc(),checks=checks,all_checks_passed=all(checks.values()),conditions=records,HOLDOUT_used=False));assert all(checks.values());print('DEVELOPMENT_DATA_AUDIT_PASSED',checks,flush=True)
if __name__=='__main__':main()
