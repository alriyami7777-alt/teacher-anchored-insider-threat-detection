from common9 import *
def main():
 gate();paths=[]
 for n in ('TA2','F00','XGBoost_40'):
  for s in ALL:
   paths.append(Path(oldspec(n,s)['checkpoint']));paths.append(P4P/f'scores/{n}_{s}.npz' if s in SEEDS else P8/f'private/scores/{n}_{s}.npy')
 for s in SEEDS:paths +=[EXPL/f'ig_seed{s}.npz',P8/f'private/Q4/seed{s}/all/randomized_state.pt',P8/f'private/Q4/seed{s}/all/explanations.npz',P8/f'private/Q4/seed{s}/all/FROZEN_BEFORE_EXPLANATION.json',P8/f'private/Q5/r6.1_{s}.npy']
 f=read(P5/'MODELS_AND_METHODS_FROZEN_PHASE5.json')
 for release in ('r5.1','r6.1','r6.2'):
  folder=Path(f['bundles'][release]['folder']);paths +=[folder/'scaled_dense_daily.npy',folder/'completed_window_labels.npy']+[folder/n for n in (('window_user_index.npy','window_start_index.npy') if release=='r6.1' else ('window_index.npy',))]
  if release!='r6.1':paths +=[P5/f'private/transfer/{release}/development_{n}_{s}.npy' for n in MODELS for s in SEEDS]
 p=OUT/'ADDITIONAL_SOURCE_INTEGRITY_MANIFEST.json';assert not p.exists();dump(p,dict(utc=utc(),sources={str(p):sha(p) for p in paths},all_target_baselines_frozen_before_new_conditions=True));print('ADDITIONAL_SOURCES_FROZEN',len(set(paths)),flush=True)
if __name__=='__main__':main()
