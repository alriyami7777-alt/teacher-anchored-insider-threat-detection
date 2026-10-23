from common8 import *
def main():
 gate();PRIVATE.mkdir(exist_ok=True);(PRIVATE/'logs').mkdir(exist_ok=True)
 paths=[H/'PREREGISTRATION_R2_HOLDOUT.md',ROOT/'phase2_runtime.py',ROOT/'producing_model/prototype_v3_node/architecture.py',ROOT/'producing_model/prototype_v3_node/odst.py',HP/'teacher_cache/bi_train_ensemble_logits.npy',P4/'MODELS_FROZEN_PHASE4.json',P4/'SCORING_COMPLETE.json',P4P/'HOLDOUT_COHORT.npz',P4P/'BOOTSTRAP_USER_MULTIPLICITIES.npy',HP/'DEVELOPMENT_DAILY_SCALER.json',HP/'DEVELOPMENT_USERS.txt',HP/'HOLDOUT_USERS.txt',EXPL/'HOLDOUT_SELECTION.json',EXPL/'cohort_pseudonyms.npz',P4P/'EXPLANATION_DEVELOPMENT_REFERENCES.json',R2/'phase7/CHATGPT_PHASE7_REPORT.md',R2/'phase7/PHASE7_RESULTS.json',R2/'phase7/FINAL_AUDIT.json']
 for n in ('AL_PRECURSOR','T-OPT','TA2','F00','uniTA2','L1','XGBoost_40'):
  for s in OLD:
   if n=='AL_PRECURSOR':p=HP/f'checkpoints/{n}/seed{s}/best.pt'
   else:p=Path(oldspec(n,s)['checkpoint'])
   paths.append(p)
   if n in ('TA2','F00','uniTA2','L1','XGBoost_40'):paths.append(P4P/f'scores/{n}_{s}.npz')
 for s in OLD:paths.extend([EXPL/f'ig_seed{s}.npz',B6P/f'explanation/seed{s}/cohort_intermediates.npz',B6P/f'explanation/seed{s}/TRAIN_TREE_REFERENCES.json'])
 for part in ('train','validation'):
  for suf in ('X.npy','X40.npy','y.npy','metadata.npz'):paths.append(HP/f'tensors/{part}_{suf}')
 hashes={str(p):sha(p) for p in paths};cache=np.load(HP/'teacher_cache/bi_train_ensemble_logits.npy');assert cache.shape==(591000,) and np.isfinite(cache).all()
 dump(OUT/'SOURCE_INTEGRITY_MANIFEST.json',dict(utc=utc(),sources=hashes,original_consensus=dict(seeds=OLD,teachers=[oldspec('T-OPT',s) for s in OLD],cache_sha256=sha(HP/'teacher_cache/bi_train_ensemble_logits.npy'),training_windows=len(cache)),amendment8=read(OUT/'AMENDMENT8_RECEIPT.json'),r52_test_read=False))
 dump(OUT/'TRAINING_CODE_FROZEN.json',dict(utc=utc(),code={p.name:sha(p) for p in CODE.glob('*.py')},runtime_sha256=sha(ROOT/'phase2_runtime.py'),new_seeds=NEW,recipes=[rt.recipe(n,72,bundle()) for n in ('AL_PRECURSOR','T-OPT','F00','TA2','XGBoost_40')],consensus_seeds=OLD))
 status('PREPARATION_COMPLETE',source_files=len(hashes))
if __name__=='__main__':main()
