from common9 import *
import argparse
def rebuild(raw,counts,mask):
 z=raw.copy();z[:,:,1:6]=np.where(mask[:,:,None],counts,z[:,:,1:6]);total=counts.sum(-1);z[:,:,0]=np.where(mask,total,z[:,:,0]);z[:,:,7:12]=np.where(mask[:,:,None],counts>0,z[:,:,7:12]);z[:,:,12]=np.where(mask,total>0,z[:,:,12]);ratio=np.divide(total,raw[:,:,0],out=np.zeros_like(total),where=raw[:,:,0]>0);z[:,:,6]=np.where(mask,raw[:,:,6]*ratio,z[:,:,6]);return z
def tensor_rebuild(raw,c,mask):
 import torch
 z=raw.clone();z[:,:,1:6]=torch.where(mask[:,:,None],c,raw[:,:,1:6]);total=c.sum(-1);z[:,:,0]=torch.where(mask,total,raw[:,:,0]);z[:,:,7:12]=torch.where(mask[:,:,None],(c>0).to(raw.dtype),raw[:,:,7:12]);z[:,:,12]=torch.where(mask,(total>0).to(raw.dtype),raw[:,:,12]);ratio=total/raw[:,:,0].clamp_min(1e-20);z[:,:,6]=torch.where(mask,raw[:,:,6]*ratio,raw[:,:,6]);return z
def main(s,eps,attack):
 import torch
 gate();dv=device();m=holdmeta();o=operational();idx=np.flatnonzero(m['y']==1);x=np.load(P4P/'HOLDOUT_COHORT.npz')['X'][idx];s1=scaler()['development'];mu=np.array(s1['mean']);sd=np.array(s1['scale']);day=((m['end_date'][idx].astype('datetime64[D]')-o['calendar'][0].astype('datetime64[D]')).astype(int)[:,None]-19+np.arange(20));raw=np.load(R2/'phase7/private/daily_features.npy',mmap_mode='r')[m['cluster'][idx,None],day].copy();original_counts=raw[:,:,1:6].copy();assert np.all(original_counts>=0) and np.array_equal(original_counts,np.rint(original_counts));assert np.max(np.abs(((raw-mu)/sd).astype(np.float32)-x))<1e-5;mask=o['daily_y'][m['cluster'][idx,None],day].astype(bool);key=f'L7_{attack}_{eps:.2f}_{s}';consume(key,seed=s,epsilon=eps,attack=attack,steps=20,query_limit=200);trace=loadmodel(oldspec('TA2',s),dv);xgb=loadmodel(oldspec('XGBoost_40',s),dv);lower=original_counts*(1-eps);c=original_counts.copy();queries=np.zeros(len(x),int);query_scores=None
 if attack=='uniform':c=np.where(mask[:,:,None],lower,c)
 elif attack=='source_targeted':
  target=np.array(read(OUT/'L7_MALICIOUS_SOURCE_TARGETS_FROZEN.json')['source_index_by_holdout_cluster'])
  for i,ui in enumerate(m['cluster'][idx]):c[i,:,target[ui]]=np.where(mask[i],lower[i,:,target[ui]],c[i,:,target[ui]])
 elif attack=='TRACE_PGD':
  for lo in range(0,len(x),128):
   hi=min(lo+128,len(x));rr=torch.tensor(raw[lo:hi],dtype=torch.float32,device=dv);orig=torch.tensor(original_counts[lo:hi],dtype=torch.float32,device=dv);low=orig*(1-eps);mm=torch.tensor(mask[lo:hi],device=dv);cc=orig.clone();mt=torch.tensor(mu,dtype=torch.float32,device=dv);st=torch.tensor(sd,dtype=torch.float32,device=dv)
   with torch.backends.cudnn.flags(enabled=False):
    for step in range(20):
     cc=cc.detach().requires_grad_(True);zz=(tensor_rebuild(rr,cc,mm)-mt)/st;g=torch.autograd.grad(rt.student_forward(trace,zz)['logit'].sum(),cc)[0];cc=torch.maximum(low,torch.minimum(orig,cc-eps*orig/10*g.sign()));cc=torch.where(mm[:,:,None],cc,orig);time.sleep(.002)
   c[lo:hi]=cc.detach().cpu().numpy();queries[lo:hi]=20
 elif attack=='XGB_greedy':
  query_scores=np.empty(len(x))
  for i in range(len(x)):
   current=c[i].copy();xx=x[i:i+1];best=float(predict(xgb,'XGBoost_40',xx,dv)[0]);q=1;active=[(t,j) for t in range(20) if mask[i,t] for j in range(5) if original_counts[i,t,j]>0]
   while q<200:
    candidates=[]
    for t,j in active:
     if current[t,j]<=lower[i,t,j]+1e-10:continue
     z=current.copy();z[t,j]=max(lower[i,t,j],z[t,j]-eps*original_counts[i,t,j]/10);candidates.append(z)
     if len(candidates)>=200-q:break
    if not candidates:break
    ca=np.array(candidates);rr=np.repeat(raw[i:i+1],len(ca),0);mm=np.repeat(mask[i:i+1],len(ca),0);zz=((rebuild(rr,ca,mm)-mu)/sd).astype(np.float32);zz[~mm]=np.repeat(x[i:i+1],len(ca),0)[~mm];scores=predict(xgb,'XGBoost_40',zz,dv);q+=len(ca);j=int(np.argmin(scores))
    if scores[j]>=best:break
    best=float(scores[j]);current=ca[j]
   c[i]=current;queries[i]=q;query_scores[i]=best
 else:raise ValueError(attack)
 c=np.maximum(lower,np.minimum(original_counts,c));assert np.all(c>=lower) and np.all(c<=original_counts) and np.all(c>=0);z=((rebuild(raw,c,mask)-mu)/sd).astype(np.float32);z[~mask]=x[~mask];assert np.array_equal(z[~mask],x[~mask]);scores={}
 for n,model in (('TA2',trace),('XGBoost_40',xgb)):
  a=query_scores if n=='XGBoost_40' and query_scores is not None else np.concatenate([predict(model,n,z[lo:lo+256],dv) for lo in range(0,len(z),256)]);p=original(n,s).copy();p[idx]=a;scores[n]=p;np.save(PRIVATE/f'scores/{key}_{n}.npy',p)
 np.savez_compressed(PRIVATE/f'{key}_PERTURBATIONS.npz',counts=c,source_row=idx,queries=queries);dump(PRIVATE/f'complete/{key}.json',dict(utc=utc(),key=key,state='COMPLETE',attack=attack,seed=s,epsilon=eps,malicious_windows=len(idx),normal_days_unchanged=True,bounds_passed=True,max_queries=int(queries.max()),score_hashes={n:sha(PRIVATE/f'scores/{key}_{n}.npy') for n in scores},perturbations_sha256=sha(PRIVATE/f'{key}_PERTURBATIONS.npz'),attacker='aggregate continuous count thinning; proportional duration; malicious-day source counts'))
 print('ATTACK_COMPLETE',key,flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--seed',type=int);p.add_argument('--epsilon',type=float);p.add_argument('--attack');a=p.parse_args();main(a.seed,a.epsilon,a.attack)
