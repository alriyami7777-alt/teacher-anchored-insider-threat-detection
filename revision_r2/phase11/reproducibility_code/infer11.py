from common11 import *
def main(c,k,n,s,release):
 import torch
 gate();sp=spec(c,k,n,s);dv=device();m=loadmodel(sp,dv);sc=read(data_dir(c,k)/'scaler.json');mu=np.array(sc['mean']);sd=np.array(sc['scale']);key=f'{c}_fold{k}_{n}_{s}_{release}';dest=P/f'scores/{key}.npy';lock=P/f'consumed/{key}.json';assert not lock.exists();co=cohort(k) if release=='r62' else None;N=len(co['global_u']) if co is not None else len(np.load(R2/'phase6b/private/cohorts/T20_metadata.npz')['y']);dump(P/f'frozen/{key}.json',dict(utc=utc(),model=sp,scaler=sc,fold_receipt_sha256=sha(OUT/'FOLD_RECEIPT.json')));lock.parent.mkdir(parents=True,exist_ok=True)
 with lock.open('x',encoding='utf8') as h:json.dump(dict(utc=utc(),key=key,checkpoint_sha256=sp['sha256'],threshold=sp['threshold'],frozen_sha256=sha(P/f'frozen/{key}.json')),h,indent=2)
 dest.parent.mkdir(parents=True,exist_ok=True);result=np.lib.format.open_memmap(dest,mode='w+',dtype=np.float64,shape=(N,));old=scalers()['original' if release=='r62' else 'development'];dense=np.load(B/'scaled_dense_daily.npy',mmap_mode='r') if release=='r62' else np.load(HP/'phase4/HOLDOUT_COHORT.npz')['X']
 for a in range(0,N,1024):
  gate();b=min(a+1024,N);x=dense[co['global_u'][a:b,None],co['start'][a:b,None]+np.arange(20)] if release=='r62' else dense[a:b];x=((x.astype(float)*np.array(old['scale'])+np.array(old['mean'])-mu)/sd).astype(np.float32);result[a:b]=predict(m,n,x,dv);time.sleep(.002)
 result.flush();assert np.isfinite(result).all();dump(P/f'complete/{key}.json',dict(utc=utc(),key=key,condition=c,fold=k,model=n,seed=s,release=release,windows=N,score_sha256=sha(dest),checkpoint_sha256=sp['sha256'],threshold=sp['threshold'],evaluation_only=True));print('SCORED_ONCE',key,flush=True)
if __name__=='__main__':main(sys.argv[1],int(sys.argv[2]),sys.argv[3],int(sys.argv[4]),sys.argv[5])
