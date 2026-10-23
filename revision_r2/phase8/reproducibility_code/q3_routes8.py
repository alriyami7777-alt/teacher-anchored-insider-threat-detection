from common8 import *
from routing8 import Routes
import argparse,subprocess
from numba import njit,prange,set_num_threads
set_num_threads(2)
@njit(parallel=True)
def auc_boot(y,u,ends,counts):
 result=np.empty(len(counts))
 for b in prange(len(counts)):
  below=0.;gp=0.;gn=0.;pos=0.;neg=0.;area=0.;e=0
  for i in range(len(y)):
   w=float(counts[b,u[i]])
   if y[i]:gp+=w;pos+=w
   else:gn+=w;neg+=w
   if i==ends[e]:area+=gp*(below+.5*gn);below+=gn;gp=0.;gn=0.;e+=1
  result[b]=area/(pos*neg) if pos>0 and neg>0 else np.nan
 return result
def bootstrap_auc(y,p,u,c):
 order=np.argsort(p,kind='stable');sp=p[order];ends=np.r_[np.flatnonzero(np.diff(sp)),len(sp)-1];return auc_boot(np.asarray(y,np.int8)[order],u[order],ends,c)
def original_route(name,seed):
 import torch
 gate();sp=oldspec(name,seed);dv=device();model=loadmodel(sp,dv);x=np.load(P4P/'HOLDOUT_COHORT.npz')['X'];saved=probability(name,seed);routes=Routes(name,seed,len(x));error=0.
 lock=routes.path/'Q3_CONSUMED.json';assert not lock.exists();dump(lock,dict(utc=utc(),checkpoint_sha256=sp['sha256'],explanation_only=True))
 with torch.inference_mode():
  for lo in range(0,len(x),512):
   hi=min(lo+512,len(x));out=rt.student_forward(model,torch.as_tensor(x[lo:hi],device=dv));routes.add(lo,hi,out);error=max(error,float(np.max(np.abs(rt.probs(out['logit'].cpu().numpy())-saved[lo:hi]))));time.sleep(.002)
 assert error<5e-5;routes.finish(captured_during_single_new_Q1_scoring=False,original_saved_probability_max_abs_error=error,checkpoint_sha256=sp['sha256']);print('Q3_ORIGINAL_ROUTE_COMPLETE',name,seed,flush=True)
def main():
 from sklearn.metrics import roc_auc_score
 yy=np.array([1,0,1,0,0,1]);pp=np.array([.9,.9,.6,.4,.4,.1]);uu=np.array([0,1,0,1,2,2]);cc=np.array([[1,1,1],[2,0,1],[0,1,2]]);assert np.allclose(bootstrap_auc(yy,pp,uu,cc),[roc_auc_score(yy,pp,sample_weight=c[uu]) for c in cc])
 outcomes=[]
 for name in ('TA2','F00'):
  for seed in ALL:
   p=PRIVATE/f'routes/{name}_{seed}/ROUTING_COMPLETE.json'
   if not p.exists() and seed in OLD:
    status('Q3_ORIGINAL_ROUTING',model=name,seed=seed)
    with (PRIVATE/f'logs/Q3_{name}_{seed}.log').open('w',encoding='utf-8') as h:
     proc=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/'q3_routes8.py'),'--model',name,'--seed',str(seed)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
     try:rc=proc.wait(timeout=7200)
     except subprocess.TimeoutExpired:proc.kill();proc.wait();rc='TIMEOUT'
   else:rc=0
   outcomes.append(read(p)|dict(status='ok') if p.exists() and rc==0 else dict(model=name,seed=seed,status='TIMEOUT' if rc=='TIMEOUT' else 'UNAVAILABLE',reason='No complete routing artifact'));dump(OUT/'Q3_OUTCOMES.json',outcomes)
 m=metadata();c=np.load(P4P/'BOOTSTRAP_USER_MULTIPLICITIES.npy');leaves=[];depths=[];trees=[];counts=[]
 for r in outcomes:
  if r['status']!='ok':continue
  n,s=r['model'],r['seed'];path=PRIVATE/f'routes/{n}_{s}';assert sha(path/'tree_outputs.npy')==r['tree_outputs_sha256'];pred=np.load(path/'tree_outputs.npy',mmap_mode='r');cache=path/'AUC_bootstrap.npy'
  if cache.exists():bb=np.load(cache)
  else:
   status('Q3_TREE_AUC_BOOTSTRAP',model=n,seed=s);bb=np.array([bootstrap_auc(m['y'],pred[:,j],m['cluster'],c) for j in range(8)]);np.save(cache,bb)
  positive=negative=0
  for j in range(8):
   occ=np.array(r['occupancy_counts'][j]);p=occ/r['windows'];entropy=float(-(p[p>0]*np.log(p[p>0])).sum()/np.log(16));cirow=ci(bb[j],roc_auc_score(m['y'],pred[:,j]));above=cirow['ci95_low']>.5;below=cirow['ci95_high']<.5;positive+=above;negative+=below;trees.append(dict(model=n,seed=s,tree=j+1,layer=j//4+1,tree_within_layer=j%4+1,normalized_entropy=entropy,never_argmax_leaves=int((occ==0).sum()),AUC=cirow.pop('estimate'),**{k:v for k,v in cirow.items() if k!='CI_direction'},separation='above_chance' if above else 'reversed_below_chance' if below else 'compatible_with_chance'))
   for k in range(16):leaves.append(dict(model=n,seed=s,tree=j+1,leaf=k,windows=int(occ[k]),occupancy_share=float(p[k])))
   for k in range(4):depths.append(dict(model=n,seed=s,tree=j+1,depth=k+1,mean_right_branch_probability=float(r['mean_right_branch_probability'][j][k])))
  counts.append(dict(model=n,seed=s,trees=8,above_chance_trees=int(positive),reversed_separating_trees=int(negative),CI_excludes_chance_trees=int(positive+negative)))
 csv('Q3_LEAF_OCCUPANCY.csv',leaves);csv('Q3_ROUTING_BY_DEPTH.csv',depths);csv('Q3_TREE_AUC_ENTROPY.csv',trees);csv('Q3_SEPARATING_TREE_COUNTS.csv',counts);dump(OUT/'Q3_RESULTS.json',dict(utc=utc(),outcomes=outcomes,leaf_occupancy=leaves,routing_by_depth=depths,tree_metrics=trees,separating_tree_counts=counts,AUC_bootstrap_selfcheck=True,bootstrap_B=2000));status('Q3_COMPLETE',models=len(counts),trees=len(trees))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--model');p.add_argument('--seed',type=int);a=p.parse_args();original_route(a.model,a.seed) if a.model else main()
