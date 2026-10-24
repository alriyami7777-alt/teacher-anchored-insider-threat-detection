from common9 import *
from trigger_precision9 import trigger_precise as trigger
import argparse
def one(mode,release,n,s,c=None):
 import torch
 gate();f=read(OUT/'ANALYSIS_CODE_FROZEN.json');assert all(sha(CODE/k)==v for k,v in f['code'].items());sp=oldspec(n,s) if c is None else spec(c,n,s);keep=read(PRIVATE/f'data/{c}/manifest.json')['indices'] if c else None;key=f'{mode}_{release}_{n}_{s}'+(f'_{c}' if c else '');dest=PRIVATE/f'scores/{key}.npy';receipt=PRIVATE/f'complete/{key}.json';dv=device();m=loadmodel(sp,dv,keep);v=np.load(HP/'tensors/validation_X.npy',mmap_mode='r');pre=np.array(v[:8]);pre=pre if keep is None else pre[:,:,keep];assert np.isfinite(predict(m,n,pre,dv,keep)).all();co=Cohort(release)
 freeze=PRIVATE/f'frozen/{key}.json';dump(freeze,dict(utc=utc(),model=sp,mode=mode,release=release,feature_indices=keep,analysis_code_sha256=sha(OUT/'ANALYSIS_CODE_FROZEN.json'),target_scaler_sha256=sha(OUT/'L1_TARGET_SCALERS_FROZEN.json') if mode=='restandard' else None));lock=consume(key,frozen_sha256=sha(freeze),checkpoint_sha256=sp['sha256'],threshold=sp['threshold']);p=np.lib.format.open_memmap(dest,mode='w+',dtype=np.float64,shape=(co.n,));op=operational() if mode=='trigger' else None;meta=holdmeta() if mode=='trigger' else None;s1=scaler()['development'];mu=np.array(s1['mean']);sd=np.array(s1['scale'])
 for lo in range(0,co.n,512):
  hi=min(lo+512,co.n);x=co.batch(lo,hi,'restandard' if mode=='restandard' else 'zero',keep)
  if mode=='trigger':
   ix=np.flatnonzero(op['insider'][meta['cluster'][lo:hi]]);p[lo:hi]=np.load(PRIVATE/f'scores/new_r5.2_HOLDOUT_{n}_{s}_{c}.npy',mmap_mode='r')[lo:hi]
   if not len(ix):continue
   x=x[ix];x=((trigger(x.astype(float)*sd+mu)-mu)/sd).astype(np.float32);p[lo+ix]=predict(m,n,x,dv,keep)
  else:p[lo:hi]=predict(m,n,x,dv,keep)
  time.sleep(.002)
 p.flush();assert np.isfinite(p).all();dump(receipt,dict(utc=utc(),key=key,state='COMPLETE',windows=co.n,sha256=sha(dest),frozen_sha256=sha(freeze),consume_sha256=sha(lock),checkpoint_sha256=sp['sha256'],threshold=sp['threshold'],r52_test_read=False));print('SCORED_ONCE',key,flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--mode');p.add_argument('--release');p.add_argument('--model');p.add_argument('--seed',type=int);p.add_argument('--config');a=p.parse_args();one(a.mode,a.release,a.model,a.seed,a.config)
