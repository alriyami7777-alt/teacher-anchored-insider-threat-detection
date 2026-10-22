"""Frozen-score paired user-cluster AP bootstrap, validation only; no inference.
Integer user multiplicities are exactly equivalent to concatenating whole-user
clusters, including repeated users. Score sorting/tie grouping is cached only
for efficiency. The first draw is verified against sklearn on explicit clusters.
"""
import pathlib,json,hashlib,re
import numpy as np
from sklearn.metrics import average_precision_score
HERE=pathlib.Path(__file__).resolve().parent
P=pathlib.Path(r'C:\PhD\07_Projects')
BASE=P/'cert-r52-locked-baselines/outputs/objective2/r52_locked_baselines'
TA=P/'teacher-anchored-insider-threat-detection-editor012/outputs/editor012_teacher_anchor_rescue/F11_DROPT'
VAL=P/'cert-r42-feasibility/data/processed/r5.2/tensors/r52_T20_s1_validation.npz'
SEEDS=[42,52,62]
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def main():
 needed=[VAL]+[BASE/f'xgboost_seed{s}/validation_probabilities.npz' for s in SEEDS]+[TA/f'seed{s}'/n for s in SEEDS for n in ['val_logits.npy','val_y.npy']]
 missing=[str(p) for p in needed if not p.is_file()]
 dest=HERE/'xgb40_vs_ta2_validation_bootstrap.json'
 if missing:dest.write_text(json.dumps({'status':'missing','missing':missing,'inference_run':False},indent=2));print('missing');return
 assert digest(VAL)=='5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c'
 manifest=json.loads((BASE/'r52_data_manifest.json').read_text())
 assert manifest['validation_tensor_sha256']==digest(VAL) and manifest['aggregation']['output_dim']==40
 with np.load(VAL,allow_pickle=True) as data:
  # Access metadata and y members only; X is never decompressed or materialized.
  y=np.asarray(data['y']).ravel().astype(int);users=np.asarray(data['user']).astype(str).ravel()
 mapping=hashlib.sha256('\n'.join(users.tolist()).encode()).hexdigest()
 assert mapping=='851385f9c926cf945b3c74b5c9442e3ccb94cf1d9dabb98106a29cbfea01c5c0'
 unique,inverse,counts=np.unique(users,return_inverse=True,return_counts=True)
 assert len(y)==64000 and y.sum()==728 and len(unique)==2000 and np.all(counts==32)
 scores=[];observed=[];input_hashes={str(VAL):digest(VAL)}
 for seed in SEEDS:
  with np.load(BASE/f'xgboost_seed{seed}/validation_probabilities.npz',allow_pickle=False) as z:
   assert np.array_equal(z['y_true'].ravel(),y);x=np.asarray(z['y_proba'],dtype=np.float64).ravel()
  assert np.array_equal(np.load(TA/f'seed{seed}/val_y.npy',allow_pickle=False).ravel(),y)
  logits=np.asarray(np.load(TA/f'seed{seed}/val_logits.npy',allow_pickle=False),dtype=np.float64).ravel()
  t=1/(1+np.exp(-np.clip(logits,-60,60)))
  assert len(x)==len(t)==len(y) and np.isfinite(x).all() and np.isfinite(t).all()
  ax=float(average_precision_score(y,x));at=float(average_precision_score(y,t))
  observed.append({'seed':seed,'PR_AUC_XGBoost_40':ax,'PR_AUC_TA2':at,'difference':ax-at});scores.extend([x,t])
  for p in [BASE/f'xgboost_seed{seed}/validation_probabilities.npz',TA/f'seed{seed}/val_y.npy',TA/f'seed{seed}/val_logits.npy']:input_hashes[str(p)]=digest(p)
 cached=[]
 for score in scores:
  order=np.argsort(-score,kind='stable');ends=np.r_[np.flatnonzero(np.diff(score[order])!=0),len(score)-1]
  cached.append((inverse[order],y[order],ends))
 def weighted_ap(cache,mult):
  ui,ys,ends=cache;w=mult[ui];tp=np.cumsum(w*ys)[ends];allw=np.cumsum(w)[ends]
  inc=np.diff(np.r_[0,tp]);precision=np.divide(tp,allw,out=np.zeros_like(tp,dtype=float),where=allw>0)
  return float(np.sum(inc*precision)/tp[-1])
 rng=np.random.default_rng(42);results=[];invalid=0
 for rep in range(2000):
  draw=rng.choice(len(unique),size=len(unique),replace=True);mult=np.bincount(draw,minlength=len(unique))
  positives=np.sum(mult[inverse]*y)
  if positives==0 or positives==np.sum(mult[inverse]):invalid+=1;continue
  aps=[weighted_ap(c,mult) for c in cached]
  if rep==0:
   groups=[np.flatnonzero(inverse==u) for u in range(len(unique))];ix=np.concatenate([groups[u] for u in draw])
   assert np.allclose(aps,[average_precision_score(y[ix],s[ix]) for s in scores],rtol=0,atol=1e-12)
  delta=np.asarray(aps[0::2])-np.asarray(aps[1::2]);results.append([*delta,float(delta.mean())])
  if (rep+1)%500==0:print('BOOTSTRAP',rep+1,flush=True)
 arr=np.asarray(results)
 def stats(i,point):return {'observed_difference':point,'bootstrap_mean_difference':float(arr[:,i].mean()),'ci95_percentile':np.quantile(arr[:,i],[.025,.975],method='linear').tolist()}
 result={'status':'COMPLETE','comparison':'PR-AUC(XGBoost_40) minus PR-AUC(TA2/F11_DROPT)','partition':'r5.2 VALIDATION only','metric':'sklearn noninterpolated average precision','seeds':SEEDS,'replicates_attempted':2000,'replicates_valid':len(arr),'single_class_draws':invalid,'rng':'numpy.default_rng(42), PCG64','sampling':'Resample 2000 users with replacement; retain all windows and multiplicity; use the same draw for both models and all seeds','seed_mean_statistic':'Mean of the three within-seed AP differences, not pooled-score AP','windows':64000,'positive_windows':728,'users':2000,'mapping_sha256':mapping,'alignment':'Same frozen validation tensor SHA256 in locked-baseline manifest and EDITOR-012; both labels match elementwise; no order-changing preprocessing in producer','observed_per_seed':observed,'per_seed':{str(s):stats(i,observed[i]['difference']) for i,s in enumerate(SEEDS)},'three_seed_mean':stats(3,float(np.mean([r['difference'] for r in observed]))),'checks':{'weighted_AP_matches_explicit_cluster_resampling_sklearn_first_draw':True,'inference_run':False,'training_run':False,'validation_feature_tensor_materialized':False},'input_sha256':input_hashes,'limitations':'Conditional on frozen fitted models and observed validation users/calendar; no model-retraining uncertainty. Historical validation is outcome-exposed.'}
 text=json.dumps(result,indent=2,allow_nan=False)
 assert not re.search(r'\b[A-Z]{3}[0-9]{4}\b',text)
 dest.write_text(text+'\n');print(json.dumps(result['three_seed_mean']))
if __name__=='__main__':main()
