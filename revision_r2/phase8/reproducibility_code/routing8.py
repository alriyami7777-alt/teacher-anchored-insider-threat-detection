from common8 import *
class Routes:
 def __init__(self,name,seed,n):
  self.name=name;self.seed=seed;self.n=n;self.count=np.zeros((8,16),np.int64);self.choices=np.zeros((8,4),float);self.path=PRIVATE/f'routes/{name}_{seed}';self.path.mkdir(parents=True,exist_ok=True);self.tree=np.lib.format.open_memmap(self.path/'tree_outputs.npy',mode='w+',dtype=np.float32,shape=(n,8));self.rows=0
 def add(self,lo,hi,out):
  probs=out['leaf_probs_all'].detach().cpu().numpy();choice=out['choices'].detach().cpu().numpy();tree=out['tree_outputs'].detach().cpu().numpy();assert probs.shape==(hi-lo,8,16) and choice.shape==(hi-lo,8,4);assert np.allclose(probs.sum(-1),1,atol=1e-5);leaf=np.argmax(probs,axis=-1)
  for j in range(8):self.count[j]+=np.bincount(leaf[:,j],minlength=16)
  self.choices+=choice.astype(float).sum(0);self.tree[lo:hi]=tree;self.rows+=hi-lo
 def finish(self,**extra):
  assert self.rows==self.n and np.all(self.count.sum(1)==self.n);self.tree.flush();dump(self.path/'ROUTING_COMPLETE.json',dict(utc=utc(),model=self.name,seed=self.seed,windows=self.n,occupancy_counts=self.count,mean_right_branch_probability=self.choices/self.n,tree_outputs_sha256=sha(self.path/'tree_outputs.npy'),layer_order='layer 1 trees 1-4, layer 2 trees 1-4; globally 1-8',argmax_tie='lowest leaf index',**extra))
