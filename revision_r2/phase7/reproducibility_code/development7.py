from common7 import *
def main():
 sys.path.insert(0,str(ROOT));import phase2_runtime as rt
 import torch
 torch.set_num_threads(2);dv=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
 if dv.type=='cuda':torch.cuda.set_per_process_memory_fraction(.35)
 d=HP/'tensors';y=np.load(d/'validation_y.npy').astype(int);assert len(y)==48000 and y.sum()==473
 X=np.load(d/'validation_X.npy',mmap_mode='r');validation={};receipts=[];(PRIVATE/'development').mkdir(exist_ok=True)
 for name in ('TRACE','XGBoost-40','L1'):
  for seed in SEEDS:
   s=spec(name,seed);assert sha(s['checkpoint'])==s['sha256'];dest=PRIVATE/f'development/{name}_{seed}.npy'
   if name=='XGBoost-40':
    source=Path(s['checkpoint']).parent/'development_validation_probabilities.npz';z=np.load(source);assert np.array_equal(y,z['y_true']);p=z['y_proba'].astype(np.float64);origin=str(source)
   else:
    model=rt.load_model(s['model'],seed,dv);values=[]
    with torch.inference_mode():
     for lo in range(0,len(y),512):
      xb=torch.as_tensor(np.array(X[lo:lo+512]),device=dv);values.append(rt.forward(model,xb,'linear' if name=='L1' else 'odst')['logit'].cpu().numpy());time.sleep(.002)
    p=rt.probs(np.concatenate(values));del model
    if dv.type=='cuda':torch.cuda.empty_cache()
    origin='frozen Phase 4 checkpoint; development VALIDATION inference only'
   assert np.isfinite(p).all() and p.shape==y.shape;np.save(dest,p);validation[name,seed]=p
   receipts.append(dict(model=name,seed=seed,origin=origin,checkpoint_sha256=s['sha256'],prediction_sha256=sha(dest),validation_AP=float(average_precision_score(y,p)),frozen_model_threshold=s['threshold'],reproduced_original_threshold=original_threshold(y,p),development_only=True,holdout_inference=False))
   status('DEVELOPMENT_VALIDATION_READY',model=name,seed=seed)
 thresholds=[];comb=[]
 for seed in SEEDS:
  p=combination(validation['TRACE',seed],validation['XGBoost-40',seed]);t=original_threshold(y,p);np.save(PRIVATE/f'development/rank_average_{seed}.npy',p);comb.append(dict(model='Rank-average',seed=seed,threshold=t,rule='original sorted grid+quantile max-F1; first maximum',**{f'validation_{k}':v for k,v in metrics(y,p,t).items() if k!='threshold'}))
 for name in ('TRACE','XGBoost-40','L1'):
  for seed in SEEDS:
   for r in rule_thresholds(y,validation[name,seed]):thresholds.append(dict(model=name,seed=seed,**r))
 frozen=dict(utc=utc(),validation_only=True,validation_windows=len(y),validation_positive_windows=int(y.sum()),development_predictions=receipts,P5_combination_thresholds=comb,P6_thresholds=thresholds,amendment7_sha256=read(OUT/'AMENDMENT7_RECEIPT.json')['sha256'],code_hashes={p.name:sha(p) for p in CODE.glob('*.py')},r52_test_read=False,no_retraining=True)
 dump(OUT/'DEVELOPMENT_THRESHOLDS_FROZEN.json',frozen);csv('P5_DEVELOPMENT_COMBINATION_THRESHOLDS.csv',comb);csv('P6_DEVELOPMENT_THRESHOLDS.csv',thresholds);status('DEVELOPMENT_THRESHOLDS_FROZEN',P5=len(comb),P6=len(thresholds))
if __name__=='__main__':main()
