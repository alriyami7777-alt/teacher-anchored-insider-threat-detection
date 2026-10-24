from common11 import *
def main(c,k):
 gate();d=data_dir(c,k);d.mkdir(parents=True,exist_ok=True);assert not (d/'manifest.json').exists();sp=read(OUT/'FOLD_RECEIPT.json');nt=sp['n_train_days'];nv=sp['n_validation_days'];users=np.load(P/f'FOLD{k}_TRAIN_USERS.npy');held=np.load(P/f'FOLD{k}_HELDOUT.npy');assert not np.intersect1d(users,held).size;storage=scalers()['original'];old=scalers()['development'];dense=np.load(B/'scaled_dense_daily.npy',mmap_mode='r');raw=dense[users,:nt].astype(float)*np.array(storage['scale'])+np.array(storage['mean']);mu=raw.mean((0,1));var=raw.var((0,1));n=raw.shape[0]*raw.shape[1];del raw;pooled=c in ('C1','C2')
 if pooled:
  n0=619500;mu0=np.array(old['mean']);v0=np.array(old['scale'])**2;delta=mu-mu0;var=(n*var+n0*v0)/(n+n0)+delta**2*n*n0/(n+n0)**2;mu=(n*mu+n0*mu0)/(n+n0);n+=n0
 sd=np.sqrt(var);sd[sd==0]=1;sc=dict(mean=mu,scale=sd,fit_rows=n,fit_population='own non-held-out TRAIN daily rows before oversampling',r62_train_users=len(users),r52_development_users=1500 if pooled else 0,fold=k);dump(d/'scaler.json',sc);daily=np.load(B/'malicious_day_labels.npy',mmap_mode='r');records={}
 for part,lo,hi in [('train',0,nt),('validation',nt,nt+nv)]:
  starts=np.arange(lo,hi-19);u=np.repeat(users,len(starts));st=np.tile(starts,len(users));labels=np.empty(len(u),np.float32)
  for a in range(0,len(u),8192):
   b=min(a+8192,len(u));labels[a:b]=daily[u[a:b,None],st[a:b,None]+np.arange(20)].max(1)
  original_n6=len(u);positive=np.flatnonzero(labels>0);indices=np.arange(original_n6);target=len(positive)
  if c=='C2' and part=='train':
   assert len(positive)>0;negative=original_n6-len(positive);target=max(len(positive),int(np.ceil(.02*negative/.98)));extra=target-len(positive);cycles,remainder=divmod(extra,len(positive));indices=np.r_[indices,np.tile(positive,cycles),np.random.default_rng(42).permutation(positive)[:remainder]]
   np.save(d/'oversampled_r62_row_indices.npy',indices)
  n6=len(indices);n5=len(np.load(HP/f'tensors/{part}_y.npy')) if pooled else 0;nall=n6+n5;X=np.lib.format.open_memmap(d/f'{part}_X.npy',mode='w+',dtype=np.float32,shape=(nall,20,13));X40=np.lib.format.open_memmap(d/f'{part}_X40.npy',mode='w+',dtype=np.float32,shape=(nall,40));y=np.zeros(nall,np.float32)
  for a in range(0,n6,4096):
   gate();b=min(a+4096,n6);ix=indices[a:b];r=dense[u[ix,None],st[ix,None]+np.arange(20)].astype(float)*np.array(storage['scale'])+np.array(storage['mean']);x=((r-mu)/sd).astype(np.float32);X[a:b]=x;X40[a:b]=agg(x);y[a:b]=labels[ix]
  if pooled:
   source=np.load(HP/f'tensors/{part}_X.npy',mmap_mode='r');y[n6:]=np.load(HP/f'tensors/{part}_y.npy')
   for a in range(0,n5,4096):
    gate();b=min(a+4096,n5);x=((source[a:b].astype(float)*np.array(old['scale'])+np.array(old['mean'])-mu)/sd).astype(np.float32);X[n6+a:n6+b]=x;X40[n6+a:n6+b]=agg(x)
  X.flush();X40.flush();np.save(d/f'{part}_y.npy',y);records[part]=dict(windows=nall,positives=int(y.sum()),r62_original_windows=original_n6,r62_effective_windows=n6,r62_original_positive_windows=len(positive),r62_effective_positive_windows=int(labels[indices].sum()),r62_effective_prevalence=float(labels[indices].mean()),r52_windows=n5,validation_oversampled=False);del X,X40
 dump(d/'manifest.json',dict(utc=utc(),condition=c,fold=k,scaler=sc,periods=records,fold_k_excluded_everywhere=True,heldout_users_sha256=sha(P/f'FOLD{k}_HELDOUT.npy'),training_users_sha256=sha(P/f'FOLD{k}_TRAIN_USERS.npy'),files={p.name:sha(p) for p in d.glob('*.npy')}));print('PREPARED',c,k,records,flush=True)
if __name__=='__main__':main(sys.argv[1],int(sys.argv[2]))
