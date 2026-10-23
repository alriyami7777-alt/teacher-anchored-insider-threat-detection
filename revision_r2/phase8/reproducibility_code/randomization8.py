from common8 import *
import argparse,subprocess,copy
from scipy.stats import rankdata
def statehash(m):
 h=hashlib.sha256()
 for n,v in sorted(m.state_dict().items()):h.update(n.encode());h.update(v.detach().cpu().numpy().tobytes())
 return h.hexdigest()
def correlations(a,b):
 aa=rankdata(a,axis=1,method='average');bb=rankdata(b,axis=1,method='average');aa-=aa.mean(1,keepdims=True);bb-=bb.mean(1,keepdims=True);den=np.linalg.norm(aa,axis=1)*np.linalg.norm(bb,axis=1);return np.divide((aa*bb).sum(1),den,out=np.full(len(aa),np.nan),where=den>0)
def final_ig(model,x,baseline,dv,progress=None):
 import torch
 n=len(x);attrs=np.empty((n,20,13),np.float32);diff=np.empty(n,float);base=torch.as_tensor(baseline,device=dv,dtype=torch.float32)
 with torch.backends.cudnn.flags(enabled=False):
  with torch.no_grad():fb=float(rt.student_forward(model,base[None])['logit'].cpu()[0])
  for lo in range(0,n,64):
   hi=min(lo+64,n);xx=torch.as_tensor(x[lo:hi],device=dv,dtype=torch.float32);d=xx-base;grads=torch.zeros_like(xx)
   for step in range(51):
    z=(base+(step/50)*d).detach().requires_grad_(True);logit=rt.student_forward(model,z)['logit'];g=torch.autograd.grad(logit.sum(),z)[0];grads.add_(g,alpha=(.5 if step in (0,50) else 1.)/50);time.sleep(.002)
   attrs[lo:hi]=(grads*d).detach().cpu().numpy()
   with torch.no_grad():diff[lo:hi]=rt.student_forward(model,xx)['logit'].cpu().numpy().astype(float)-fb
   if progress:progress(hi,n)
 residual=attrs.astype(float).sum((1,2))-diff;relative=np.abs(residual)/np.maximum(np.abs(diff),1e-6);return attrs,diff,residual,relative
def one(seed,stage):
 import torch
 gate();dv=device();original=loadmodel(oldspec('TA2',seed),dv)
 for p in original.parameters():p.requires_grad_(False)
 rt.seed_all(42);fresh=rt.build('odst').to(dv).eval();ix=np.random.default_rng(42).choice(591000,1024,replace=False);train=np.load(HP/'tensors/train_X.npy',mmap_mode='r');init=fresh.data_aware_initialize_from_batch(torch.as_tensor(np.array(train[ix]),device=dv));fresh.eval()
 model=copy.deepcopy(original);oldstate=original.state_dict();newstate=fresh.state_dict();prefix=('node_head.',) if stage=='head' else ('node_head.','attention.') if stage=='head_attention' else ('',);changed=[k for k in oldstate if k.startswith(prefix)];state={k:newstate[k] if k in changed else oldstate[k] for k in oldstate};model.load_state_dict(state);model.eval()
 for p in model.parameters():p.requires_grad_(False)
 dest=PRIVATE/f'Q4/seed{seed}/{stage}';dest.mkdir(parents=True,exist_ok=True);checkpoint=dest/'randomized_state.pt';torch.save({'model_state_dict':model.state_dict()},checkpoint)
 refs=np.zeros(8,float)
 with torch.inference_mode():
  for lo in range(0,len(train),512):
   out=rt.student_forward(model,torch.as_tensor(np.array(train[lo:lo+512]),device=dv));refs+=out['tree_outputs'].cpu().numpy().astype(float).sum(0);time.sleep(.002)
 refs/=len(train);baseline=np.array(read(P4P/'EXPLANATION_DEVELOPMENT_REFERENCES.json')['TA2_baseline_sequence'],np.float32)
 # Verify the final-logit-only implementation against the unchanged nine-output engine on DEVELOPMENT.
 sys.path.insert(0,str(R2/'explanation'));from phase3_engine import integrated_gradients
 class Forward:
  device=dv
  def __call__(self,x):
   out=rt.student_forward(model,x);return torch.cat((out['tree_outputs'],out['logit'][:,None]),1)
 dev=np.array(np.load(HP/'tensors/validation_X.npy',mmap_mode='r')[:2]);full=integrated_gradients(Forward(),dev,baseline);simple=final_ig(model,dev,baseline,dv);error=float(np.max(np.abs(full[0][:,-1]-simple[0])));assert error<1e-5
 freeze=dict(utc=utc(),seed=seed,stage=stage,randomization_seed=42,model_state_sha256=statehash(model),fresh_initialization_state_sha256=statehash(fresh),checkpoint_sha256=sha(checkpoint),original_checkpoint_sha256=oldspec('TA2',seed)['sha256'],changed_state_keys=changed,unchanged_state_keys=[k for k in state if k not in changed],original_constructor=True,data_aware_initialization=init,initialization_population='development TRAIN only',initialization_rows=1024,initialization_index_sha256=hashlib.sha256(ix.tobytes()).hexdigest(),tree_reference_population='development TRAIN only',tree_reference_windows=len(train),tree_reference_mean=refs,IG_baseline_population='frozen Phase4 development TRAIN',IG_50_interval_final_output_parity_error=error,engine_sha256=sha(R2/'explanation/phase3_engine.py'),code_sha256=sha(__file__))
 dump(dest/'FROZEN_BEFORE_EXPLANATION.json',freeze);lock=dest/'Q4_CONSUMED.json';assert not lock.exists();dump(lock,dict(utc=utc(),freeze_sha256=sha(dest/'FROZEN_BEFORE_EXPLANATION.json'),explanation_only=True))
 selection=np.array(read(EXPL/'HOLDOUT_SELECTION.json')['selected_bundle_row_indices']);x=np.load(P4P/'HOLDOUT_COHORT.npz')['X'][selection];outatt=[];outtree=[]
 with torch.inference_mode():
  for lo in range(0,len(x),512):
   out=rt.student_forward(model,torch.as_tensor(x[lo:lo+512],device=dv));outatt.append(out['attention_weights'].cpu().numpy());outtree.append(out['tree_outputs'].cpu().numpy());time.sleep(.002)
 attention=np.concatenate(outatt);tree=(np.concatenate(outtree).astype(float)-refs)/8.
 def progress(done,n):print('Q4_IG',seed,stage,done,n,flush=True)
 ig,diff,resid,rel=final_ig(model,x,baseline,dv,progress);np.savez_compressed(dest/'explanations.npz',ig=ig,attention=attention,tree_centred=tree,IG_difference=diff,IG_residual=resid,IG_relative=rel)
 origig=np.load(EXPL/f'ig_seed{seed}.npz')['ig'][:,-1].astype(float);inter=np.load(B6P/f'explanation/seed{seed}/cohort_intermediates.npz');origref=np.array(read(B6P/f'explanation/seed{seed}/TRAIN_TREE_REFERENCES.json')['tree_output_mean']);origatt=inter['attention'];origtree=(inter['tree']-origref)/8.
 if stage=='head':assert np.max(np.abs(attention-origatt))<5e-5
 values={'IG_signed_features':correlations(origig.sum(1),ig.astype(float).sum(1)),'IG_absolute_feature_shares':correlations(np.abs(origig).sum(1),np.abs(ig.astype(float)).sum(1)),'attention':correlations(origatt,attention),'tree_centred_contributions':correlations(origtree,tree)};rows=[]
 for component,v in values.items():
  valid=v[np.isfinite(v)];rows.append(dict(seed=seed,stage=stage,component=component,windows=len(v),valid_windows=len(valid),constant_or_undefined_windows=len(v)-len(valid),median_rho=float(np.median(valid)) if len(valid) else None,Q1_rho=float(np.quantile(valid,.25)) if len(valid) else None,Q3_rho=float(np.quantile(valid,.75)) if len(valid) else None))
 np.savez_compressed(dest/'correlations.npz',**values);dump(dest/'RESULT.json',dict(utc=utc(),seed=seed,stage=stage,status='ok',rows=rows,explanation_sha256=sha(dest/'explanations.npz'),correlations_sha256=sha(dest/'correlations.npz'),freeze=freeze,IG_relative_median=float(np.median(rel)),IG_relative_P95=float(np.quantile(rel,.95)),head_only_attention_max_abs_error=float(np.max(np.abs(attention-origatt))) if stage=='head' else None));print('Q4_STAGE_COMPLETE',seed,stage,flush=True)
def main():
 outcomes=[]
 for seed in OLD:
  for stage in ('head','head_attention','all'):
   dest=PRIVATE/f'Q4/seed{seed}/{stage}';result=dest/'RESULT.json'
   if result.exists():r=read(result)
   elif (dest/'Q4_CONSUMED.json').exists():r=dict(seed=seed,stage=stage,status='FAILED',reason='Previously consumed incomplete explanation; no repeat')
   else:
    status('Q4_RANDOMIZATION',seed=seed,randomized=stage)
    with (PRIVATE/f'logs/Q4_{seed}_{stage}.log').open('w',encoding='utf-8') as h:
     proc=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/'randomization8.py'),'--seed',str(seed),'--stage',stage],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
     try:rc=proc.wait(timeout=7200)
     except subprocess.TimeoutExpired:proc.kill();proc.wait();rc='TIMEOUT'
    r=read(result) if rc==0 and result.exists() else dict(seed=seed,stage=stage,status='TIMEOUT' if rc=='TIMEOUT' else 'FAILED',reason=f'Exit {rc}; no repeated consumed explanation')
   outcomes.append(r);dump(OUT/'Q4_OUTCOMES.json',outcomes)
 rows=[z for r in outcomes if r['status']=='ok' for z in r['rows']];pooled=[]
 for stage in ('head','head_attention','all'):
  for component in ('IG_signed_features','IG_absolute_feature_shares','attention','tree_centred_contributions'):
   arrays=[np.load(PRIVATE/f"Q4/seed{r['seed']}/{stage}/correlations.npz")[component] for r in outcomes if r['status']=='ok' and r['stage']==stage]
   if not arrays:continue
   v=np.concatenate(arrays);valid=v[np.isfinite(v)];pooled.append(dict(seed='pooled_three_seed_windows_descriptive',stage=stage,component=component,windows=len(v),valid_windows=len(valid),constant_or_undefined_windows=len(v)-len(valid),median_rho=float(np.median(valid)) if len(valid) else None,Q1_rho=float(np.quantile(valid,.25)) if len(valid) else None,Q3_rho=float(np.quantile(valid,.75)) if len(valid) else None))
 csv('Q4_RANDOMIZATION_CORRELATIONS.csv',rows+pooled);csv('Q4_IG_COMPLETENESS.csv',[{k:r[k] for k in ('seed','stage','IG_relative_median','IG_relative_P95')} for r in outcomes if r['status']=='ok']);dump(OUT/'Q4_RESULTS.json',dict(utc=utc(),outcomes=outcomes,correlations=rows+pooled,randomization_seed=42,no_cutoff_selected=True));status('Q4_COMPLETE',successful=sum(r['status']=='ok' for r in outcomes))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--seed',type=int);p.add_argument('--stage');a=p.parse_args();one(a.seed,a.stage) if a.seed else main()
