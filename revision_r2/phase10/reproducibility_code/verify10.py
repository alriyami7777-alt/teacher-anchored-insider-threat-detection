from common10 import *
from report10 import expected
def main():
 interim='--interim' in sys.argv
 checks={};detail={};a=read(OUT/'AMENDMENT10_RECEIPT.json');cr=read(OUT/'AMENDMENT10_CLARIFICATION_RECEIPT.json');pr=(R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md').read_bytes();f=read(OUT/'PREREQUISITES_FROZEN.json');sp=read(OUT/'R62_SPLIT_RECEIPT.json');frozen=read(OUT/'TRAINING_CODE_FROZEN.json');af=read(OUT/'ANALYSIS_CODE_FROZEN.json');results=read(OUT/'PHASE10_RESULTS.json');planned,evals=expected()
 checks['amendment_and_clarification_prefix_chain']=all(hashlib.sha256(pr[:r['hashed_bytes']]).hexdigest()==r['sha256'] for r in (a,cr)) and hashlib.sha256(pr[:a['previous_bytes']]).hexdigest()==a['previous_sha256'] and hashlib.sha256(pr[:cr['previous_bytes']]).hexdigest()==cr['previous_sha256']
 if (OUT/'DEADLINE_EXTENSION_RECEIPT.json').exists():
  extension=read(OUT/'DEADLINE_EXTENSION_RECEIPT.json');checks['approved_1830_deadline_extension_hash_and_history']=hashlib.sha256(pr[:extension['hashed_bytes']]).hexdigest()==extension['sha256'] and hashlib.sha256(pr[:extension['previous_bytes']]).hexdigest()==extension['previous_sha256'] and extension['deadline_local']=='2026-10-23T18:30:00+08:00' and read(OUT/'DEADLINE_EXTENSION_CONTROL_CHANGE.json')['hyperparameters_data_thresholds_statistics_unchanged']
  history=P/'control_history/deadline_extension';oldtf=read(history/'TRAINING_CODE_FROZEN.json');oldaf=read(history/'ANALYSIS_CODE_FROZEN.json');expected_common=(history/'common10.py').read_text().replace('17:45','18:30');expected_worker=(history/'worker10.py').read_text().replace(' rows=[]\n'," rows=read(OUT/'EXECUTION_LOG.json') if (OUT/'EXECUTION_LOG.json').exists() else []\n",1).replace("    run('p1_10.py',[s],f'p1_{s}')","    if not (OUT/f'P1_THRESHOLDS_{s}.json').exists():run('p1_10.py',[s],f'p1_{s}')")
  checks['deadline_extension_preserves_every_scientific_method']=expected_common==(CODE/'common10.py').read_text() and expected_worker==(CODE/'worker10.py').read_text() and all(sha(CODE/n)==oldtf['code'][n] for n in ('prepare10.py','train10.py','infer10.py','p1_10.py')) and all(sha(CODE/n)==oldaf['code'][n] for n in ('stats10.py','contrasts10.py')) and sha(ROOT/'phase2_runtime.py')==oldtf['runtime_sha256']
 checks['split_receipt_and_sorted_pseudonym_hashes']=sha(OUT/'R62_SPLIT_RECEIPT.json')==f['split_receipt_sha256'] and sha(OUT/'R62_HOLDOUT_PSEUDONYMS.txt')==sp['heldout_list_sha256'] and sha(OUT/'R62_DEVELOPMENT_PSEUDONYMS.txt')==sp['development_list_sha256']
 checks['all_split_and_nested_indices_preserved']=all(sha(P/n)==h for n,h in sp['index_hashes'].items()) and sha(P/'INSIDER_STATUS.npy')==read(OUT/'SPLIT_METADATA_ACCESS_CORRECTION.json')['insider_status_sha256']
 hl=(OUT/'R62_HOLDOUT_PSEUDONYMS.txt').read_text().splitlines();dl=(OUT/'R62_DEVELOPMENT_PSEUDONYMS.txt').read_text().splitlines();checks['pseudonym_lists_sorted_unique_disjoint']=hl==sorted(set(hl)) and dl==sorted(set(dl)) and len(hl)==len(dl)==2000 and not set(hl)&set(dl)
 checks['original_sources_scores_checkpoints_unchanged']=all(sha(z['path'])==z['sha256'] for z in read(OUT/'SOURCE_INTEGRITY_FROZEN.json')['sources'])
 checks['r52_evaluation_inputs_and_both_user_lists_preserved']=all(sha(z['path'])==z['sha256'] for z in read(OUT/'EVALUATION_INPUTS_FROZEN.json')['sources'])
 historical=read(R2/'phase9/ADDITIONAL_SOURCE_INTEGRITY_MANIFEST.json')['sources'];cached_sources=[z for z in read(OUT/'SOURCE_INTEGRITY_FROZEN.json')['sources'] if z['role'].startswith('cached')];checks['original_cached_baselines_match_pre_Phase9_freeze']=all(z['path'] in historical and z['sha256']==historical[z['path']] for z in cached_sources)
 checks['frozen_training_and_analysis_code_unchanged']=all(sha(CODE/n)==h for z in (frozen,af) for n,h in z['code'].items()) and sha(ROOT/'phase2_runtime.py')==frozen['runtime_sha256']
 if not interim:checks['all_reported_code_hashes_match']=all(sha(CODE/n)==h for n,h in results['code_hashes'].items())
 checks['development_numerical_audit_passed']=read(OUT/'DEVELOPMENT_NUMERICAL_AUDIT.json')['all_checks_passed']
 manifests=[read(p) for p in (P/'data').glob('*/manifest.json')];checks['own_training_tensors_match_frozen_manifests']=all(sha(P/f'data/{z["condition"]}/{n}')==h for z in manifests for n,h in z['files'].items())
 training=[read(p) for p in (P/'training').glob('*/results/*.json')];checks['all_successful_checkpoints_preserved']=all(sha(z['checkpoint'])==z['sha256'] for z in training)
 weights=[];recipes=[];times=[]
 for z in training:
  y=np.load(P/f'data/{z["condition"]}/train_y.npy',mmap_mode='r');ratio=(len(y)-y.sum())/y.sum();cfg=z['config'];mult=1 if 'PRECURSOR' in z['model'] else .25
  weights.append(np.isclose(cfg['params']['scale_pos_weight'] if z['model']=='XGBoost_40' else cfg['pos_weight'],ratio if z['model']=='XGBoost_40' else mult*ratio));recipes.append(z['development_only'] and (z['epochs']<=10 and cfg['encoder_lr']==3e-6 and cfg['head_lr']==1e-4 if z['condition'].startswith('adapt') else True));times.append(z['wall_seconds']<2700)
 checks['class_imbalance_weights_use_own_TRAIN_labels']=all(weights);checks['adaptation_epoch_LR_and_development_only_rules']=all(recipes);checks['every_completed_training_under_45_minutes']=all(times)
 scorefiles=list((P/'complete').glob('*.json'));receipts=[read(p) for p in scorefiles];locks=list((P/'consumed').glob('*.json'));unfinished={p.stem for p in locks}-{r['key'] for r in receipts};accounted={r.get('key') for r in results['not_run_or_unfinished'] if r.get('kind')=='heldout_scoring'};checks['one_exclusive_score_receipt_per_new_condition']=len({r['key'] for r in receipts})==len(receipts) and all((P/f'consumed/{r["key"]}.json').exists() for r in receipts) and (not unfinished or results['marker']=='PHASE10_PARTIAL' and unfinished<=accounted)
 checks['all_new_target_conditions_preregistered']={r['key'] for r in receipts}<=set(evals)
 checks['all_new_scores_match_frozen_models_thresholds_and_hashes']=all(sha(P/f'scores/{r["key"]}.npy')==r['score_sha256'] and read(P/f'frozen/{r["key"]}.json')['model']['sha256']==r['checkpoint_sha256'] and read(P/f'frozen/{r["key"]}.json')['model']['threshold']==r['threshold'] for r in receipts)
 checks['r52_new_scores_only_pooled']=all(r['key'].startswith('pooled_') for r in receipts if r['key'].endswith('_r52'))
 timestamps=[datetime.fromisoformat(r['utc']).timestamp() for r in receipts];checks['all_completed_target_scoring_before_hard_stop']=all(t<=DEADLINE for t in timestamps)
 checks['amendment_split_precede_all_new_scoring_training']=datetime.fromisoformat(a['utc'])<datetime.fromisoformat(sp['utc']) and all(datetime.fromisoformat(read(p)['utc'])>datetime.fromisoformat(sp['utc']) for p in (P/'frozen').glob('*.json'))
 checks['heldout_labels_never_select_thresholds_scalers_models']=all(z['all_heldout_excluded'] for z in manifests) and not results['heldout_used_for_training_selection_scaling_thresholds']
 cross=read(OUT/'CROSS_RELEASE_USER_DISJOINTNESS.json');checks['both_releases_heldout_users_disjoint_from_all_development']=cross['r62_HOLDOUT_ID_overlap_r52_DEVELOPMENT']==0 and cross['r52_HOLDOUT_ID_overlap_r62_DEVELOPMENT']==0 and cross['all_release_ID_overlap']==0
 checks['original_TEST_sealed']=results['r52_TEST_read'] is False and read(OUT/'SOURCE_INTEGRITY_FROZEN.json')['read_test'] is False
 countscheck=True
 for N in (2000,500):
  p=P/f'bootstrap_counts_{N}.npy'
  if p.exists():
   actual=np.load(p);rng=np.random.default_rng(42);exp=np.array([np.bincount(rng.integers(0,N,N),minlength=N) for _ in range(2000)],np.int16);countscheck &= np.array_equal(actual,exp)
 checks['bootstrap_exact_2000_default_rng42_user_clusters']=bool(countscheck)
 hcheck=True;intervalcheck=True;missing=[]
 for priority,size in ((1,24),(2,60),(3,120),(4,180)):
  rows=read(OUT/f'P{priority}_CONTRASTS.json')['contrasts'];hcheck &= len(rows)==size;ps=np.array([r['p_unadjusted'] for r in rows]);order=np.argsort(ps,kind='stable');adj=np.maximum.accumulate(np.minimum(1,ps[order]*(size-np.arange(size))));hcheck &= np.allclose(adj,np.array([rows[i]['p_Holm'] for i in order]));missing += [r for r in rows if r['status']!='ok'];intervalcheck &= all(r.get('attempted_replicates')==2000 and r['valid_replicates']<=2000 for r in rows if r['status']=='ok')
 checks['all_384_contrasts_retained_and_Holm_exact']=bool(hcheck);checks['all_completed_contrast_CIs_use_2000_paired_replicates']=bool(intervalcheck)
 checks['baseline_refit_ranking_metrics_exactly_unchanged']=all(all(read(P/f'metrics/P1_{n}_{s}_r62.json')[k]==read(P/f'metrics/zero_{n}_{s}_r62.json')[k] for k in ('PR_AUC','AP_over_prevalence','top1_insider_recall')) for n in MODELS for s in SEEDS if (P/f'metrics/P1_{n}_{s}_r62.json').exists())
 if not interim:checks['complete_or_partial_marker_honest']=(results['marker']=='PHASE10_COMPLETE' and len(training)==42 and len(receipts)==39 and not missing and not results['not_run_or_unfinished']) or (results['marker']=='PHASE10_PARTIAL' and bool(missing or results['not_run_or_unfinished']))
 figure=read(OUT/'FIGURE_RECEIPT.json');checks['figure_300dpi_12pt_and_adjacent_CSV']=figure['dpi']==300 and figure['minimum_font_points']>=12 and sha(OUT/'PHASE10_SUMMARY.png')==figure['png_sha256'] and sha(OUT/'PHASE10_SUMMARY.csv')==figure['csv_sha256']
 if not interim:
  qa=read(OUT/'VISUAL_QA_RECEIPT.json') if (OUT/'VISUAL_QA_RECEIPT.json').exists() else {};checks['summary_figure_visually_reviewed']=qa.get('figure_sha256')==figure['png_sha256'] and qa.get('reviewed') is True
 rawids=np.load(B/'user_ids.npy');leaks=[]
 for p in OUT.iterdir():
  if p.is_file() and p.suffix.lower() in ('.md','.json','.csv','.txt'):
   text=p.read_text(encoding='utf-8-sig')
   if any(str(i) in text for i in rawids):leaks.append(p.name)
 checks['public_outputs_pseudonyms_only']=not leaks
 report=OUT/'CHATGPT_PHASE10_REPORT.md';checks['report_ends_with_result_marker']=report.read_text(encoding='utf8').rstrip().endswith(results['marker']);detail.update(successful_training=len(training),completed_new_inference=len(receipts),planned_training=42,planned_inference=39,uncomputed_contrasts=len(missing),public_raw_id_leak_files=leaks)
 audit=dict(utc=utc(),interim=interim,all_checks_passed=all(checks.values()),check_count=len(checks),checks=checks,details=detail,report_sha256=sha(report),result_sha256=sha(OUT/'PHASE10_RESULTS.json'));dump(OUT/('INTERIM_AUDIT.json' if interim else 'FINAL_AUDIT.json'),audit);print(json.dumps(audit,indent=2));assert all(checks.values())
if __name__=='__main__':main()
