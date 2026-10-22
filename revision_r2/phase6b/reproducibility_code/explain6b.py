from common6b import *
import argparse,subprocess
def feature_results(seed):
 out={}
 with np.load(EXPL/f'TA2_seed{seed}_feature_interventions.npz') as z:
  for key in z.files:
   a,b,name=key.split('_',2);out.setdefault((int(a[1:]),int(b[1:])),{})[name]=z[key]
 return out
def save_results(path,results):np.savez_compressed(path,**{f'k{k}_s{sign}_{key}':value for (k,sign),r in results.items() for key,value in r.items()})
def temporal(m,x,y,original,attention,seed,dv,dest):
 import torch
 from objective3_attention_faithfulness import forward_with_timestep_mask
 results={};n=len(x);direction=np.where(y==1,1.,-1.)
 # Exact existing helper is called unchanged. All-valid parity is checked on DEVELOPMENT only.
 dev=np.array(rt.data()['validation']['X'][:16]);xb=torch.as_tensor(dev,device=dv)
 with torch.inference_mode():
  a=rt.student_forward(m,xb)['logit'];b,_=forward_with_timestep_mask(m,xb,torch.ones((16,20),dtype=torch.bool,device=dv));parity=float(torch.max(torch.abs(a-b)).cpu())
 assert parity<5e-5
 for k in (1,3,5,10):
  rng=np.random.default_rng(np.random.SeedSequence([42,seed,1,k]));delta=np.empty(n);rd=np.empty(n);ra=np.empty(n)
  for lo in range(0,n,32):
   hi=min(lo+32,n);mask=np.ones((hi-lo,26,20),bool)
   for a,i in enumerate(range(lo,hi)):
    top=np.argsort(-attention[i],kind='stable')[:k];mask[a,0,top]=False
    for rep in range(25):mask[a,rep+1,rng.choice(20,k,replace=False)]=False
   inputs=np.repeat(x[lo:hi],26,axis=0)
   with torch.inference_mode():pred,_=forward_with_timestep_mask(m,torch.as_tensor(inputs,device=dv),torch.as_tensor(mask.reshape(-1,20),device=dv))
   z=pred.cpu().numpy().astype(np.float64).reshape(hi-lo,26);changes=direction[lo:hi,None]*(original[lo:hi,None]-z);delta[lo:hi]=changes[:,0];rd[lo:hi]=changes[:,1:].mean(1);ra[lo:hi]=(changes[:,1:]>0).mean(1);time.sleep(.002)
  results[(k,0)]=dict(signed_change=delta,accuracy=(delta>0).astype(float),random_signed_change=rd,random_accuracy=ra)
  save_results(dest/'temporal_interventions.npz',results);print('TEMPORAL_COMPLETE',seed,k,flush=True)
 return results,parity
def tree_interventions(tree,ref,seed):
 centered=(tree-ref)/8.;results={};n=len(tree);original=tree.mean(1)
 for k in (1,2,3):
  for sign in (1,-1):
   rng=np.random.default_rng(np.random.SeedSequence([42,seed,2,k,0 if sign==1 else 1]));d=np.full(n,np.nan);r=np.full(n,np.nan);ra=np.full(n,np.nan)
   for i in range(n):
    eligible=np.flatnonzero(sign*centered[i]>0)
    if len(eligible)<k:continue
    top=eligible[np.argsort(-sign*centered[i,eligible],kind='stable')[:k]];chosen=np.array([top,*[rng.choice(eligible,k,replace=False) for _ in range(25)]])
    replaced=np.broadcast_to(tree[i],(26,8)).copy();replaced[np.arange(26)[:,None],chosen]=ref[chosen];changes=sign*(original[i]-replaced.mean(1));d[i]=changes[0];r[i]=changes[1:].mean();ra[i]=(changes[1:]>0).mean()
   results[(k,sign)]=dict(signed_change=d,accuracy=np.where(np.isfinite(d),(d>0).astype(float),np.nan),random_signed_change=r,random_accuracy=ra)
 return results
def run_seed(seed):
 import torch
 spec=oldspec('TA2',seed);assert sha(spec['checkpoint'])==spec['sha256'];dv=device();m=loadmodel(spec|dict(model='TRACE'),dv);dest=PRIVATE/'explanation'/f'seed{seed}';dest.mkdir(parents=True,exist_ok=True)
 # References are established first, from all development TRAIN windows.
 refsfile=dest/'TRAIN_TREE_REFERENCES.json'
 if refsfile.exists():refs=read(refsfile);assert refs['model_sha256']==spec['sha256']
 else:
  train=rt.data()['train']['X'];sums=np.zeros(8,np.float64)
  with torch.inference_mode():
   for lo in range(0,len(train),1024):
    o=rt.student_forward(m,torch.as_tensor(np.asarray(train[lo:lo+1024]),device=dv));sums+=o['tree_outputs'].cpu().numpy().astype(np.float64).sum(0);time.sleep(.002)
  refs=dict(model_sha256=spec['sha256'],population='1500 development users TRAIN',windows=len(train),tree_output_mean=sums/len(train),test_read=False,holdout_used_for_reference=False);dump(refsfile,refs)
 selection=read(EXPL/'HOLDOUT_SELECTION.json');idx=np.array(selection['selected_bundle_row_indices']);cohort=np.load(P4P/'HOLDOUT_COHORT.npz');x=cohort['X'][idx];y=cohort['y'][idx];users=cohort['user'][idx]
 prior=np.load(EXPL/'cohort_pseudonyms.npz');assert np.array_equal(y,prior['y']) and np.array_equal(users,prior['user']);assert len(idx)==2344 and int(y.sum())==1172
 lock=dest/'H6_CONSUMED.json'
 with lock.open('x',encoding='utf-8') as h:json.dump(dict(utc=utc(),seed=seed,selection_sha256=sha(EXPL/'HOLDOUT_SELECTION.json'),references_sha256=sha(refsfile),model_sha256=spec['sha256']),h)
 values=[];att=[];logits=[]
 with torch.inference_mode():
  for lo in range(0,len(x),1024):
   out=rt.student_forward(m,torch.as_tensor(x[lo:lo+1024],device=dv));values.append(out['tree_outputs'].cpu().numpy());att.append(out['attention_weights'].cpu().numpy());logits.append(out['logit'].cpu().numpy());time.sleep(.002)
 tree=np.concatenate(values).astype(np.float64);attention=np.concatenate(att);original=np.concatenate(logits).astype(np.float64);assert tree.shape==(2344,8);assert np.max(np.abs(tree.mean(1)-original))<5e-5
 p4=np.load(P4P/f'scores/TA2_{seed}.npz')['scores'][idx];p4error=float(np.max(np.abs(rt.probs(original)-p4)));assert p4error<5e-5
 np.savez_compressed(dest/'cohort_intermediates.npz',tree=tree,attention=attention,original_logit=original,user=users,y=y,source_row=idx)
 tres=tree_interventions(tree,np.array(refs['tree_output_mean']),seed);save_results(dest/'tree_interventions.npz',tres)
 _,parity=temporal(m,x,y,original,attention,seed,dv,dest)
 dump(dest/'H6_COMPLETE.json',dict(utc=utc(),seed=seed,model_sha256=sha(spec['checkpoint']),selection_sha256=sha(EXPL/'HOLDOUT_SELECTION.json'),Phase4_prediction_max_abs_error=p4error,development_allvalid_mask_parity=parity,tree_reference_sha256=sha(refsfile),temporal_sha256=sha(dest/'temporal_interventions.npz'),tree_sha256=sha(dest/'tree_interventions.npz'),reused_feature_sha256=sha(EXPL/f'TA2_seed{seed}_feature_interventions.npz'),random_controls_new_levels=25,random_controls_inherited_feature=200,r52_test_read=False))
 print('H6_SEED_COMPLETE',seed,flush=True)
def main():
 assert (OUT/'SCORING_COMPLETE.json').exists();frozen=dict(utc=utc(),code={n:sha(CODE/n) for n in ('explain6b.py','common6b.py')},masked_softmax_helper_sha256=sha(ROOT/'src/objective3_attention_faithfulness.py'),selection_sha256=sha(EXPL/'HOLDOUT_SELECTION.json'),development_reference_sha256=sha(P4P/'EXPLANATION_DEVELOPMENT_REFERENCES.json'),feature_arrays={str(s):sha(EXPL/f'TA2_seed{s}_feature_interventions.npz') for s in SEEDS})
 if not (OUT/'H6_FROZEN.json').exists():dump(OUT/'H6_FROZEN.json',frozen)
 outcomes=[]
 for seed in SEEDS:
  dest=PRIVATE/'explanation'/f'seed{seed}';done=dest/'H6_COMPLETE.json'
  if done.exists():r=read(done)|dict(status='ok')
  elif (dest/'H6_CONSUMED.json').exists():r=dict(seed=seed,status='FAILED',reason='Previously consumed incomplete explanation; no rerun')
  else:
   status('H6_EXPLANATION',seed=seed);log=PRIVATE/'logs'/f'explain_{seed}.log'
   with log.open('w',encoding='utf-8') as h:
    proc=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/'explain6b.py'),'--seed',str(seed)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    try:rc=proc.wait(timeout=7200)
    except subprocess.TimeoutExpired:proc.kill();proc.wait();rc='TIMEOUT'
   r=read(done)|dict(status='ok') if rc==0 and done.exists() else dict(seed=seed,status='TIMEOUT' if rc=='TIMEOUT' else 'FAILED',reason=f'Exit {rc}; no repeat of consumed conditions')
  outcomes.append(r);dump(OUT/'H6_SCORING_OUTCOMES.json',outcomes)
 status('H6_SCORING_COMPLETE',outcomes=len(outcomes))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--seed',type=int);a=p.parse_args()
 if a.seed:run_seed(a.seed)
 else:main()
