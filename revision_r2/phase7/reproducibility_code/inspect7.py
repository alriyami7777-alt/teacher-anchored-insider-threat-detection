from pathlib import Path
import json,numpy as np
r=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision')
hp=r/'holdout/private'; ex=r/'explanation/holdout'
paths=[ex/'ig_seed42.npz',r/'phase6b/private/explanation/seed42/cohort_intermediates.npz',r/'phase5/private/HOLDOUT_OPERATIONAL_METADATA.npz',hp/'checkpoints_parity_v2/XGBoost_40/seed42/development_validation_probabilities.npz']
for p in paths:
 print('ARRAY_SCHEMA',str(p))
 if p.exists():
  z=np.load(p,allow_pickle=False);print({k:dict(shape=z[k].shape,dtype=str(z[k].dtype)) for k in z.files})
 else:print('MISSING')
f=json.loads((r/'holdout/phase4/MODELS_FROZEN_PHASE4.json').read_text())
for a in f['models']:
 if a['model'] in ('TA2','L1','F00','XGBoost_40','LightGBM_40','Transformer'):print('SPEC',json.dumps({k:a.get(k) for k in ('model','seed','checkpoint','sha256','threshold','config')}))
print('SAVED_VALIDATION', [str(p) for p in hp.glob('**/*validation*prob*')])
print('OP_METADATA', [str(p) for p in (r/'phase5').glob('**/*OPERATIONAL_METADATA*')])
