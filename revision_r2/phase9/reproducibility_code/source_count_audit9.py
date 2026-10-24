from common9 import *
def main():
 import pyarrow.dataset as ds
 from datetime import date
 gate();op=operational();users=(HP/'HOLDOUT_USERS.txt').read_text().splitlines();wanted=[users[i] for i in np.flatnonzero(op['insider'])];p=Path(r'C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\interval_level\r52_user_day_intervals_dense.parquet');filt=ds.field('user').isin(wanted)&(ds.field('interval_date')>=date(2010,1,2))&(ds.field('interval_date')<=date(2011,4,10));df=ds.dataset(p).to_table(columns=['user','malicious_event_count'],filter=filt).to_pandas();g=df.groupby('user').malicious_event_count.sum();target=read(OUT/'L7_MALICIOUS_SOURCE_TARGETS_FROZEN.json');records=[]
 for row in target['rows']:
  i=int(np.flatnonzero(op['user']==row['user'])[0]);count=int(g.loc[users[i]]);records.append(dict(user=row['user'],daily_labelled_event_total=count,source_labelled_event_total=row['malicious_events'],equal=count==row['malicious_events']))
 result=dict(utc=utc(),all_checks_passed=all(z['equal'] for z in records),records=records,target_choice_sha256=sha(OUT/'L7_MALICIOUS_SOURCE_TARGETS_FROZEN.json'),projected_columns=['user','malicious_event_count'],rows=len(df),r52_test_read=False);dump(OUT/'MALICIOUS_SOURCE_COUNT_AUDIT.json',result);assert result['all_checks_passed'];print('MALICIOUS_SOURCE_COUNTS_RECONCILE_ALL25',sum(z['daily_labelled_event_total'] for z in records),flush=True)
if __name__=='__main__':main()
