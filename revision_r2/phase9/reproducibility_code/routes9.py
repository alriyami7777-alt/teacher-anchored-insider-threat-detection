from common9 import *
from stats9 import *
def response(choice,leaf):
 codes=np.array([[(i>>(3-d))&1 for d in range(4)] for i in range(16)]);c=choice[:,:,None,:];lp=np.exp((codes[None,None]*np.log(np.clip(c,1e-8,1-1e-8))+(1-codes[None,None])*np.log(np.clip(1-c,1e-8,1))).sum(-1));return np.einsum('btl,tl->bt',lp,leaf)
def main():
 import torch
 gate();dv=device();selection=np.array(read(EXPL/'HOLDOUT_SELECTION.json')['selected_bundle_row_indices']);x=np.load(P4P/'HOLDOUT_COHORT.npz')['X'][selection];m=holdmeta();u=m['cluster'][selection];y=m['y'][selection];w=counts(500);rows=[];points=[];stored={}
 for s in SEEDS:
  model=loadmodel(oldspec('TA2',s),dv);leaf=np.concatenate([l.leaf_responses.detach().cpu().numpy()[:,:,0] for l in model.node_head.layers]);choice=[];trees=[];logits=[];consume(f'L4_routes_{s}',checkpoint_sha256=oldspec('TA2',s)['sha256'])
  with torch.no_grad():
   for lo in range(0,len(x),256):out=rt.student_forward(model,torch.as_tensor(x[lo:lo+256],device=dv));choice.append(out['choices'].cpu().numpy());trees.append(out['tree_outputs'].cpu().numpy());logits.append(out['logit'].cpu().numpy());time.sleep(.002)
  c=np.concatenate(choice).astype(float);tree=np.concatenate(trees);logit=np.concatenate(logits);base=response(c,leaf);assert np.max(np.abs(base-tree))<2e-5;assert np.max(np.abs(rt.probs(logit)-original('TA2',s)[selection]))<5e-5;sign=np.where(logit>=0,1.,-1.);importance=np.empty((len(x),8,4))
  for t in range(8):
   for d in range(4):cc=c.copy();cc[:,t,d]=.5;importance[:,t,d]=sign*(base[:,t]-response(cc,leaf)[:,t])/8
  order=np.argsort(-importance.reshape(len(x),32),axis=1,kind='stable');rng=np.random.default_rng(42);pred=rt.probs(logit)>=oldspec('TA2',s)['threshold'];strata={'all':np.ones(len(x),bool),'malicious':y==1,'benign':y==0,'TP':(y==1)&pred,'FN':(y==1)&~pred,'FP':(y==0)&pred,'TN':(y==0)&~pred}
  for k in (1,2,3):
   top=c.copy();random=[];ix=order[:,:k];b=np.arange(len(x))[:,None];top[b,ix//4,ix%4]=1-top[b,ix//4,ix%4];top_effect=sign*(base-response(top,leaf)).sum(1)/8
   for trial in range(25):
    cc=c.copy()
    for i in range(len(x)):
     ts,ns=np.unique(ix[i]//4,return_counts=True)
     for t,n in zip(ts,ns):ds=rng.choice(4,n,replace=False);cc[i,t,ds]=1-cc[i,t,ds]
    random.append(sign*(base-response(cc,leaf)).sum(1)/8)
   random_effect=np.mean(random,0);delta=top_effect-random_effect;stored[f'{s}_k{k}_delta']=delta;stored[f'{s}_k{k}_top']=top_effect;stored[f'{s}_k{k}_random']=random_effect
   for st,mask in strata.items():
    if not mask.any():r=dict(seed=s,k=k,stratum=st,windows=0,status='unavailable_empty_stratum',estimate=None,p_unadjusted=1);rep=np.full(2000,np.nan)
    else:
     cw=w[:,u[mask]];den=cw.sum(1);rep=np.divide(cw@delta[mask],den,out=np.full(2000,np.nan),where=den>0);r=dict(seed=s,k=k,stratum=st,windows=int(mask.sum()),status='ok',mean_top_effect=float(top_effect[mask].mean()),mean_random_effect=float(random_effect[mask].mean()),**interval(rep,delta[mask].mean()))
    stored[f'{s}_k{k}_{st}_boot']=rep;rows.append(r)
  points.append(dict(seed=s,route_probability_parity_error=float(np.max(np.abs(base-tree))),prediction_parity_error=float(np.max(np.abs(rt.probs(logit)-original('TA2',s)[selection]))),selected_nonpositive_contribution_fraction=float((np.take_along_axis(importance.reshape(len(x),32),order[:,:3],1)<=0).mean())))
 for k in (1,2,3):
  for st in ('all','malicious','benign','TP','FN','FP','TN'):
   rs=[r for r in rows if r['k']==k and r['stratum']==st and r['seed'] in SEEDS];valid=all(r['status']=='ok' for r in rs);a=np.mean([stored[f'{s}_k{k}_{st}_boot'] for s in SEEDS],0);rows.append(dict(seed='mean',k=k,stratum=st,status='ok' if valid else 'unavailable_empty_stratum',**interval(a,np.mean([r['estimate'] for r in rs]) if valid else np.nan)))
 holm(rows,'L4',84);np.savez_compressed(PRIVATE/'L4_INTERVENTIONS.npz',**stored);csv('L4_ROUTE_INTERVENTIONS.csv',rows);dump(OUT/'L4_RESULTS.json',dict(utc=utc(),contrasts=rows,parity=points,Holm_family_size=84,random_trials=25,downstream_feature_computations_held_fixed=True))
if __name__=='__main__':main()
