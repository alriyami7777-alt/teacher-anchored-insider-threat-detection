from common6b import *
import pandas as pd
def main():
 from PIL import Image
 checks={}
 pr=(H/'PREREGISTRATION_R2_HOLDOUT.md').read_bytes();a=read(OUT/'AMENDMENT5_RECEIPT.json');checks['preserved_preregistration_prefix']=hashlib.sha256(pr[:a['previous_prefix_bytes']]).hexdigest()==a['previous_prefix_sha256'];checks['amendment5_hash']=hashlib.sha256(pr[:a['hashed_bytes']]).hexdigest()==a['sha256'];pos=pr.index(b'\n\nAmendment 5 clarification SHA-256 receipt:');checks['clarification_hash']=hashlib.sha256(pr[:pos]).hexdigest()=='5b932a5ec7fec60d8984dfa31a061a09563491204946140c05b4aafc6bd0c0f2';checks['preregistration_final_hash']=sha(H/'PREREGISTRATION_R2_HOLDOUT.md')==a['preregistration_final_sha256']
 f=read(OUT/'MODELS_FROZEN_PHASE6B.json');checks['all_checkpoints_unchanged']=all(sha(r['checkpoint'])==r['sha256'] for r in f['models']);checks['frozen_scoring_sources_unchanged']=all(sha(CODE/n)==h for n,h in f['scoring_code'].items());checks['source_model_development_preflight']=len(f['development_preflight'])==27 and all(r['finite'] for r in f['development_preflight'])
 original=read(P4/'MODELS_FROZEN_PHASE4.json');checks['all_original_Phase4_checkpoints_unchanged']=all(sha(r['checkpoint'])==r['sha256'] for r in original['models'])
 checks['all_original_Phase4_sources_unchanged']=all(sha(ROOT/'phase4'/n)==h for n,h in original['files'].items())
 done=read(OUT/'SCORING_COMPLETE.json');checks['all_scoring_outcomes_accounted']=len(done['outcomes'])==len(f['models'])+30
 good=[r for r in done['outcomes'] if r['state']=='COMPLETE'];checks['predictions_and_exclusive_receipts']=all(sha(PRIVATE/f"scores/{r['model']}_{r['seed']}_{r['condition']}.npy")==r['prediction_sha256'] and read(PRIVATE/f"score_receipts/{r['model']}_{r['seed']}_{r['condition']}.json")['state']=='COMPLETE' for r in good)
 h6=read(OUT/'H6_FROZEN.json');checks['H6_sources_unchanged']=all(sha(CODE/n)==h for n,h in h6['code'].items()) and sha(ROOT/'src/objective3_attention_faithfulness.py')==h6['masked_softmax_helper_sha256'];checks['frozen_explanation_cohort_unchanged']=sha(EXPL/'HOLDOUT_SELECTION.json')==h6['selection_sha256'];checks['inherited_feature_arrays_unchanged']=all(sha(EXPL/f'TA2_seed{s}_feature_interventions.npz')==h6['feature_arrays'][str(s)] for s in SEEDS)
 result=read(OUT/'PHASE6B_RESULTS.json');checks['full_840_test_Holm_family']=len(result['H1_H5_contrasts'])==840 and all(r['Holm_family_size']==840 for r in result['H1_H5_contrasts']);checks['separate_H6_families']=result['H6']['level_family_sizes']==dict(temporal=72,feature=162,tree=162);checks['feature_reuse_estimate_and_CI_parity']=len(result['H6']['feature_reuse_numerical_parity'])==108 and all(r['max_abs_error']<1e-10 for r in result['H6']['feature_reuse_numerical_parity'])
 checks['all_successful_training_and_teacher_checkpoints_unchanged']=all(sha(r['checkpoint'])==r['checkpoint_sha256'] for r in result['training_log'] if r['status']=='ok');checks['pre_scoring_H5_teacher_verification']=len(f['H5_own_teacher_verification'])==12
 development=read(OUT/'DEVELOPMENT_VERIFICATION.json');checks['development_and_orderfree_inputs_unchanged']=all(sha(HP/f"tensors/{r['split']}_X.npy")==r['source_X_sha256'] and sha(PRIVATE/f"data/orderfree/{r['split']}_X.npy")==r['orderfree_X_sha256'] for r in development['checks'])
 checks['insider_denominator_25']=all(r['total_insiders']==25 and 0<=r['detected_insiders']<=25 for r in result['insider_recall']);checks['all_five_views']=set(r['view'] for r in result['models'])=={'pooled_completed','train_completed','validation_completed','pooled_offset0','pooled_endpoint'}
 metadata=[]
 for t in (10,20,30):
  z=np.load(PRIVATE/f'cohorts/T{t}_metadata.npz');metadata.append(dict(length=t,windows=len(z['y']),positive_windows=int(z['y'].sum()),users=len(np.unique(z['user'])),max_end_date=str(z['end_date'].max()),min_end_date=str(z['end_date'].min()),positive_users=len(np.unique(z['user'][z['y']==1]))));assert set(z['partition'])=={'train','validation'} and str(z['end_date'].max())=='2011-04-10'
 checks['permitted_HOLDOUT_periods_only']=True;checks['r52_test_sealed']=result['r52_test_read']==False and result['holdout_used_for_training_selection_scaling_thresholds']==False
 figs={}
 for letter in 'abcde':
  png=next(OUT.glob(f'figure_{letter}_*.png'));csvpath=png.with_suffix('.csv');im=Image.open(png);dpi=im.info.get('dpi',(0,0));figs[png.name]=dict(size=im.size,dpi=dpi,sha256=sha(png),CSV_sha256=sha(csvpath));assert min(dpi)>299 and len(pd.read_csv(csvpath))>0
 checks['five_300dpi_figures_with_CSV']=len(figs)==5
 report=OUT/'CHATGPT_PHASE6B_REPORT.md';checks['report_marker']=report.read_text(encoding='utf-8').rstrip().endswith('PHASE6B_COMPLETE');checks['report_hash']=sha(report)==result['report_sha256'];checks['all_outcomes_in_report']=('No training, scoring or explanation run was skipped, failed or timed out.' in report.read_text(encoding='utf-8'))==(not result['failures'])
 # Match only real raw IDs from the private membership lists, never a broad regular expression.
 raw=set(HP.joinpath('HOLDOUT_USERS.txt').read_text().split())|set(devusers());leaks=[]
 for p in OUT.iterdir():
  if p.suffix not in ('.md','.csv','.json'):continue
  content=p.read_text(encoding='utf-8')
  for identifier in raw:
   if identifier in content:leaks.append(p.name);break
 checks['no_raw_CERT_user_ids_in_public_outputs']=not leaks
 audit=dict(utc=utc(),all_checks_passed=all(checks.values()),checks=checks,cohorts=metadata,figures=figs,raw_id_leak_files=leaks,successful_scoring_passes=len(good),planned_scoring_jobs=len(done['outcomes']),report_sha256=sha(report),result_sha256=sha(OUT/'PHASE6B_RESULTS.json'),r52_test_read=False)
 dump(OUT/'FINAL_AUDIT.json',audit);assert audit['all_checks_passed'],checks;status('PHASE6B_COMPLETE',all_checks_passed=True,scoring_jobs=len(done['outcomes']))
if __name__=='__main__':main()
