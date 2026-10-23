from common7 import *
def fmt(v):
 if v is None or isinstance(v,float) and not np.isfinite(v):return '—'
 if isinstance(v,(list,tuple)):return ', '.join(map(str,v))
 if isinstance(v,bool):return 'yes' if v else 'no'
 if isinstance(v,(float,np.floating)):return f'{v:.6g}'
 return str(v)
def table(rows,cols=None):
 if isinstance(rows,pd.DataFrame):rows=rows.replace({np.nan:None}).to_dict('records')
 if not rows:return 'No eligible rows.\n'
 if cols is None:cols=[(k,k.replace('_',' ')) for k in rows[0]]
 return '\n'.join(['| '+' | '.join(v for k,v in cols)+' |','| '+' | '.join('---' for k,v in cols)+' |']+['| '+' | '.join(fmt(r.get(k)).replace('|','/').replace('\n',' ') for k,v in cols)+' |' for r in rows])+'\n'
def main():
 op=read(OUT/'OPERATIONAL_RESULTS.json');a=read(OUT/'CASE_ATTRIBUTION_RESULTS.json');co=read(OUT/'COMBINATION_SENSITIVITY_RESULTS.json');dev=read(OUT/'DEVELOPMENT_THRESHOLDS_FROZEN.json');am=read(OUT/'AMENDMENT7_RECEIPT.json');fig=read(OUT/'FIGURE_RECEIPTS.json');m,o=metadata()
 means=[]
 for n in NAMES.values():
  rr=[r for r in op['model_delay_summary'] if r['model']==n];means.append(dict(model=n,seed='arithmetic_mean_of_seed_summaries',**{k:float(np.mean([r[k] for r in rr])) for k in ('insiders_detected','noninsiders_flagged','delay_n','median_delay_days','delay_Q1','delay_Q3')}))
 csv('P3_MODEL_SEED_MEANS.csv',means)
 failures=[dict(stage='cases7.py first descriptive calculation',status='CORRECTED',reason='int16 cluster index multiplied by 464 overflowed before the user-day activity summary was exported; changed only that index arithmetic to int64, added explicit range and count guards, and reran cached-data analysis. No training, target inference or explanation experiment was repeated.'),dict(stage='first final inventory audit',status='CORRECTED',reason='The CSV inventory included its own earlier hash after report regeneration, creating a self-reference. Excluded the inventory file from its own content list; all numerical, source-integrity, privacy and figure checks had already passed. Regenerated only the report/results/inventory and reran the audit.')]
 limitations=[
 'False-alarm IG is available for only 3/562, 5/724 and 5/648 non-insider false-alarm windows in seeds 42/52/62 (0.53%, 0.69%, 0.77%). Full false-alarm-window IG means cannot be computed from the permitted saved explanations. Those full-population attribution means are unavailable; the reported saved-sample means are descriptive and cannot establish which source drives all false alarms. Counts, episodes and activity features use the full relevant cohort.',
 'Saved 50-interval IG is approximate. For the missed-case peak windows, relative completeness residuals are 0.234, 0.185 and 1.729; the seed-62 error exceeds the explained logit difference. Signed feature values and absolute shares are reported transparently, without treating them as an exact decomposition or causal explanation. P2 completeness diagnostics are also reported.',
 'An early alert on an insider can occur long before any malicious day. First-any-alert delay and first-malicious-window detection delay are reported separately. Only the latter determines insider detection, and undetected cases are excluded, with counts, from detected-only delay summaries.',
 'A completed-window positive means some malicious day in the preceding 20 days, not necessarily an action on the alert end-day. P4 reports both completed-window and malicious-endpoint-day precision. The 38 unscorable start-of-period days have no policy alerts and are explicitly marked unavailable in daily exports.',
 'The missed insider has an all-day non-malicious feature median of zero because inactive days dominate that descriptive reference. This is not evidence that malicious activity resembles ordinary active-day behaviour. The requested own-user median is used only for description, never model scaling or threshold selection.',
 'P5 is the sole authorised transductive transformation: ranks are calculated separately within development VALIDATION and within HOLDOUT. Its frozen numeric threshold has a split-relative percentile interpretation and is not a calibrated probability or an online alert rule.',
 'P4 keeps the original daily ranking/policy fixed under user-cluster resampling. Its CIs describe user variation conditional on that fixed policy; they do not rerank duplicate users to construct a new daily competition. Count contrasts use resampled user multiplicities in insider-count units.',
 'P4 and P5 CIs are exploratory, unadjusted and not simultaneous. CIs compatible with zero do not show equivalence. No additional combination, model fit, threshold tuning on HOLDOUT or r5.2 TEST access is performed.'
 ]
 lines=['# Phase 7: operational and case analyses on 500 unseen users','',f'Completed {utc()}. Exploratory/descriptive analyses of frozen Phase 4 models and saved predictions. r5.2 TEST remains sealed. HOLDOUT users are evaluation only.','',
 '## Findings','',
 'TRACE detects 24 of 25 insiders in every seed. The same scenario-2 insider, U_488844ba74, is missed in all three; this is also the complete union of insiders missed in any TRACE seed. XGBoost-40 detects this case in all three seeds, while TRACE catches other insiders missed by XGBoost-40. The union of their frozen-threshold detection sets covers all 25 insiders in every seed; a union is a complementarity description, not an additional deployed combination.',
 '', 'TRACE flags 23, 27 and 28 non-insiders, versus 6, 8 and 22 for XGBoost-40. At B=1 daily alert, TRACE catches 13, 10 and 13 insiders; XGBoost-40 catches 13, 12 and 13. At B=10, TRACE catches 25, 24 and 24; XGBoost-40 catches 24 in every seed. Median malicious-window detection delay is zero days among detected insiders for both models, with undetected insiders retained separately.',
 '', 'The only tried rank-average combination has mean AP 0.812170 and F1 0.747533, versus TRACE 0.712201/0.477874 and XGBoost-40 0.824003/0.747053. The mean AP difference is +0.099970 versus TRACE (95% user-cluster CI 0.007574 to 0.218996) and -0.011833 versus XGBoost-40 (-0.112486 to 0.092212). These unadjusted exploratory results do not show improvement over XGBoost-40. All seedwise results and count/F1 contrasts follow below.',
 '', '## Amendment 7 and execution boundary','',f"SHA-256 `{am['sha256']}` over {am['hashed_bytes']} preregistration bytes before its receipt, UTC {am['utc']}. The prior {am['previous_bytes']}-byte prefix is preserved with SHA-256 `{am['previous_sha256']}`. [Amendment receipt](AMENDMENT7_RECEIPT.json). Phase 6C was complete and its final audit passed before this amendment; its report hash remains `{am['phase6c_report_sha256']}`.",'',
 (R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md').read_bytes()[am['previous_bytes']:].decode('utf-8'),'',
 'No model is retrained and no HOLDOUT prediction pass is repeated. The original 18 model-seed prediction arrays, checkpoints and thresholds are reused. Only the six frozen TRACE/L1 checkpoints require development-VALIDATION inference for the declared thresholds; XGBoost validation predictions are already saved. All nine development score arrays and all 21 P5/P6 thresholds were frozen before these policies were evaluated on HOLDOUT. A GPU allocator cap of 35%, small batches, cooperative pauses and two CPU threads share resources without controlling another chat.',
 '', 'Primary cohort: 213,000 completed 20-day windows, 1,172 positive windows, 500 unseen users (25 insiders, 475 non-insiders), permitted TRAIN+VALIDATION dates 2010-01-02 through 2011-04-10. Endpoints are available on 426 days. No cross-period windows are created. An alert uses score >= frozen threshold; insider detection requires an alert on a malicious-containing completed window. Non-insider false alarms use any alert. Global ranks descend across all 213,000 windows for the same model/seed, with average ranks on ties.',
 '', '## P1: missed-insider case study','',table(a['cases']),
 'This user has 23 malicious days over a 45-day span and 64 malicious-containing windows. The peak TRACE scores remain below threshold in all seeds. The all-day non-malicious medians are zero; therefore the activity comparison does not support a claim that the malicious days resemble the normal active-day profile. All 13 daily feature values, own non-malicious medians and differences are shown in the detailed table below.',
 '',table(a['peak_windows']),table(a['peak_all_windows']),
 'The highest overall scores are explicitly separated from the highest malicious-containing scores. TRACE alerts outside the labelled malicious-containing windows for this user; those alerts do not count as malicious detection.',
 '',table(a['other_model_detection'],[('model','Other model'),('seed','Seed'),('detected','Detected'),('first_malicious_window_alert_date','First malicious-window alert'),('detection_delay_days','Delay days'),('first_malicious_window_alert_rank','Global rank'),('threshold','Frozen threshold')]),
 '', 'Model-relative explanation: the peak malicious-window logits are -0.890, -1.195 and -1.186, below threshold logits +0.241, +0.241 and -0.490. Their attention masses on malicious days are 98.6%, 16.1% and 76.4%, against malicious-day fractions 70%, 5% and 70% in the selected windows. Thus low attention to malicious days is not a consistent explanation of the miss. The frozen mean-tree readout supplies insufficient positive logit at these operating points despite the observed activity and attention. The device-activity flag has a negative signed IG sum in all three peak windows, but the large completeness errors prevent an exact feature-based or causal explanation. This is a statement about the frozen models, not about the person’s intent.',
 '',table(a['explanation_diagnostics']),
 '![Case score timeline](figure_P1_timeline_U_488844ba74.png)','[Timeline source data](figure_P1_timeline_U_488844ba74.csv). Each malicious day is shaded. [Every case window score](P1_ALL_CASE_WINDOW_SCORES.csv); [malicious-containing windows only](P1_MALICIOUS_CONTAINING_WINDOW_SCORES.csv).',
 '', '![Saved peak-window explanations](figure_P1_explanations_U_488844ba74.png)','[Explanation figure data](figure_P1_explanations_U_488844ba74.csv). Dark tree bars are the top three by absolute reference-centred contribution; references come from development TRAIN. All 13 IG features, all 20 attention days and all eight trees are included below.',
 '', '### P1 daily features on all malicious days','',table(a['malicious_day_features']),
 '### P1 attention over 20 days per peak window','',table(a['attention']),
 '### P1 complete IG feature rankings','',table(a['IG_features']),
 '### P1 complete tree contributions','',table(a['tree_contributions']),
 '### P1 every malicious-containing window score','',table(pd.read_csv(OUT/'P1_MALICIOUS_CONTAINING_WINDOW_SCORES.csv')),
 '', '## P2: false-alarm characterisation','',table(op['P2_counts']),table(op['P2_Jaccard']),
 'Jaccard is intersection/union; empty versus empty is defined as one. The table includes all within-model seed pairs and all nine between-model seed pairs. False-alarm users are non-insiders only. [Full user-level alert counts](P2_ALERTS_PER_USER.csv), [all alert episodes](P2_ALERT_EPISODES.csv) and [every permitted calendar day](P2_ALERTS_PER_DAY.csv) retain pseudonyms and explicit scorable status.',
 '',table(a['P2_coverage']),
 'Only the saved explanation sample is used. Device has the largest false-alarm source share in each seed (about 0.30–0.38), while file has the largest true-positive share (about 0.40–0.52). This difference describes 3/5/5 saved false-alarm windows, below 0.8% coverage, and does not establish a population driver. Shared/activity combines total_events, duration and is_active_day; every source combines its count and activity flag. All shares use absolute IG normalized within each window before averaging.',
 '', '![False-alarm counts and saved-sample source shares](figure_P2_false_alarms.png)','[Figure data](figure_P2_false_alarms.csv). Full-cohort counts and sampled attribution have different coverage.',
 '', '### P2 mean IG per feature and per source','',table(a['P2_attribution']),
 '### P2 mean daily activity features','',table(a['P2_activity']),
 'The window-day mean counts every occurrence of a day in an overlapping alerting window. The unique-user-day mean counts a user/date once within the respective group. Both use the full eligible false-alarm/true-positive window group, not just the explanation sample. Counts and duration retain their original aggregate units; flags are proportions.',
 '', '## P3: per-insider detection timing','',
 'The [25-row wide timing table](P3_INSIDER_TIMING_25_ROWS.csv) contains every requested model/seed column for all 25 insiders. The same entries appear below, grouped by model to stay readable, and in [long format](P3_INSIDER_TIMING_LONG.csv). In each seed cell, D means detected on a malicious window; TP gives detection delay/global rank; ANY gives first-any-alert delay/global rank, which can be negative. A pre-onset ANY alert is not a true-positive detection. Missing delay/rank stays unavailable.',
 '']
 for n in NAMES.values():
  rows=[]
  for user in o['user'][o['insider']]:
   rr=[r for r in op['timing'] if r['model']==n and r['user']==user];row=dict(user=user,scenario=rr[0]['scenario'],malicious_days=rr[0]['malicious_days'])
   for r in rr:row[f"seed_{r['seed']}"]=f"D={fmt(r['detected'])}; TP={fmt(r['detection_delay_days'])}d/{fmt(r['first_malicious_window_alert_rank'])}; ANY={fmt(r['first_any_alert_delay_days'])}d/{fmt(r['first_any_alert_rank'])}"
   rows.append(row)
  lines+=['### '+n+' (all 25 insiders)','',table(rows)]
 lines+=['### P3 model/seed delay summaries','',table(op['model_delay_summary']),table(means),
 'Median and quartiles use detected insiders only; delay_n states the denominator. The arithmetic seed summary averages the three seedwise quantities, including quantiles; it is not a new pooled delay distribution. First-any summaries retain non-malicious/pre-onset alerts and are shown separately. Negative delays can extend farther back than 19 days; the long CSV records whether the first-any alert falls within the 19-day pre-onset window. These are whole permitted-period observations, not a prospective early-warning claim.',
 '', '### P3 per-scenario summaries','',table(op['scenario_summary']),
 '', '## P4: fixed daily alert budgets','',
 'Each eligible day alerts exactly the top B users by their maximum window score ending that day. There is one completed endpoint per user/day here, so no duplicate-user aggregation changes the score. Ties are resolved by pseudonym ascending. Across 426 days, per-seed workload is 426, 852, 2,130 and 4,260 alerts for B=1/2/5/10. Precision uses completed-window labels; endpoint-day precision is also shown. No threshold or budget is selected from HOLDOUT.',
 '',table(op['P4_budget_results']),
 '![Fixed daily budgets](figure_P4_daily_budget.png)','[Figure data](figure_P4_daily_budget.csv). [All selected user-day alerts](P4_SELECTED_USER_DAY_ALERTS.csv) retain the source window, label and pseudonym.',
 '', '### P4 all paired count contrasts','',table(op['P4_contrasts']),
 'All 32 rows are preserved: two comparator contrasts, four budgets, each seed plus the arithmetic three-seed count mean. Bootstrap weights resample all 500 users with seed 42 and 2,000 replicates; the two sides share multiplicities. These CIs condition on the frozen daily policy and remain unadjusted.',
 '', '## P5: complementarity and the single rank average','',table(op['P5_complementarity']),
 'The insiders’ "neither" cell contains zero users in each seed: the union of frozen-threshold detections covers 25/25. This does not imply that the predeclared rank-average threshold preserves that union. The non-insider cells partition all 475 users; neither includes users flagged by neither model.',
 '',table(dev['P5_combination_thresholds']),table(co['P5_metrics']),
 'The combination is exactly the equal mean of within-split average ranks divided by split N. The threshold uses the original TRACE/XGBoost grid+quantile max-F1 rule with first maximum on development VALIDATION. No other combination is evaluated. Seed means average metrics, never probabilities.',
 '', '![One rank-average combination](figure_P5_rank_average.png)','[Figure data](figure_P5_rank_average.csv).',
 '', '### P5 all paired combination contrasts','',table(co['P5_contrasts']),
 '', '## P6: threshold-rule sensitivity','',
 'Recall ≥0.90 chooses the highest observed development-VALIDATION score threshold attaining the target. Precision ≥0.50 chooses maximal recall among eligible thresholds, then the lowest threshold; if unattainable, maximal precision/recall then lowest threshold is used and labelled closest attainable. The achieved development values and all frozen thresholds follow. HOLDOUT results are reported for both rules beside the original max-F1 threshold, without choosing an operating point from these results.',
 '',table(dev['P6_thresholds']),table(co['P6_metrics']),
 '![Validation-derived threshold sensitivity](figure_P6_threshold_rules.png)','[Figure data](figure_P6_threshold_rules.csv). A higher insider catch can entail many more non-insider users flagged; the full precision/recall table gives the corresponding window metrics.',
 '', '## P2 full alert-episode accounting','',
 'An episode is a maximal run of consecutive alerting calendar endpoints for a user, split at period boundaries. Episode starts per day and all alert-day counts are reported; the 38 days without completed windows stay unavailable, rather than zero-scored. User rows include all 500 users with the non-insider flag so zero-episode users remain explicit.',
 '', '### P2 alert counts and episodes per user','',table(pd.read_csv(OUT/'P2_ALERTS_PER_USER.csv')),
 '### P2 alert counts and episode starts per calendar day','',table(pd.read_csv(OUT/'P2_ALERTS_PER_DAY.csv')),
 '### P2 every alert episode','',table(pd.read_csv(OUT/'P2_ALERT_EPISODES.csv')),
 '', '## Skips, failures, interpretations and deviations','',table(failures),'']
 lines+=['- '+v for v in limitations]
 lines+=['','No model/seed, budget, threshold rule or planned contrast was dropped. There were no training runs, target inference runs, new IG computations or new interventions. All case explanation components were present. The unavailable full-population false-alarm IG means and the corrected descriptive-index failure are explicitly accounted for above.','',
 '## Integrity and deliverables','',
 '[PHASE7_RESULTS.json](PHASE7_RESULTS.json) collects all six blocks, thresholds, figures, source hashes, outputs and limitations. [SOURCE_INTEGRITY_MANIFEST.json](SOURCE_INTEGRITY_MANIFEST.json) records original artifacts; [DEVELOPMENT_THRESHOLDS_FROZEN.json](DEVELOPMENT_THRESHOLDS_FROZEN.json) records validation-only decisions. [FINAL_AUDIT.json](FINAL_AUDIT.json) verifies numerical spot checks, all planned counts, original-source hashes, Amendment 7, pseudonyms, figures and completion. The Phase 6C audit remains historical: Amendment 7 legitimately appends the shared preregistration, while preserving the entire Amendment 6 prefix and completed Phase 6C report/results.','']
 inventory=[]
 for p in sorted(OUT.glob('*.csv')):
  if p.name=='CSV_DELIVERABLE_INVENTORY.csv':continue
  df=pd.read_csv(p);inventory.append(dict(file=p.name,rows=len(df),columns=len(df.columns),sha256=sha(p)))
 csv('CSV_DELIVERABLE_INVENTORY.csv',inventory)
 lines+=['### CSV inventory','',table([r|dict(file=f"[{r['file']}]({r['file']})") for r in inventory]),'', 'PHASE7_COMPLETE']
 report=OUT/'CHATGPT_PHASE7_REPORT.md';report.write_text('\n'.join(lines)+'\n',encoding='utf-8')
 dump(OUT/'PHASE7_RESULTS.json',dict(utc=utc(),amendment7=am,P1_P2_cases_and_attribution=a,P2_P3_P4_P5_operational=op,P5_P6_combination_and_sensitivity=co,development_thresholds=dev,figures=fig,failures=failures,skips_and_limitations=limitations,CSV_inventory=inventory,source_integrity_manifest_sha256=sha(OUT/'SOURCE_INTEGRITY_MANIFEST.json'),actual_code_hashes={p.name:sha(p) for p in CODE.glob('*.py')},report_sha256=sha(report),r52_test_read=False,holdout_fitting_selection_scaling=False,threshold_population='1500 development users VALIDATION only',new_holdout_inference=False,new_training=False,new_IG_or_interventions=False,all_outcomes_accounted_for=True,complete=True));status('REPORT_WRITTEN')
if __name__=='__main__':main()
