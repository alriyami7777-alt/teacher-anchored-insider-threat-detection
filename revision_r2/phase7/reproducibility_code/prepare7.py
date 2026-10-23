from common7 import *
def main():
 a=read(OUT/'AMENDMENT7_RECEIPT.json');pr=(R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md').read_bytes();assert hashlib.sha256(pr[:a['hashed_bytes']]).hexdigest()==a['sha256'];assert sha(R2/'phase6c/CHATGPT_PHASE6C_REPORT.md')==a['phase6c_report_sha256'];assert read(R2/'phase6c/FINAL_AUDIT.json')['all_checks_passed']
 PRIVATE.mkdir(exist_ok=True);(PRIVATE/'logs').mkdir(exist_ok=True)
 paths=[R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md',P4/'MODELS_FROZEN_PHASE4.json',P4P/'HOLDOUT_COHORT.npz',B6P/'cohorts/T20_metadata.npz',P5/'private/HOLDOUT_OPERATIONAL_METADATA.npz',P5/'C_INSIDER_SCENARIO_MAP.csv',EXPL/'HOLDOUT_SELECTION.json',EXPL/'cohort_pseudonyms.npz',P4P/'BOOTSTRAP_USER_MULTIPLICITIES.npy',HP/'DEVELOPMENT_DAILY_SCALER.json']
 for s in specs():
  assert sha(s['checkpoint'])==s['sha256'];paths.extend([Path(s['checkpoint']),P4P/f"scores/{s['model']}_{s['seed']}.npz"])
 for seed in SEEDS:paths.extend([EXPL/f'ig_seed{seed}.npz',B6P/f'explanation/seed{seed}/cohort_intermediates.npz',B6P/f'explanation/seed{seed}/TRAIN_TREE_REFERENCES.json'])
 for phase in ('phase6b','phase6c'):
  for n in (f'CHATGPT_{phase.upper()}_REPORT.md',f'{phase.upper()}_RESULTS.json','FINAL_AUDIT.json'):paths.append(R2/phase/n)
 for n in ('validation_X.npy','validation_X40.npy','validation_y.npy','validation_metadata.npz'):paths.append(HP/'tensors'/n)
 frozen={str(p):sha(p) for p in paths};dump(OUT/'SOURCE_INTEGRITY_MANIFEST.json',dict(utc=utc(),amendment7_sha256=a['sha256'],sources=frozen,models=specs(),r52_test_read=False,no_retraining=True,no_new_holdout_inference=True))
 # Read only the aggregated daily columns with the same explicit period/user predicate.
 import pyarrow.dataset as ds
 from datetime import date
 source=Path(r'C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\interval_level\r52_user_day_intervals_dense.parquet')
 users=(HP/'HOLDOUT_USERS.txt').read_text().splitlines();m,o=metadata();pseudo=['U_'+hashlib.sha256(u.encode()).hexdigest()[:10] for u in users];assert np.array_equal(pseudo,o['user'])
 pred=ds.field('user').isin(users)&(ds.field('interval_date')>=date(2010,1,2))&(ds.field('interval_date')<=date(2011,4,10))
 df=ds.dataset(source,format='parquet').to_table(columns=['user','interval_date',*FEATURES,'is_malicious_interval'],filter=pred).to_pandas();df['interval_date']=pd.to_datetime(df.interval_date);daily=np.empty((500,464,13),np.float64)
 for i,u in enumerate(users):
  g=df[df.user==u].sort_values('interval_date');assert np.array_equal(g.interval_date.to_numpy().astype('datetime64[D]'),o['calendar']);assert np.array_equal(g.is_malicious_interval,o['daily_y'][i]);daily[i]=g[FEATURES].to_numpy()
 assert len(df)==232000 and np.isfinite(daily).all();np.save(PRIVATE/'daily_features.npy',daily)
 dump(OUT/'PREPARATION_RECEIPT.json',dict(utc=utc(),daily_source=str(source),columns=['interval_date',*FEATURES,'is_malicious_interval'],explicit_date_predicate=['2010-01-02','2011-04-10'],rows=len(df),daily_features_sha256=sha(PRIVATE/'daily_features.npy'),all_daily_labels_match_Phase5=True,all_users_pseudonymised=True,raw_log_text_read=False,answer_payload_read=False,r52_test_read=False,original_sources=len(frozen)))
 status('PREPARATION_COMPLETE',sources=len(frozen),daily_rows=len(df))
if __name__=='__main__':main()
