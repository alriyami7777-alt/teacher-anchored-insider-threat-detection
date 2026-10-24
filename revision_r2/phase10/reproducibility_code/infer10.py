from common10 import *
def main(c,n,s,release):
 import torch
 gate();sp=spec(c,n,s);dv=device();m=loadmodel(sp,dv);sc=read(P/f'data/{c}/scaler.json');mu=np.array(sc['mean']);sd=np.array(sc['scale']);co=cohort(release);key=f'{c}_{n}_{s}_{release}';dest=P/f'scores/{key}.npy';lock=P/f'consumed/{key}.json';assert not lock.exists();lock.parent.mkdir(parents=True,exist_ok=True);dump(P/f'frozen/{key}.json',dict(utc=utc(),model=sp,scaler=sc,split_receipt_sha256=sha(OUT/'R62_SPLIT_RECEIPT.json')))
 with lock.open('x',encoding='utf8') as h:json.dump(dict(utc=utc(),key=key,checkpoint_sha256=sp['sha256'],threshold=sp['threshold'],frozen_sha256=sha(P/f'frozen/{key}.json')),h,indent=2)
 result=np.lib.format.open_memmap(dest,mode='w+',dtype=np.float64,shape=(len(co['y']),));old=scalers()['original' if release=='r62' else 'development'];dense=np.load(B/'scaled_dense_daily.npy',mmap_mode='r') if release=='r62' else np.load(HP/'phase4/HOLDOUT_COHORT.npz')['X']
 for a in range(0,len(result),1024):
  gate();b=min(a+1024,len(result));x=dense[co['global_u'][a:b,None],co['start'][a:b,None]+np.arange(20)] if release=='r62' else dense[a:b];x=((x.astype(float)*np.array(old['scale'])+np.array(old['mean'])-mu)/sd).astype(np.float32);result[a:b]=predict(m,n,x,dv);time.sleep(.002)
 result.flush();assert np.isfinite(result).all();dump(P/f'complete/{key}.json',dict(utc=utc(),key=key,windows=len(result),score_sha256=sha(dest),checkpoint_sha256=sp['sha256'],threshold=sp['threshold'],heldout_evaluation_only=True));print('SCORED_ONCE',key,flush=True)
if __name__=='__main__':main(sys.argv[1],sys.argv[2],int(sys.argv[3]),sys.argv[4])
