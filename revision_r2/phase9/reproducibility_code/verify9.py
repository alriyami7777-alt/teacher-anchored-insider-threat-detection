from common9 import *
from stats9 import holm
def main():
 from PIL import Image
 r=read(OUT/'PHASE9_RESULTS.json');checks={};details={};a=r['amendment9'];c=r['clarification'];pr=(R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md').read_bytes();src=read(OUT/'SOURCE_INTEGRITY_MANIFEST.json');tf=read(OUT/'TRAINING_CODE_FROZEN.json');af=read(OUT/'ANALYSIS_CODE_FROZEN.json');sf=read(OUT/'SUPPLEMENTARY_METHODS_FROZEN.json');train=r['training'];tests=r['tests']
 checks['Phase8_complete_report_preserved']=sha(P8/'CHATGPT_PHASE8_REPORT.md')==a['phase8_report_sha256'] and read(P8/'FINAL_AUDIT.json')['all_checks_passed']
 checks['Amendment9_prefix_and_previous_prefix_hashes']=hashlib.sha256(pr[:a['hashed_bytes']]).hexdigest()==a['sha256'] and hashlib.sha256(pr[:a['previous_bytes']]).hexdigest()==a['previous_sha256']
 checks['clarification_hash_chain_and_final_preregistration']=hashlib.sha256(pr[:c['hashed_bytes']]).hexdigest()==c['sha256'] and hashlib.sha256(pr[:c['previous_bytes']]).hexdigest()==c['previous_sha256'] and c['previous_sha256']==a['preregistration_final_sha256'] and sha(R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md')==c['preregistration_final_sha256']
 checks['amendment_precedes_all_preparation_and_training']=a['utc']<src['utc']<tf['utc'] and all(a['utc']<read(p)['utc'] for p in (PRIVATE/'data').glob('*/manifest.json'))
 checks['all_original_source_bytes_unchanged']=all(sha(p)==h for p,h in src['sources'].items())
 extra=read(OUT/'ADDITIONAL_SOURCE_INTEGRITY_MANIFEST.json');checks['all_eight_seed_scores_transfer_inputs_and_explanations_preserved']=all(sha(p)==h for p,h in extra['sources'].items())
 checks['training_runtime_and_four_initial_files_frozen']=sha(ROOT/'phase2_runtime.py')==tf['runtime_sha256'] and all(sha(CODE/k)==h for k,h in tf['code'].items())
 checks['target_analysis_code_and_dependencies_frozen']=all(sha(CODE/k)==h for k,h in af['code'].items()) and all(sha(p)==h for p,h in af['dependencies'].items())
 checks['clarification_preserves_initial_method_version']=sha(OUT/'ANALYSIS_CODE_FROZEN_INITIAL.json')==af['supersedes_sha256'] and sha(OUT/'AMENDMENT9_CLARIFICATION_RECEIPT.json')==af['clarification_receipt_sha256']
 checks['source_target_method_and_choices_frozen']=all(sha(CODE/k)==h for k,h in sf['code'].items()) and sha(OUT/'L7_MALICIOUS_SOURCE_TARGETS_FROZEN.json')==sf['malicious_source_targets_sha256']
 sourceaudit=read(OUT/'MALICIOUS_SOURCE_COUNT_AUDIT.json');checks['actual_malicious_source_counts_match_daily_labels_all25']=sourceaudit['all_checks_passed'] and sourceaudit['target_choice_sha256']==sha(OUT/'L7_MALICIOUS_SOURCE_TARGETS_FROZEN.json')
 rawfix=read(OUT/'PRE_SCORING_RAW_COUNT_PRECISION_RECEIPT.json');bdprecision=read(OUT/'BACKDOOR_RAW_COUNT_PRECISION_RECEIPT.json');checks['raw_count_precision_corrections_preserve_method_history']=sha(OUT/'ANALYSIS_CODE_FROZEN_PRE_RAW_COUNT_FIX.json')==af['raw_count_fix_previous_manifest_sha256'] and sha(OUT/'PRE_SCORING_RAW_COUNT_PRECISION_RECEIPT.json')==af['raw_count_fix_receipt_sha256'] and sha(OUT/'ANALYSIS_CODE_FROZEN_PRE_TRIGGER_COUNT_FIX.json')==af['trigger_count_fix_previous_manifest_sha256'] and sha(OUT/'BACKDOOR_RAW_COUNT_PRECISION_RECEIPT.json')==af['trigger_count_fix_receipt_sha256'] and sha(rawfix['raw_daily_source'])==rawfix['raw_daily_sha256'] and sha(CODE/'trigger_precision9.py')==bdprecision['trigger_code_sha256']
 checks['all_development_numerical_checks_pass']=read(OUT/'DEVELOPMENT_NUMERICAL_VERIFICATION.json')['all_checks_passed']
 checks['development_data_disjoint_users_and_exact_poison_transforms']=read(OUT/'DEVELOPMENT_DATA_AUDIT.json')['all_checks_passed']
 checks['all60_training_runs_accounted_for']=len(train)==60 and {(z['condition'],z['model'],z['seed']) for z in train}=={(c,n,s) for c in CONFIGS for n in ('AL_PRECURSOR','T-OPT','TA2','XGBoost_40') for s in SEEDS}
 checks['successful_checkpoints_preserved']=all(sha(z['checkpoint'])==z['sha256'] for z in train if z['status']=='ok')
 checks['TRAIN_only_and_clean_VALIDATION_selection']=all(z['development_only'] and z['clean_validation_selection'] for z in train if z['status']=='ok')
 checks['condition_specific_matched_teachers_and_consensus']=all(z['matched_teacher_seed']==z['seed'] and z['consensus_seeds']==list(SEEDS) and z['consensus_condition']==z['condition'] for z in train if z['model']=='TA2' and z['status']=='ok')
 import torch
 torch.set_num_threads(2);consensusok=True;consensusdetails=[]
 for config in CONFIGS:
  p=PRIVATE/f'training/{config}/teacher_cache/bi_train_ensemble_logits.npy'
  if not p.exists():
   consensusok&=bool(r['failures']);consensusdetails.append(dict(condition=config,status='unavailable_missing_training_cache'));continue
  f=read(PRIVATE/f'data/{config}/manifest.json');x=np.load(PRIVATE/f'data/{config}/train_X.npy',mmap_mode='r');ix=np.unique(np.r_[0,len(x)-1,np.random.default_rng(42).choice(len(x),8,replace=False)]);logits=[]
  with torch.inference_mode():
   for seed in SEEDS:
    model=loadmodel(spec(config,'T-OPT',seed),torch.device('cpu'),f['indices']);logits.append(rt.student_forward(model,torch.as_tensor(np.array(x[ix])))['logit'].numpy())
  cached=np.load(p);error=float(np.max(abs(np.mean(logits,0)-cached[ix])));consensusok&=len(cached)==len(x);consensusdetails.append(dict(condition=config,training_windows=len(x),cache_windows=len(cached),cache_sha256=sha(p),development_sample_rows=len(ix),CPU_GPU_max_abs_error=error,CPU_comparison_is_diagnostic=True))
 backend=read(OUT/'TEACHER_CONSENSUS_BACKEND_VERIFICATION.json');backendok=backend['all_original_backend_checks_passed'] and backend['population']=='development TRAIN only' and backend['original_batch_size']==1024 and backend['no_training'] and backend['no_target_inference'] and backend['no_cache_rewrite'] and sha(CODE/'consensus_backend_check9.py')==backend['code_sha256'] and set(z['condition'] for z in backend['records'])==set(CONFIGS)
 for z in backend['records']:backendok&=sha(PRIVATE/f"training/{z['condition']}/teacher_cache/bi_train_ensemble_logits.npy")==z['cache_sha256'] and z['GPU_original_1024_batch_max_abs_error']<2e-5 and z['cache_unchanged']
 checks['all_condition_teacher_consensus_caches_reconcile_on_development']=bool(consensusok) and bool(backendok);details['condition_teacher_consensus_CPU_diagnostic']=consensusdetails;details['condition_teacher_consensus_matched_training_backend']=backend
 dataok=True;validationok=True;poisonok=True
 for z in r['training_data']['conditions']:
  p=PRIVATE/f"data/{z['config']}";ix=np.load(p/'poison_indices.npy');dataok&=sha(p/'poison_indices.npy')==z['poison_index_sha256']
  for part in ('train','validation'):
   for key in ('X','X40','y'):dataok&=sha(p/f'{part}_{key}.npy')==z[part][key+'_sha256']
  validationok&=np.array_equal(np.load(p/'validation_y.npy'),np.load(HP/'tensors/validation_y.npy'))
  originaly=np.load(HP/'tensors/train_y.npy');actualy=np.load(p/'train_y.npy');expected=originaly.copy()
  if z['config']!='reduced':expected[ix]=0
  if z['config']=='backdoor01':expected=np.r_[expected,np.zeros(len(ix))]
  poisonok&=np.array_equal(actualy,expected) and len(ix)==z['modified_positive_windows']
 checks['all_prepared_data_hashes_preserved']=bool(dataok);checks['VALIDATION_labels_clean_in_all_conditions']=bool(validationok);checks['poison_labels_and_copy_counts_exact']=bool(poisonok)
 tab=pd.read_csv(P8/'Q5_FEATURE_SHIFT_PSI.csv');sets=[set(tab[(tab.release==rel)&(tab.absolute_standardized_mean_shift>.25)].feature) for rel in ('r6.1','r6.2')];f=read(OUT/'L2_FEATURES_FROZEN.json');checks['L2_exact_predeclared_both_release_feature_rule']=f['dropped']==[v for v in FEATURES if v in sets[0]&sets[1]] and f['utc']<tf['utc']
 checks['L1_scalers_unlabelled_and_never_HOLDOUT']=not read(OUT/'L1_TARGET_SCALERS_FROZEN.json')['holdout_scaling'] and all(not z['labels_read'] for z in read(OUT/'L1_TARGET_SCALERS_FROZEN.json')['releases'].values())
 consumed={p.stem:read(p) for p in (PRIVATE/'consumed').glob('*.json')};complete={p.stem:read(p) for p in (PRIVATE/'complete').glob('*.json')};infer={k:v for k,v in complete.items() if not k.startswith('L7_')};attack={k:v for k,v in complete.items() if k.startswith('L7_')};failures=r['failures'];checks['all99_new_inference_conditions_or_recorded_failures']=len(infer)==99 or bool(failures);checks['all36_attack_conditions_or_recorded_failures']=len(attack)==36 or bool(failures)
 checkpred=True;checkfreeze=True;mf=read(OUT/'MODELS_FROZEN_PHASE9.json');registry={(z.get('condition'),z['model'],z['seed']):z for z in mf['models']+mf['original_models']};regok=True
 for k,z in infer.items():
  checkpred&=k in consumed and z['state']=='COMPLETE' and sha(PRIVATE/f'scores/{k}.npy')==z['sha256'];fr=read(PRIVATE/f'frozen/{k}.json');checkfreeze&=fr['utc']<=consumed[k]['utc'] and fr['model']['sha256']==z['checkpoint_sha256'] and fr['model']['threshold']==z['threshold'] and sha(PRIVATE/f'frozen/{k}.json')==z['frozen_sha256'];sp=fr['model'];registered=registry[sp.get('condition'),sp['model'],sp['seed']];regok&=sp['sha256']==registered['sha256'] and sp['threshold']==registered['threshold'] and mf['utc']<consumed[k]['utc']
 checks['unique_score_consumption_and_all_prediction_hashes']=bool(checkpred);checks['all_models_thresholds_and_conditions_frozen_before_scoring']=bool(checkfreeze);checks['all_new_scores_match_pre_target_model_threshold_registry']=bool(regok);checks['all_extra_original_baselines_frozen_before_new_scoring']=all(extra['utc']<z['utc'] for k,z in consumed.items() if not k.startswith(('L4_','L6_')))
 attackok=True;actualbounds=True;normalpred=True;hm=holdmeta();malrows=np.flatnonzero(hm['y']==1);op0=operational();day=((hm['end_date'][malrows].astype('datetime64[D]')-op0['calendar'][0].astype('datetime64[D]')).astype(int)[:,None]-19+np.arange(20));rawcounts=np.load(R2/'phase7/private/daily_features.npy',mmap_mode='r')[hm['cluster'][malrows,None],day,1:6]
 for k,z in attack.items():
  attackok&=k in consumed and z['bounds_passed'] and z['normal_days_unchanged'] and all(sha(PRIVATE/f'scores/{k}_{n}.npy')==h for n,h in z['score_hashes'].items()) and sha(PRIVATE/f'{k}_PERTURBATIONS.npz')==z['perturbations_sha256'] and z['max_queries']<=200
  perturb=np.load(PRIVATE/f'{k}_PERTURBATIONS.npz');pc=perturb['counts'];actualbounds&=np.array_equal(perturb['source_row'],malrows) and np.all(pc>=rawcounts*(1-z['epsilon'])) and np.all(pc<=rawcounts) and np.all(pc>=0) and int(perturb['queries'].max())==z['max_queries']
  for n in ('TA2','XGBoost_40'):normalpred&=np.array_equal(np.load(PRIVATE/f'scores/{k}_{n}.npy')[hm['y']==0],original(n,z['seed'])[hm['y']==0])
 checks['all_attack_bounds_query_caps_and_saved_scores']=bool(attackok);checks['independent_saved_attack_box_and_query_count_verification']=bool(actualbounds);checks['all_unattacked_window_predictions_exactly_preserved']=bool(normalpred)
 checks['source_choices_clarified_frozen_before_attacks']=all(c['utc']<v['utc'] and sf['utc']<v['utc'] for k,v in consumed.items() if k.startswith('L7_'))
 co=holdmeta();op=operational();checks['HOLDOUT_exact_permitted_cohort_dates_and_users']=len(co['y'])==213000 and co['y'].sum()==1172 and len(np.unique(co['cluster']))==500 and str(co['end_date'].astype('datetime64[D]').max())=='2011-04-10' and set(co['partition'])=={'train','validation'}
 asr=[z for z in tests['L8'].get('points',[]) if z.get('condition')=='backdoor01_triggered'];checks['backdoor_all_insider_and_malicious_subset_denominators']=len(asr)==12 and set(z['ASR_population'] for z in asr)=={'all_insider_windows','malicious_containing_insider_windows'} and all(z['triggered_windows']==(10650 if z['ASR_population']=='all_insider_windows' else 1172) for z in asr)
 checks['L3_all48_declared_AUC_tests_and_signal_rule']=len(tests['L3']['contrasts'])==48 and all(z['forecasting_signal_CI_rule']==(z['ci95_low']>.5) for z in tests['L3']['contrasts'])
 leadok=True;users={v:i for i,v in enumerate(op['user'])};dates=co['end_date'].astype('datetime64[D]');cal=op['calendar'].astype('datetime64[D]');lookup={(int(ui),str(d)):i for i,(ui,d) in enumerate(zip(co['cluster'],dates))};scorecache={(n,s):original(n,s) for n in ('TA2','L1','XGBoost_40') for s in SEEDS}
 for z in tests['L3']['detail']:
  leadok&=z['lead'] in (1,3,5,7)
  if not z['eligible']:continue
  ui=users[z['user']];first=cal[np.flatnonzero(op['daily_y'][ui])[0]];expected=first-np.timedelta64(z['lead'],'D');row=lookup[ui,str(expected)];ctrl=(dates==expected)&~op['insider'][co['cluster']];p=scorecache[z['model'],z['seed']];pct=100*((p[ctrl]<p[row]).sum()+.5*(p[ctrl]==p[row]).sum())/ctrl.sum();leadok&=str(expected)==z['end_date'] and co['y'][row]==0 and ctrl.sum()==z['control_windows'] and np.isclose(pct,z['rank_percentile'])
 checks['L3_exact_pre_event_dates_benign_windows_and_same_date_ranks']=bool(leadok)
 checks['HOLDOUT_bootstrap_stream_exactly_matches_Phase4']=np.array_equal(np.load(PRIVATE/'bootstrap_counts_500.npy'),np.load(P4P/'BOOTSTRAP_USER_MULTIPLICITIES.npy'))
 prior=read(P8/'Q1_RESULTS.json')['per_seed_all_views'];checks['all24_cached_original_APs_match_Phase8']=all(np.isclose(read(PRIVATE/f"metrics/zero_r5.2_HOLDOUT_{z['model']}_{z['seed']}.json")['PR_AUC'],z['PR_AUC'],atol=1e-14) for z in prior if z['view']=='pooled_completed')
 checks['L4_all84_contrasts_and_route_parity']=len(tests['L4']['contrasts'])==84 and all(z['route_probability_parity_error']<2e-5 and z['prediction_parity_error']<5e-5 for z in tests['L4']['parity'])
 thresholds=read(OUT/'L5_THRESHOLDS_FROZEN.json');checks['L5_all6_ensembles_clean_validation_thresholds']=len(thresholds['thresholds'])==6 and all(z['population']=='clean development VALIDATION only' for z in thresholds['thresholds']) and tests['L5']['no_new_target_forward']
 checks['L6_all9_seed_baseline_correlations_and_no_null_tests']=len(tests['L6']['points'])==9 and tests['L6']['Holm_family_size']==0 and tests['L6']['fresh_state_reused_from_phase8']
 familyok=True
 for L,size in r['Holm_families'].items():
  if not size:continue
  rows=tests[L]['contrasts'];copy=[dict(z) for z in rows];holm(copy,L,size);familyok&=all(z['p_Holm']==b['p_Holm'] and z['Holm_family_size']==size and z['Holm_reject_0_05']==b['Holm_reject_0_05'] for z,b in zip(rows,copy))
 checks['all_Holm_families_complete_and_adjusted_p_exact']=bool(familyok)
 supplemental=read(OUT/'SUPPLEMENTAL_INTERVALS_COMPLETE.json');supfreeze=read(OUT/'SUPPLEMENTAL_STATISTICS_CODE_FROZEN.json');checks['supplemental_predeclared_statistics_code_frozen']=all(sha(CODE/k)==h for k,h in supfreeze['code'].items()) and sha(OUT/'SUPPLEMENTAL_STATISTICS_CODE_FROZEN.json')==supplemental['code_freeze_sha256']
 checks['all_predeclared_marginal_and_non_AUC_seed_mean_CIs_accounted_for']=(supplemental['counts']=={'L1':288,'L2':192,'L5':18,'L7':384,'L8':64} and supplemental['L3_additional_mean_metric_rows']==36) or bool(failures)
 figureok=True;fs=r['figures']['figures']
 for z in fs:
  p=OUT/f"{z['stem']}.png";img=Image.open(p);figureok&=min(img.info['dpi'])>299 and z['minimum_font_pt']>=12 and sha(p)==z['png_sha256'] and sha(OUT/f"{z['stem']}.csv")==z['CSV_sha256']
 checks['eight_300dpi_12pt_figures_with_matching_CSV']=len(fs)==8 and bool(figureok);qa=read(OUT/'VISUAL_QA_RECEIPT.json') if (OUT/'VISUAL_QA_RECEIPT.json').exists() else {};checks['all_eight_figures_visually_reviewed']=qa.get('all_figures_reviewed')==True and qa.get('figure_hashes')=={z['stem']:z['png_sha256'] for z in fs}
 rawids=set((HP/'HOLDOUT_USERS.txt').read_text().split())|set((HP/'DEVELOPMENT_USERS.txt').read_text().split());leaks=[]
 for p in OUT.iterdir():
  if p.suffix in ('.json','.md','.csv'):
   text=p.read_text(encoding='utf-8-sig')
   if any(v in text for v in rawids):leaks.append(p.name)
 checks['public_artifacts_pseudonyms_only']=not leaks;checks['TEST_sealed_HOLDOUT_evaluation_only']=not r['r52_test_read'] and not r['holdout_used_for_training_selection_scaling_references_thresholds']
 checks['all_reported_code_hashes_match']=all(sha(CODE/k)==h for k,h in r['code_hashes'].items());checks['all_CSV_inventory_hashes_and_rows_match']=all(sha(OUT/z['file'])==z['sha256'] and len(pd.read_csv(OUT/z['file']))==z['rows'] for z in r['CSV_inventory']);checks['all_planned_failures_explicit']=r['complete'] and all(z.get('status') for z in failures)
 report=OUT/'CHATGPT_PHASE9_REPORT.md';text=report.read_text();pending=text.rstrip().endswith('PHASE9_PENDING_VERIFICATION');checks['report_hash_and_completion_marker']=(pending or text.rstrip().endswith('PHASE9_COMPLETE')) and sha(report)==r['report_sha256']
 if all(checks.values()) and pending:
  report.write_text(text.rstrip()[:-len('PHASE9_PENDING_VERIFICATION')]+'PHASE9_COMPLETE\n',encoding='utf-8');r['report_sha256']=sha(report);r['completed_after_all_audits_utc']=utc();dump(OUT/'PHASE9_RESULTS.json',r)
 audit=dict(utc=utc(),all_checks_passed=all(checks.values()),check_count=len(checks),checks=checks,details=details,raw_identifier_leak_files=leaks,report_sha256=sha(report),result_sha256=sha(OUT/'PHASE9_RESULTS.json'));dump(OUT/'FINAL_AUDIT.json',audit);assert audit['all_checks_passed'],{k:v for k,v in checks.items() if not v};status('PHASE9_COMPLETE',checks=len(checks))
if __name__=='__main__':main()
