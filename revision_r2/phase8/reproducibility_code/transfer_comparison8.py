"""Post-monitor reader of existing aggregate results; never reads label arrays."""
from common8 import *
def main():
 monitor=OUT/'Q5_MONITOR_FROZEN_BEFORE_TRANSFER_COMPARISON.json';assert monitor.exists();source=Path(r'C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor024-r61\review\editor024_r61_final_confirmation\EDITOR024_R61_PRIMARY_SUMMARY.csv');data=pd.read_csv(source);d=data[(data.model=='TA2')&(data.view=='COMPLETED_WINDOW')];assert set(d.seed)==set(OLD) and len(d)==3
 record=dict(release='r6.1',block='historical_original_TRACE_all_user_r52',PR_AUC=float(d.PR_AUC.mean()),F1=None,precision=None,recall=None,model='TRACE',view='COMPLETED_WINDOW',seeds=list(OLD),population_note='Existing all-user r5.2 checkpoint results; different from Phase4 development-user checkpoint',source=str(source),source_sha256=sha(source))
 supplement=dict(utc=utc(),reason='The shared cross-version portfolio has no r6.1 rows; use its separate existing primary aggregate summary after the monitor freeze.',monitor_sha256=sha(monitor),monitor_utc=read(monitor)['utc'],record=record,per_seed_records=d.to_dict('records'),raw_label_arrays_read=False,monitor_or_predictions_recomputed=False);dump(OUT/'Q5_KNOWN_R61_TRANSFER_SUPPLEMENT.json',supplement)
 known=read(OUT/'Q5_RESULTS.json')['known_transfer_summary'];csv('Q5_KNOWN_TRANSFER_COMPARISON.csv',known+[record]);print('R61_EXISTING_AGGREGATE_COMPARISON_ADDED',record['PR_AUC'],flush=True)
if __name__=='__main__':main()
