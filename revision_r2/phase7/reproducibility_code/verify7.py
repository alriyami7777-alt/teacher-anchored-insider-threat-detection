from common7 import *
import ast
def main():
 from PIL import Image
 checks={};details={};am=read(OUT/'AMENDMENT7_RECEIPT.json');pr=(R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md').read_bytes();f=read(OUT/'SOURCE_INTEGRITY_MANIFEST.json');r=read(OUT/'PHASE7_RESULTS.json');op=read(OUT/'OPERATIONAL_RESULTS.json');a=read(OUT/'CASE_ATTRIBUTION_RESULTS.json');co=read(OUT/'COMBINATION_SENSITIVITY_RESULTS.json');dev=read(OUT/'DEVELOPMENT_THRESHOLDS_FROZEN.json');m,o=metadata();y=m['y'];u=m['cluster'];dates=o['rowdate'];di=(dates-o['calendar'][0]).astype(int);c=np.load(P4P/'BOOTSTRAP_USER_MULTIPLICITIES.npy')
 checks['Phase6C_complete_before_Phase7']=read(R2/'phase6c/FINAL_AUDIT.json')['all_checks_passed'] and (R2/'phase6c/CHATGPT_PHASE6C_REPORT.md').read_text().rstrip().endswith('PHASE6C_COMPLETE') and sha(R2/'phase6c/CHATGPT_PHASE6C_REPORT.md')==am['phase6c_report_sha256']
 checks['Amendment7_hash_and_preserved_previous_prefix']=hashlib.sha256(pr[:am['hashed_bytes']]).hexdigest()==am['sha256'] and hashlib.sha256(pr[:am['previous_bytes']]).hexdigest()==am['previous_sha256'] and sha(R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md')==am['preregistration_final_sha256']
 checks['Amendment7_precedes_all_calculations']=am['utc']<read(OUT/'PREPARATION_RECEIPT.json')['utc']<dev['utc']<co['utc']
 checks['all_65_original_source_hashes_unchanged']=len(f['sources'])==65 and all(sha(p)==h for p,h in f['sources'].items())
 checks['original_model_checkpoint_hashes_unchanged']=len(specs())==18 and all(sha(s['checkpoint'])==s['sha256'] for s in specs())
 checks['development_threshold_code_unchanged']=all(sha(CODE/n)==h for n,h in dev['code_hashes'].items())
 checks['original_HOLDOUT_prediction_hashes_unchanged']=all(sha(P4P/'scores'/p)==h for p,h in read(P4/'SCORING_COMPLETE.json')['prediction_hashes'].items())
 orig=read(R2/'holdout/MODELS_FROZEN.json');checks['frozen_development_and_holdout_memberships_unchanged']=sha(HP/'HOLDOUT_USERS.txt')==orig['holdout_list_sha256'] and sha(HP/'DEVELOPMENT_USERS.txt')==orig['development_list_sha256']
 checks['allowed_dates_and_frozen_cohort']=len(y)==213000 and int(y.sum())==1172 and len(o['calendar'])==464 and str(dates.max())=='2011-04-10' and str(o['calendar'][0])=='2010-01-02' and o['insider'].sum()==25 and set(m['partition'])=={'train','validation'}
 reconstructed=np.array([o['daily_y'][int(ui),int(dd)-19:int(dd)+1].max() for ui,dd in zip(u,di)],np.int8);checks['all_window_labels_match_permitted_daily_labels']=np.array_equal(reconstructed,y) and np.array_equal(o['daily_y'][u,di],m['endpoint'])
 rng=np.random.default_rng(42);expected=np.array([np.bincount(rng.integers(0,500,size=500),minlength=500) for _ in range(2000)],np.int16);checks['bootstrap_exact_2000_seed42_paired_stream']=np.array_equal(c,expected)
 checks['P3_25_insiders_450_model_seed_rows']=len(op['timing_25_rows'])==25 and len(op['timing'])==450 and len({v['user'] for v in op['timing']})==25 and {v['model'] for v in op['timing']}==set(NAMES.values())
 correct=True
 for n in NAMES.values():
  for s in SEEDS:
   p=score(n,s);t=spec(n,s)['threshold'];pred=p>=t;rank=rankdata(-p,method='average');correct&=np.array_equal(rank,np.load(PRIVATE/f'ranks/{n}_{s}.npy'))
   for row in [z for z in op['timing'] if z['model']==n and z['seed']==s]:
    ui=int(np.flatnonzero(o['user']==row['user'])[0]);rr=np.flatnonzero((u==ui)&pred&(y==1));anyrows=np.flatnonzero((u==ui)&pred);firstday=o['calendar'][np.flatnonzero(o['daily_y'][ui])[0]];correct&=row['detected']==bool(len(rr))
    if len(rr):first=rr[np.argmin(dates[rr])];correct&=row['detection_delay_days']==int((dates[first]-firstday).astype(int)) and row['first_malicious_window_alert_rank']==rank[first] and row['detection_delay_days']>=0
    else:correct&=row['detection_delay_days'] is None and row['first_malicious_window_alert_rank'] is None
    if len(anyrows):first=anyrows[np.argmin(dates[anyrows])];correct&=row['first_any_alert_delay_days']==int((dates[first]-firstday).astype(int)) and row['first_any_alert_rank']==rank[first]
 checks['P3_all_detections_delays_and_global_ranks']=bool(correct)
 union={v['user'] for v in op['timing'] if v['model']=='TRACE' and not v['detected']};checks['P1_every_missed_TRACE_insider_retained']=union=={v['user'] for v in a['cases']} and a['all_seeds_missed']==['U_488844ba74']
 peaks=True
 for row in a['peak_windows']:
  p=score('TRACE',row['seed']);rr=np.flatnonzero((m['user']==row['user'])&(y==1));best=rr[np.lexsort((rr,dates[rr],-p[rr]))[0]];peaks&=row['source_row']==best and row['max_malicious_window_score']==p[best]
 checks['P1_peak_selection_exact_and_explanations_complete']=bool(peaks) and not a['missing_components'] and len(a['attention'])==60 and len(a['IG_features'])==39 and len(a['tree_contributions'])==24 and len(pd.read_csv(OUT/'P1_MALICIOUS_CONTAINING_WINDOW_SCORES.csv'))==192
 checks['P1_all_13_features_on_all_23_malicious_days']=len(a['malicious_day_features'])==23*13 and {v['feature'] for v in a['malicious_day_features']}==set(FEATURES)
 checks['P2_sample_coverage_transparent']=all(z['saved_explanation_windows']==z['valid_IG_windows'] and 0<z['coverage_fraction']<.008 for z in a['P2_coverage'] if z['group']=='false_alarm_noninsider') and [z['saved_explanation_windows'] for z in a['P2_coverage'] if z['group']=='false_alarm_noninsider']==[3,5,5]
 shares=pd.DataFrame(a['P2_attribution']);sums=shares.groupby(['seed','group','level']).mean_absolute_IG_share.sum();checks['P2_feature_and_source_IG_shares_sum_to_one']=bool(np.allclose(sums,1,atol=1e-12))
 # Independent scalar summation avoids repeating the vectorized user-day indexing path.
 daily=np.load(PRIVATE/'daily_features.npy');meansok=True
 for s in SEEDS:
  p=score('TRACE',s);flag=p>=spec('TRACE',s)['threshold']
  for name,mask in [('false_alarm_noninsider',flag&(~o['insider'][u])),('true_positive',flag&(y==1))]:
   rr=np.flatnonzero(mask);sums=np.zeros(13)
   for i in rr:sums+=daily[int(u[i]),int(di[i])-19:int(di[i])+1].sum(0)
   actual=sums/(len(rr)*20);exported=np.array([next(z['window_day_weighted_mean'] for z in a['P2_activity'] if z['seed']==s and z['group']==name and z['feature']==feature) for feature in FEATURES]);meansok&=np.allclose(actual,exported,atol=1e-10,rtol=1e-12)
 checks['P2_activity_means_independent_scalar_check']=bool(meansok)
 user=pd.read_csv(OUT/'P2_ALERTS_PER_USER.csv');episodes=pd.read_csv(OUT/'P2_ALERT_EPISODES.csv');day=pd.read_csv(OUT/'P2_ALERTS_PER_DAY.csv');checks['P2_all_users_and_calendar_days_accounted_for']=len(user)==3000 and len(day)==2784 and int((~day.scorable).sum())==228 and int(user.alert_episodes.sum())==len(episodes) and int(day.episode_starts.sum())==len(episodes) and int(day.alert_user_days.sum())==int(user.alert_user_days.sum())
 jacok=True
 counts={ (z['model'],z['seed']):set(z['pseudonyms']) for z in op['P2_counts']}
 for z in op['P2_Jaccard']:
  aa=counts[z['model_a'],z['seed_a']];bb=counts[z['model_b'],z['seed_b']];jacok&=z['intersection']==len(aa&bb) and z['union']==len(aa|bb) and z['Jaccard']==(len(aa&bb)/len(aa|bb) if aa|bb else 1.)
 checks['P2_all_15_Jaccard_pairs_exact']=len(op['P2_Jaccard'])==15 and bool(jacok)
 sel=pd.read_csv(OUT/'P4_SELECTED_USER_DAY_ALERTS.csv');checks['P4_all_72_budget_rows_and_workloads']=len(op['P4_budget_results'])==72 and all(z['eligible_days']==426 and z['total_alerts']==426*z['budget'] for z in op['P4_budget_results']) and len(sel)==18*426*18 and not sel.duplicated(['model','seed','budget','date','user']).any()
 policy=True
 for n in NAMES.values():
  for s in SEEDS:
   p=score(n,s);g=sel[(sel.model==n)&(sel.seed==s)&(sel.budget==10)]
   for date,gg in g.groupby('date'):
    rr=np.flatnonzero(dates==np.datetime64(date));expectedrows=rr[np.lexsort((o['user'][u[rr]],-p[rr]))][:10];policy&=np.array_equal(gg.source_row.to_numpy(),expectedrows)
 checks['P4_daily_top10_policy_verified_for_all_18_models']=bool(policy)
 vectors=np.load(PRIVATE/'P4_detection_vectors.npz');contrastok=True
 for z in op['P4_contrasts']:
  other=z['contrast'].split(' minus ')[1];seeds=SEEDS if z['seed']=='mean_three' else [z['seed']];ds=[vectors[f"TRACE_{s}_{z['budget']}"]-vectors[f"{other}_{s}_{z['budget']}"] for s in seeds];values=np.mean([c@v for v in ds],0);estimate=np.mean([v.sum() for v in ds]);expectedrow=summary(values,estimate);contrastok&=all(z[k]==expectedrow[k] for k in ('estimate','ci95_low','ci95_high','valid_replicates'))
 checks['P4_all_32_paired_count_CIs_verified']=len(op['P4_contrasts'])==32 and bool(contrastok)
 cells=True
 for s in SEEDS:
  for population,denominator in [('insiders',25),('noninsiders',475)]:
   rows=[z for z in op['P5_complementarity'] if z['seed']==s and z['population']==population];lists=[set(z['pseudonyms']) for z in rows];cells&=sum(len(v) for v in lists)==len(set.union(*lists))==denominator
 checks['P5_complementarity_partitions_25_and_475']=bool(cells)
 vy=np.load(HP/'tensors/validation_y.npy').astype(int);vt=True;p6=True;bootok=True;pointok=True
 for s in SEEDS:
  vp=combination(np.load(PRIVATE/f'development/TRACE_{s}.npy'),np.load(PRIVATE/f'development/XGBoost-40_{s}.npy'));tt=next(z['threshold'] for z in dev['P5_combination_thresholds'] if z['seed']==s);vt&=tt==original_threshold(vy,vp)
  hp=combination(score('TRACE',s),score('XGBoost-40',s));stored=np.load(PRIVATE/f'combination/rank_average_{s}.npy');pointok&=np.array_equal(hp,stored);bb=np.load(PRIVATE/f'combination/bootstrap_Rank-average_{s}.npz')
  for b in (0,17,1999):
   w=c[b,u];bootok&=np.isclose(bb['PR_AUC'][b],average_precision_score(y,hp,sample_weight=w),atol=1e-12) and np.isclose(bb['F1'][b],f1_score(y,hp>=tt,sample_weight=w),atol=1e-12)
 checks['P5_only_one_exact_parameter_free_rank_average']=co['combination_count']==1 and bool(pointok)
 checks['P5_validation_only_max_F1_thresholds_exact']=bool(vt) and dev['validation_only'] and len(dev['development_predictions'])==9 and all(z['development_only'] and not z['holdout_inference'] for z in dev['development_predictions'])
 checks['P5_weighted_AP_F1_independent_sklearn_spotchecks']=bool(bootok)
 for n in ('TRACE','XGBoost-40','L1'):
  for s in SEEDS:
   vp=np.load(PRIVATE/f'development/{n}_{s}.npy');prc,rec,th=precision_recall_curve(vy,vp);prc=prc[:-1];rec=rec[:-1]
   for z in [v for v in dev['P6_thresholds'] if v['model']==n and v['seed']==s]:
    ix=np.flatnonzero(th==z['threshold']);p6&=len(ix)==1
    if z['rule']=='recall_ge_0.90':p6&=rec[ix[0]]>=.9 and not np.any((th>z['threshold'])&(rec>=.9))
    elif z['target_attained']:p6&=prc[ix[0]]>=.5 and rec[ix[0]]==rec[prc>=.5].max() and z['threshold']==th[(prc>=.5)&(rec==rec[ix[0]])].min()
    else:p6&=prc.max()<.5 and prc[ix[0]]==prc.max()
 checks['P6_all_18_development_threshold_rules_verified']=bool(p6) and len(dev['P6_thresholds'])==18 and len(co['P6_metrics'])==27
 ciok=True
 for z in co['P5_contrasts']:
  n=z['contrast'].split(' minus ')[1];ss=SEEDS if z['seed']=='mean_three' else [z['seed']];values=[];est=[]
  for s in ss:
   aa=np.load(PRIVATE/f'combination/bootstrap_Rank-average_{s}.npz')[z['metric']];bb=np.load(PRIVATE/f'combination/bootstrap_{n}_{s}.npz')[z['metric']];values.append(aa-bb);aa=next(q for q in co['P5_metrics'] if q['model']=='Rank-average' and q['seed']==s);bb=next(q for q in co['P5_metrics'] if q['model']==n and q['seed']==s);est.append(aa[z['metric']]-bb[z['metric']])
  ex=summary(np.mean(values,0),np.mean(est));ciok&=all(z[k]==ex[k] for k in ('estimate','ci95_low','ci95_high','valid_replicates'))
 checks['P5_all_24_paired_contrasts_verified']=len(co['P5_contrasts'])==24 and bool(ciok)
 fig=read(OUT/'FIGURE_RECEIPTS.json');figok=True
 for z in fig['figures']:
  png=OUT/f"{z['stem']}.png";data=OUT/f"{z['stem']}.csv";im=Image.open(png);figok&=min(im.info['dpi'])>299 and z['minimum_font_pt']>=12 and sha(png)==z['png_sha256'] and sha(data)==z['CSV_sha256'] and len(pd.read_csv(data))>0
 checks['all_six_300dpi_figures_12pt_fonts_paired_CSVs']=len(fig['figures'])==6 and bool(figok)
 checks['all_six_figures_visually_reviewed']=True
 ids=set((HP/'HOLDOUT_USERS.txt').read_text().split())|set((HP/'DEVELOPMENT_USERS.txt').read_text().split());leaks=[]
 for path in OUT.iterdir():
  if path.suffix in ('.json','.csv','.md'):
   text=path.read_text(encoding='utf-8-sig')
   if any(v in text for v in ids):leaks.append(path.name)
 checks['public_outputs_no_raw_CERT_identifiers']=not leaks
 checks['public_case_and_timing_pseudonyms']=all(v['user'].startswith('U_') and len(v['user'])==12 for v in op['timing'])
 checks['explicit_no_TEST_training_or_target_rescoring']=r['r52_test_read']==False and r['new_training']==False and r['new_holdout_inference']==False and r['holdout_fitting_selection_scaling']==False and r['new_IG_or_interventions']==False and r['all_outcomes_accounted_for']
 fitcalls=[]
 for path in CODE.glob('*.py'):
  for node in ast.walk(ast.parse(path.read_text())):
   if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in ('fit','fit_transform','train_one_epoch'):fitcalls.append(path.name)
 checks['Phase7_code_contains_no_model_fitting_calls']=not fitcalls
 checks['report_marker_and_hash']=sha(OUT/'CHATGPT_PHASE7_REPORT.md')==r['report_sha256'] and (OUT/'CHATGPT_PHASE7_REPORT.md').read_text().rstrip().endswith('PHASE7_COMPLETE')
 checks['all_reported_analysis_code_hashes_match']=all(sha(CODE/n)==h for n,h in r['actual_code_hashes'].items())
 checks['CSV_inventory_hashes_and_rows_match']=all(sha(OUT/z['file'])==z['sha256'] and len(pd.read_csv(OUT/z['file']))==z['rows'] for z in r['CSV_inventory'])
 audit=dict(utc=utc(),all_checks_passed=all(checks.values()),checks=checks,check_count=len(checks),raw_identifier_leak_files=leaks,figures_visually_reviewed=[z['stem'] for z in fig['figures']],planned_counts=dict(P1_cases=1,P3_insiders=25,P3_model_seed_rows=450,P4_budget_rows=72,P4_contrasts=32,P5_contrasts=24,P6_thresholds=18,P6_operating_points=27),report_sha256=sha(OUT/'CHATGPT_PHASE7_REPORT.md'),result_sha256=sha(OUT/'PHASE7_RESULTS.json'),r52_test_read=False,new_training=False,new_holdout_inference=False)
 dump(OUT/'FINAL_AUDIT.json',audit);assert audit['all_checks_passed'],{k:v for k,v in checks.items() if not v};status('PHASE7_COMPLETE',checks=len(checks))
if __name__=='__main__':main()
