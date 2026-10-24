from common10 import *
gate();dest=OUT/'EVALUATION_INPUTS_FROZEN.json';assert not dest.exists();assert not list((P/'complete').glob('pooled_*'))
paths=[HP/'phase4/HOLDOUT_COHORT.npz',R2/'phase6b/private/cohorts/T20_metadata.npz',P5/'private/HOLDOUT_OPERATIONAL_METADATA.npz',HP/'DEVELOPMENT_USERS.txt',HP/'HOLDOUT_USERS.txt',HP/'DEVELOPMENT_DAILY_SCALER.json']
dump(dest,dict(utc=utc(),before_any_new_pooled_heldout_scoring=True,read_for_hash_only=True,sources=[dict(path=str(p),sha256=sha(p)) for p in paths]));print('EVALUATION_INPUTS_FROZEN',flush=True)
