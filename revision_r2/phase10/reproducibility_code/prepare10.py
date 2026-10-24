from common10 import *
def main(c):
 gate();d=P/f'data/{c}';d.mkdir(parents=True,exist_ok=True);assert not (d/'manifest.json').exists();sp=read(OUT/'R62_SPLIT_RECEIPT.json');nt=sp['n_train_days'];nv=sp['n_validation_days'];users=np.load(P/({'within':'DEVELOPMENT','pooled':'DEVELOPMENT','adapt10':'ADAPT10','adapt25':'ADAPT25','xadapt10':'ADAPT10','xadapt25':'ADAPT25'}[c]+'_indices.npy'));storage=scalers()['original'];old=scalers()['development'];dense=np.load(B/'scaled_dense_daily.npy',mmap_mode='r');raw=dense[users,:nt].astype(float)*np.array(storage['scale'])+np.array(storage['mean']);mu=raw.mean((0,1));var=raw.var((0,1));n=raw.shape[0]*raw.shape[1];del raw
 pooled=c=='pooled' or c.startswith('xadapt')
 if pooled:
  n0=619500;mu0=np.array(old['mean']);v0=np.array(old['scale'])**2;delta=mu-mu0;var=(n*var+n0*v0)/(n+n0)+delta**2*n*n0/(n+n0)**2;mu=(n*mu+n0*mu0)/(n+n0);n+=n0
 sd=np.sqrt(var);sd[sd==0]=1;sc=dict(mean=mu,scale=sd,fit_rows=n,fit_population='own development TRAIN daily rows only',r62_development_users=len(users),r52_development_users=1500 if pooled else 0);dump(d/'scaler.json',sc);daily=np.load(B/'malicious_day_labels.npy',mmap_mode='r');records={}
 for part,lo,hi in [('train',0,nt),('validation',nt,nt+nv)]:
  starts=np.arange(lo,hi-19);u=np.repeat(users,len(starts));st=np.tile(starts,len(users));n6=len(u);n5=len(np.load(HP/f'tensors/{part}_y.npy')) if pooled else 0;nall=n6+n5
  X=np.lib.format.open_memmap(d/f'{part}_X.npy',mode='w+',dtype=np.float32,shape=(nall,20,13));X40=np.lib.format.open_memmap(d/f'{part}_X40.npy',mode='w+',dtype=np.float32,shape=(nall,40));y=np.zeros(nall,np.float32)
  for a in range(0,n6,4096):
   gate();b=min(a+4096,n6);ix=st[a:b,None]+np.arange(20);r=dense[u[a:b,None],ix].astype(float)*np.array(storage['scale'])+np.array(storage['mean']);x=((r-mu)/sd).astype(np.float32);X[a:b]=x;X40[a:b]=agg(x);y[a:b]=daily[u[a:b,None],ix].max(1)
  if pooled:
   source=np.load(HP/f'tensors/{part}_X.npy',mmap_mode='r');y[n6:]=np.load(HP/f'tensors/{part}_y.npy')
   for a in range(0,n5,4096):
    gate();b=min(a+4096,n5);x=((source[a:b].astype(float)*np.array(old['scale'])+np.array(old['mean'])-mu)/sd).astype(np.float32);X[n6+a:n6+b]=x;X40[n6+a:n6+b]=agg(x)
  X.flush();X40.flush();np.save(d/f'{part}_y.npy',y);records[part]=dict(windows=nall,positives=int(y.sum()),r62_windows=n6,r52_windows=n5);del X,X40
 dump(d/'manifest.json',dict(utc=utc(),condition=c,scaler=sc,periods=records,features_from_fixed_storage_codec=True,all_heldout_excluded=True,files={p.name:sha(p) for p in d.glob('*.npy')}));print('PREPARED',c,records,flush=True)
if __name__=='__main__':main(sys.argv[1])
