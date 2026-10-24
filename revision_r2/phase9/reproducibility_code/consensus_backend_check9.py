"""Development-only diagnosis of consensus cache numerical parity; never rewrites a cache."""
from common9 import *
def main():
 import torch
 gate();dv=device();rt.seed_all(42);records=[]
 for config in CONFIGS:
  f=read(PRIVATE/f'data/{config}/manifest.json');x=np.load(PRIVATE/f'data/{config}/train_X.npy',mmap_mode='r');ix=np.unique(np.r_[0,len(x)-1,np.random.default_rng(42).choice(len(x),8,replace=False)]);cachefile=PRIVATE/f'training/{config}/teacher_cache/bi_train_ensemble_logits.npy';before=sha(cachefile);cache=np.load(cachefile);compact=[];original_batch=[]
  with torch.no_grad():
   for seed in SEEDS:
    model=loadmodel(spec(config,'T-OPT',seed),dv,f['indices']);rt.freeze_teacher(model);compact.append(rt.student_forward(model,torch.as_tensor(np.array(x[ix]),device=dv))['logit'].cpu().numpy());full=np.empty(len(ix),np.float32)
    for lo in np.unique(ix//1024*1024):
     hi=min(int(lo)+1024,len(x));select=(ix>=lo)&(ix<hi);out=rt.student_forward(model,torch.as_tensor(np.array(x[int(lo):hi]),device=dv))['logit'].cpu().numpy();full[select]=out[ix[select]-lo];time.sleep(.002)
    original_batch.append(full);del model;torch.cuda.empty_cache()
  compact=np.mean(compact,0);matched=np.mean(original_batch,0);error=float(np.max(abs(matched-cache[ix])));records.append(dict(condition=config,sampled_rows=ix.tolist(),training_windows=len(x),cache_windows=len(cache),cache_sha256=before,cache_unchanged=sha(cachefile)==before,GPU_compact_batch_max_abs_error=float(np.max(abs(compact-cache[ix]))),GPU_original_1024_batch_max_abs_error=error,original_backend_and_batch_parity=error<2e-5));print('CONSENSUS_BACKEND_PARITY',config,records[-1],flush=True)
 result=dict(utc=utc(),population='development TRAIN only',no_training=True,no_target_inference=True,no_cache_rewrite=True,original_batch_size=1024,cudnn_deterministic=torch.backends.cudnn.deterministic,cudnn_benchmark=torch.backends.cudnn.benchmark,records=records,all_original_backend_checks_passed=all(z['original_backend_and_batch_parity'] and z['cache_unchanged'] and z['training_windows']==z['cache_windows'] for z in records),code_sha256=sha(__file__));dump(OUT/'TEACHER_CONSENSUS_BACKEND_VERIFICATION.json',result);assert result['all_original_backend_checks_passed'];print('ALL_CONSENSUS_MATCHED_BACKEND_CHECKS_PASSED',flush=True)
if __name__=='__main__':main()
