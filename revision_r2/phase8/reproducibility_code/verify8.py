from common8 import *
import ast
def main():
 from PIL import Image
 checks={};details={};r=read(OUT/'PHASE8_RESULTS.json');am=r['amendment8'];pr=(H/'PREREGISTRATION_R2_HOLDOUT.md').read_bytes();sources=read(OUT/'SOURCE_INTEGRITY_MANIFEST.json');freeze=read(OUT/'MODELS_FROZEN_PHASE8.json');training=r['training'];m=metadata();q1=r['Q1'];q2=r['Q2'];q3=r['Q3'];q4=r['Q4'];q5=r['Q5']
 checks['Phase7_gate_and_report_preserved']=read(R2/'phase7/FINAL_AUDIT.json')['all_checks_passed'] and sha(R2/'phase7/CHATGPT_PHASE7_REPORT.md')==am['phase7_report_sha256']
 checks['Amendment8_hashed_before_computation']=hashlib.sha256(pr[:am['hashed_bytes']]).hexdigest()==am['sha256'] and hashlib.sha256(pr[:am['previous_bytes']]).hexdigest()==am['previous_sha256'] and sha(H/'PREREGISTRATION_R2_HOLDOUT.md')==am['preregistration_final_sha256'] and am['utc']<sources['utc']
 checks['all_original_71_sources_unchanged']=len(sources['sources'])==71 and all(sha(p)==v for p,v in sources['sources'].items())
 tf=read(OUT/'TRAINING_CODE_FROZEN.json');checks['frozen_Q1_training_implementation_unchanged']=sha(ROOT/'phase2_runtime.py')==tf['runtime_sha256'] and all(sha(CODE/n)==h for n,h in tf['code'].items())
 af=read(OUT/'ANALYSIS_CODE_FROZEN.json');checks['frozen_target_analysis_code_and_dependencies_unchanged']=all(sha(CODE/n)==h for n,h in af['analysis_code'].items()) and all(sha(p)==h for p,h in af['dependencies'].items())
 checks['all_development_numerical_selfchecks_passed']=read(OUT/'DEVELOPMENT_NUMERICAL_VERIFICATION.json')['all_checks_passed']
 checks['25_planned_training_runs_accounted_for']=len(training)==25 and {(v['model'],v['seed']) for v in training}=={(n,s) for n in ('AL_PRECURSOR','T-OPT','F00','TA2','XGBoost_40') for s in NEW}
 checks['all_successful_checkpoints_unchanged']=all(sha(v['checkpoint'])==v['sha256'] for v in training if v['status']=='ok')
 checks['new_models_development_only_selection']=all(v['development_only'] and v['validation_only_checkpoint_and_threshold'] for v in training if v['status']=='ok')
 checks['TRACE_original_three_teacher_consensus_and_new_matched_routes']=all(tuple(v['consensus_seeds'])==OLD and v['matched_teacher_seed']==v['seed'] for v in training if v['status']=='ok' and v['model']=='TA2') and sha(HP/'teacher_cache/bi_train_ensemble_logits.npy')==sources['original_consensus']['cache_sha256']
 checks['XGBoost_recipe_changes_only_seed_and_thread_cap']=all({k:x for k,x in v['config']['params'].items() if k not in ('random_state','n_jobs')}=={k:x for k,x in oldspec('XGBoost_40',42)['config']['params'].items() if k not in ('random_state','n_jobs')} for v in training if v['status']=='ok' and v['model']=='XGBoost_40')
 records=[read(p) for p in (PRIVATE/'score_receipts').glob('*.json')];successful=[v for v in records if v['state']=='COMPLETE'];planned_detectors=sum(v['status']=='ok' and v['model'] in ('TA2','F00','XGBoost_40') for v in training)
 checks['new_scoring_receipts_unique_and_accounted_for']=len({(v['model'],v['seed']) for v in records})==len(records) and len(read(OUT/'Q1_SCORING_OUTCOMES.json'))==planned_detectors
 checks['all_completed_new_predictions_match_receipts']=all(v['windows']==213000 and sha(PRIVATE/f"scores/{v['model']}_{v['seed']}.npy")==v['prediction_sha256'] for v in successful)
 checks['new_detector_thresholds_frozen_before_scoring']=all(v['checkpoint_sha256']==spec(v['model'],v['seed'])['sha256'] and v['threshold']==spec(v['model'],v['seed'])['threshold'] and freeze['utc']<v['utc'] for v in records)
 checks['scoring_code_unchanged']=all(sha(CODE/n)==h for n,h in freeze['scoring_code'].items())
 checks['all_original_predictions_preserved']=all(sha(P4P/'scores'/n)==h for n,h in freeze['original_prediction_hashes'].items())
 checks['exact_Phase4_allowed_HOLDOUT_cohort_and_dates']=sha(P4P/'HOLDOUT_COHORT.npz')==read(P4/'HOLDOUT_BUILD_RECEIPT.json')['cohort_sha256'] and len(m['y'])==213000 and int(m['y'].sum())==1172 and len(np.unique(m['user']))==500 and len(np.unique(m['user'][m['y']==1]))==25 and str(m['end_date'].astype('datetime64[D]').max())=='2011-04-10' and set(m['partition'])=={'train','validation'}
 cohort=np.load(P4P/'HOLDOUT_COHORT.npz');checks['evaluation_metadata_row_alignment_matches_Phase4']=all(np.array_equal(m[k],cohort[k]) for k in ('y','user','cluster','endpoint','offset0','partition'))
 checks['Q1_twenty_planned_contrasts_retained']=len(q1['contrasts'])==20 and sum(v['seed']=='all_eight' for v in q1['contrasts'])==2 and sum(v['seed']=='new_five' for v in q1['contrasts'])==2
 points={(v['model'],v['seed']):v['PR_AUC'] for v in q1['per_seed_all_views'] if v['view']=='pooled_completed'};wins=sum(points['TA2',s]>points['F00',s] for s in ALL if ('TA2',s) in points and ('F00',s) in points);checks['Q1_strict_positive_seed_count_exact']=wins==q1['strict_TRACE_minus_F00_positive_seeds']
 bsok=True
 for z in q1['contrasts']:
  if z['status']!='ok':continue
  other=z['contrast'].split(' minus ')[1];ss=ALL if z['seed']=='all_eight' else NEW if z['seed']=='new_five' else (z['seed'],);aa=[]
  for s in ss:
   arrays=[]
   for n in ('TA2',other):arrays.append(np.load(P4P/f'bootstrap/pooled_completed_{n}_{s}.npy') if s in OLD else np.load(PRIVATE/f'bootstrap/AP_{n}_{s}.npy'))
   aa.append(arrays[0]-arrays[1])
  expected=ci(np.mean(aa,0),np.mean([points['TA2',s]-points[other,s] for s in ss]));bsok&=all(expected[k]==z[k] for k in ('estimate','ci95_low','ci95_high','valid_replicates'))
 checks['Q1_all_paired_AP_CIs_reconcile']=bool(bsok)
 checks['Q1_all_five_views_and_insider_denominators']=set(v['view'] for v in q1['per_seed_all_views'])=={'pooled_completed','train_completed','validation_completed','pooled_offset0','pooled_endpoint'} and all(v['insiders_total']==25 and 0<=v['insiders_detected']<=25 for v in q1['per_seed_all_views'])
 q2ok=True;selection={}
 for z in q2['outcomes']:
  if z['status']!='ok':continue
  n,s,t=z['model'],z['seed'],z['length'];base=HP/'tensors' if t==20 else R2/'phase6/private/data/r52_T30_F13';y=np.load(base/'validation_y.npy');pos=np.flatnonzero(y==1);neg=np.random.default_rng(42).choice(np.flatnonzero(y==0),len(pos),replace=False);expected=np.sort(np.r_[pos,neg]);actual=np.load(PRIVATE/f'Q2/{n}_{s}_T{t}/development_selection.npy');q2ok&=np.array_equal(expected,actual) and z['development_only'];selection[n,s,t]=actual
  curves=[v for v in q2['curves'] if v['model']==n and v['seed']==s and v['length']==t];q2ok&=len(curves)==t and (not z['normalization_defined'] or np.isclose(curves[-1]['normalized_mean'],1,atol=1e-12))
 checks['Q2_validation_only_common_fixed_sampling_and_normalization']=bool(q2ok)
 checks['Q2_gradients_at_all_three_components']=set(v['component'] for v in q2['component_summary'])=={'input','LSTM_output','attention_context'} and all(0<=v['exact_zero_fraction']<=1 and np.isfinite(v['mean_L2']) for v in q2['component_summary'])
 checks['Q2_30day_checkpoints_accounted_for']=sum(v['length']==30 for v in q2['outcomes'])==3
 routeok=True
 for z in q3['outcomes']:
  if z['status']!='ok':continue
  count=np.array(z['occupancy_counts']);routeok&=count.shape==(8,16) and np.all(count.sum(1)==213000) and np.array(z['mean_right_branch_probability']).shape==(8,4) and sha(PRIVATE/f"routes/{z['model']}_{z['seed']}/tree_outputs.npy")==z['tree_outputs_sha256']
  if z['seed'] in OLD:routeok&=z['original_saved_probability_max_abs_error']<5e-5
 checks['Q3_all_route_receipts_shapes_mass_and_parity']=bool(routeok)
 entropy=True
 for z in q3['tree_metrics']:
  occ=np.array([v['occupancy_share'] for v in q3['leaf_occupancy'] if v['model']==z['model'] and v['seed']==z['seed'] and v['tree']==z['tree']]);expected=-(occ[occ>0]*np.log(occ[occ>0])).sum()/np.log(16);decision='above_chance' if z['ci95_low']>.5 else 'reversed_below_chance' if z['ci95_high']<.5 else 'compatible_with_chance';entropy&=np.isclose(expected,z['normalized_entropy']) and int((occ==0).sum())==z['never_argmax_leaves'] and z['separation']==decision
 checks['Q3_entropies_unused_leaves_and_AUC_rules_exact']=bool(entropy) and q3['AUC_bootstrap_selfcheck']
 checks['Q3_every_successful_model_has_all_eight_trees']=len(q3['tree_metrics'])==8*sum(v['status']=='ok' for v in q3['outcomes']) and len(q3['leaf_occupancy'])==16*len(q3['tree_metrics']) and len(q3['routing_by_depth'])==4*len(q3['tree_metrics'])
 q4ok=True;fresh=[];stagekeys={}
 for z in q4['outcomes']:
  if z['status']!='ok':continue
  f=z['freeze'];dest=PRIVATE/f"Q4/seed{z['seed']}/{z['stage']}";q4ok&=sha(dest/'explanations.npz')==z['explanation_sha256'] and sha(dest/'randomized_state.pt')==f['checkpoint_sha256'] and f['initialization_population']=='development TRAIN only' and f['tree_reference_population']=='development TRAIN only' and f['IG_50_interval_final_output_parity_error']<1e-5;fresh.append(f['fresh_initialization_state_sha256']);stagekeys[z['seed'],z['stage']]=set(f['changed_state_keys']);arr=np.load(dest/'correlations.npz')
  for row in z['rows']:
   a=arr[row['component']];v=a[np.isfinite(a)];q4ok&=len(a)==2344 and row['valid_windows']==len(v) and row['constant_or_undefined_windows']==len(a)-len(v)
   if len(v):q4ok&=np.isclose(np.median(v),row['median_rho']) and np.isclose(np.quantile(v,.25),row['Q1_rho']) and np.isclose(np.quantile(v,.75),row['Q3_rho'])
  if z['stage']=='head':q4ok&=z['head_only_attention_max_abs_error']<5e-5
 checks['Q4_saved_cohort_development_references_IG_parity_and_correlations']=bool(q4ok)
 checks['Q4_progressive_groups_nested_and_fixed_fresh_seed']=len(set(fresh))<=1 and all(stagekeys[s,'head']<=stagekeys[s,'head_attention']<=stagekeys[s,'all'] for s in OLD if all((s,k) in stagekeys for k in ('head','head_attention','all')))
 checks['Q4_all_nine_planned_stages_accounted_for']=len(q4['outcomes'])==9
 inputfreeze=read(OUT/'Q5_INPUT_MONITOR_FROZEN.json');mon=read(OUT/'Q5_MONITOR_FROZEN_BEFORE_TRANSFER_COMPARISON.json')
 # Q5_RESULTS copies the frozen monitor dict, including utc; it has no separate comparison timestamp.
 # Verify that inheritance, the frozen content/hash, the later artifact write and the preserved reader order.
 q5source=(CODE/'shift8.py').read_text(encoding='utf-8');freeze_call="dump(OUT/'Q5_MONITOR_FROZEN_BEFORE_TRANSFER_COMPARISON.json',monitor)";known_call="known=[];old=read(P5/'A_RESULTS.json')"
 q5time=(OUT/'Q5_RESULTS.json').stat().st_mtime_ns;montime=(OUT/'Q5_MONITOR_FROZEN_BEFORE_TRANSFER_COMPARISON.json').stat().st_mtime_ns
 checks['Q5_no_target_labels_and_monitor_frozen_before_known_summary']=not inputfreeze['target_labels_read'] and not mon['target_labels_read'] and mon['known_transfer_results_not_yet_read'] and q5['monitor_frozen_before_known_summary'] and mon['utc']==q5['utc'] and sha(OUT/'Q5_MONITOR_FROZEN_BEFORE_TRANSFER_COMPARISON.json')==q5['monitor_sha256'] and all(q5[k]==mon[k] for k in ('features','flags','score_distributions','cohorts','outcomes','reused_score_receipts')) and q5time>montime and q5source.index(freeze_call)<q5source.index(known_call)
 details['Q5_timestamp_semantics']=dict(monitor_utc=mon['utc'],result_inherits_monitor_utc=q5['utc']==mon['utc'],monitor_write_ns=montime,result_write_ns=q5time,reader_order_preserved=q5source.index(freeze_call)<q5source.index(known_call),initial_audit_correction='Strict utc inequality was inappropriate for a result built by copying the monitor dictionary; no monitor, inference or method was rerun.')
 monitorok=True
 for z in q5['features']:
  ref=np.array(z['reference_bin_counts']);target=np.array(z['target_bin_counts']);pr=(ref+.5)/(ref.sum()+.5*len(ref));pt=(target+.5)/(target.sum()+.5*len(target));monitorok&=np.isclose(((pt-pr)*np.log(pt/pr)).sum(),z['PSI'],atol=1e-14) and ref.sum()==619500 and target.sum()==z['target_daily_rows']
 for z in q5['flags']:
  rows=[v for v in q5['features'] if v['release']==z['release']];monitorok&=z['flagged']==(max(v['absolute_standardized_mean_shift'] for v in rows)>.25 or max(v['PSI'] for v in rows)>.25)
 checks['Q5_all_52_PSI_histograms_and_four_frozen_rules_exact']=len(q5['features'])==52 and len(q5['flags'])==4 and bool(monitorok)
 checks['Q5_unlabelled_input_source_hashes_unchanged']=all(sha(p)==h for p,h in inputfreeze['dependencies'].items())
 # The sole post-input-freeze edit filters the later aggregate historical reader to completed-window rows.
 raw=(CODE/'shift8.py').read_bytes();line=b" if 'view' in hist:hist=hist[hist['view']=='COMPLETED_WINDOW']\n";oldhash=hashlib.sha256(raw.replace(line,b'')).hexdigest();checks['Q5_input_monitor_code_preserved_through_comparison_only_clarification']=sha(CODE/'shift8.py')==inputfreeze['code_sha256'] or oldhash==inputfreeze['code_sha256'];details['Q5_comparison_only_code_clarification']=dict(frozen_code_sha256=inputfreeze['code_sha256'],current_code_sha256=sha(CODE/'shift8.py'),reverse_single_comparison_filter_recovers_frozen_code=oldhash==inputfreeze['code_sha256'])
 supplement=read(OUT/'Q5_KNOWN_R61_TRANSFER_SUPPLEMENT.json');sr=supplement['record'];checks['Q5_all_three_known_transfer_releases_and_post_monitor_source']=set(z['release'] for z in q5['known_transfer_summary'])=={'r5.1','r6.1','r6.2'} and sha(sr['source'])==sr['source_sha256'] and mon['utc']<supplement['utc'] and not supplement['raw_label_arrays_read'] and not supplement['monitor_or_predictions_recomputed']
 checks['Q5_twelve_score_distribution_rows_or_recorded_failures']=len(q5['score_distributions'])==12 or bool(r['failures'])
 checks['all_child_failures_timeouts_and_skips_retained']=r['complete'] and (not r['failures'] or all(v.get('status') for v in r['failures']))
 figures=read(OUT/'FIGURE_RECEIPTS.json')['figures'];figok=True
 for z in figures:
  p=OUT/f"{z['stem']}.png";data=OUT/f"{z['stem']}.csv";im=Image.open(p);figok&=min(im.info['dpi'])>299 and z['minimum_font_pt']>=12 and sha(p)==z['png_sha256'] and sha(data)==z['CSV_sha256'] and len(pd.read_csv(data))>0
 checks['all_five_300dpi_12pt_figures_and_paired_data']=len(figures)==5 and bool(figok)
 qa=read(OUT/'VISUAL_QA_RECEIPT.json') if (OUT/'VISUAL_QA_RECEIPT.json').exists() else {};checks['all_figures_visually_reviewed']=qa.get('all_figures_reviewed')==True and qa.get('figure_hashes')=={z['stem']:z['png_sha256'] for z in figures}
 rawids=set((HP/'DEVELOPMENT_USERS.txt').read_text().split())|set((HP/'HOLDOUT_USERS.txt').read_text().split());leaks=[]
 for p in OUT.iterdir():
  if p.suffix in ('.json','.md','.csv'):
   text=p.read_text(encoding='utf-8-sig')
   if any(v in text for v in rawids):leaks.append(p.name)
 checks['public_outputs_no_raw_CERT_identifiers']=not leaks
 checks['sealed_TEST_and_no_HOLDOUT_fitting_selection_scaling_thresholds']=r['r52_test_read']==False and r['holdout_used_for_training_selection_scaling_thresholds']==False and r['Q5_target_labels_read']==False
 checks['all_final_analysis_code_hashes_match']=all(sha(CODE/n)==h for n,h in r['code_hashes'].items())
 checks['CSV_inventory_hashes_and_rows_match']=all(sha(OUT/z['file'])==z['sha256'] and len(pd.read_csv(OUT/z['file']))==z['rows'] for z in r['CSV_inventory'])
 report=OUT/'CHATGPT_PHASE8_REPORT.md';reporttext=report.read_text(encoding='utf-8');pending=reporttext.rstrip().endswith('PHASE8_PENDING_VERIFICATION');checks['report_completion_marker_and_hash']=(pending or reporttext.rstrip().endswith('PHASE8_COMPLETE')) and sha(report)==r['report_sha256']
 if all(checks.values()) and pending:
  report.write_text(reporttext.rstrip()[:-len('PHASE8_PENDING_VERIFICATION')]+'PHASE8_COMPLETE\n',encoding='utf-8');r['report_sha256']=sha(report);r['completed_after_all_audits_utc']=utc();dump(OUT/'PHASE8_RESULTS.json',r);checks['report_completion_marker_and_hash']=report.read_text().rstrip().endswith('PHASE8_COMPLETE') and sha(report)==r['report_sha256']
 audit=dict(utc=utc(),all_checks_passed=all(checks.values()),check_count=len(checks),checks=checks,details=details,raw_identifier_leak_files=leaks,report_sha256=sha(OUT/'CHATGPT_PHASE8_REPORT.md'),result_sha256=sha(OUT/'PHASE8_RESULTS.json'),r52_test_read=False);dump(OUT/'FINAL_AUDIT.json',audit);assert audit['all_checks_passed'],{k:v for k,v in checks.items() if not v};status('PHASE8_COMPLETE',checks=len(checks))
if __name__=='__main__':main()
