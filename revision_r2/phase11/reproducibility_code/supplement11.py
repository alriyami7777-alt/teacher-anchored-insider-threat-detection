from common11 import *
def main():
 gate();paths=[P4/'MODELS_FROZEN_PHASE4.json',P5/'MODELS_AND_METHODS_FROZEN_PHASE5.json',P10/'TRAINING_CODE_FROZEN.json',P10/'ANALYSIS_CODE_FROZEN.json']
 for n in ('TA2','F00','XGBoost_40'):
  for s in SEEDS:
   receipt=P10/f'private/complete/within_{n}_{s}_r62.json';score=P10/f'private/scores/within_{n}_{s}_r62.npy';assert sha(score)==read(receipt)['score_sha256'];paths.extend((receipt,score))
 dump(OUT/'SUPPLEMENTAL_SOURCE_INTEGRITY.json',dict(utc=utc(),after_initial_posthoc=True,within_scores_verified_against_original_Phase10_score_receipts=True,Phase10_final_audit_sha256=sha(P10/'FINAL_AUDIT.json'),sources=[dict(path=str(p),sha256=sha(p)) for p in paths]));print('SUPPLEMENTAL_SOURCES_BOUND',len(paths),flush=True)
if __name__=='__main__':main()
