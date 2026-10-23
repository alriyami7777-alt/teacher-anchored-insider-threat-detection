from common7 import *
from itertools import combinations,product
def delay_summary(values):
 a=np.asarray([v for v in values if v is not None],float)
 return dict(delay_n=len(a),median_delay_days=float(np.median(a)) if len(a) else None,delay_Q1=float(np.quantile(a,.25)) if len(a) else None,delay_Q3=float(np.quantile(a,.75)) if len(a) else None)
def first(rows,dates,p,ranks,firstday):
 if not len(rows):return dict(date=None,delay_days=None,rank=None,score=None)
 i=int(rows[np.lexsort((rows,dates[rows]))[0]])
 return dict(date=str(dates[i]),delay_days=int((dates[i]-firstday).astype(int)),rank=float(ranks[i]),score=float(p[i]))
def main():
 assert (OUT/'DEVELOPMENT_THRESHOLDS_FROZEN.json').exists()
 m,o=metadata();y=m['y'];u=m['cluster'];dates=o['rowdate'];cal=o['calendar'];di=(dates-cal[0]).astype(int);insider=o['insider'];users=o['user'];mapping=pd.read_csv(P5/'C_INSIDER_SCENARIO_MAP.csv',dtype={'scenario':str});scenarios=dict(zip(mapping.user,mapping.scenario));inds=np.flatnonzero(insider)
 assert len(inds)==25 and all(o['daily_y'][i].any() for i in inds)
 timing=[];summaryrows=[];scenrows=[];eps=[];dailyrows=[];userrows=[];sets={};budgets=[];selected_rows=[];budgetdet={};rankdir=PRIVATE/'ranks';rankdir.mkdir(exist_ok=True)
 for n in NAMES.values():
  for s in SEEDS:
   p=score(n,s);t=spec(n,s)['threshold'];flag=p>=t;ranks=rankdata(-p,method='average');np.save(rankdir/f'{n}_{s}.npy',ranks);det=detected(m,p,t);fa=flagged(m,o,p,t);sets[n,s]=dict(detected=set(users[det]),false_alarm=set(users[fa]))
   for i in inds:
    firstday=cal[np.flatnonzero(o['daily_y'][i])[0]];positive=np.flatnonzero((u==i)&flag&(y==1));anyalert=np.flatnonzero((u==i)&flag);a=first(anyalert,dates,p,ranks,firstday);b=first(positive,dates,p,ranks,firstday)
    timing.append(dict(user=users[i],scenario=scenarios[users[i]],model=n,seed=s,malicious_days=int(o['daily_y'][i].sum()),first_malicious_day=str(firstday),detected=bool(len(positive)),first_any_alert_date=a['date'],first_any_alert_delay_days=a['delay_days'],first_any_alert_rank=a['rank'],first_any_alert_score=a['score'],pre_onset_within_19_days=bool(a['delay_days'] is not None and -19<=a['delay_days']<0),first_malicious_window_alert_date=b['date'],detection_delay_days=b['delay_days'],first_malicious_window_alert_rank=b['rank'],first_malicious_window_alert_score=b['score'],threshold=t))
   tr=[r for r in timing if r['model']==n and r['seed']==s];summaryrows.append(dict(model=n,seed=s,**ops(m,o,p,t),**delay_summary([r['detection_delay_days'] for r in tr]),**{f'first_any_{k}':v for k,v in delay_summary([r['first_any_alert_delay_days'] for r in tr]).items()}))
   for scenario in sorted(set(scenarios.values())):
    rows=[r for r in tr if r['scenario']==scenario];scenrows.append(dict(model=n,seed=s,scenario=scenario,insiders=len(rows),insiders_detected=sum(r['detected'] for r in rows),**delay_summary([r['detection_delay_days'] for r in rows])))
   if n in ('TRACE','XGBoost-40'):
    current=[]
    for i in range(500):
     rr=np.flatnonzero((u==i)&flag);groups=[]
     for part in ('train','validation'):
      a=rr[m['partition'][rr]==part]
      if len(a):groups.extend(np.split(a,np.flatnonzero(np.diff(dates[a]).astype(int)>1)+1))
     for g in groups:
      r=dict(model=n,seed=s,user=users[i],noninsider=bool(not insider[i]),partition=str(m['partition'][g[0]]),start_date=str(dates[g[0]]),end_date=str(dates[g[-1]]),alerting_user_days=len(g),malicious_window_alerts=int(y[g].sum()),peak_score=float(p[g].max()));eps.append(r);current.append(r)
     userrows.append(dict(model=n,seed=s,user=users[i],noninsider=bool(not insider[i]),flagged=bool(len(rr)),alert_windows=len(rr),alert_user_days=len(np.unique(dates[rr])),alert_episodes=len(groups),max_score=float(p[u==i].max()),threshold=t))
    for d in cal:
     scorable=bool((dates==d).any());rr=np.flatnonzero((dates==d)&flag);non=rr[~insider[u[rr]]];starts=[r for r in current if r['start_date']==str(d)];dailyrows.append(dict(model=n,seed=s,date=str(d),scorable=scorable,alert_user_days=len(rr) if scorable else None,noninsider_alert_user_days=len(non) if scorable else None,episode_starts=len(starts) if scorable else None,noninsider_episode_starts=sum(r['noninsider'] for r in starts) if scorable else None))
   # One endpoint per user/day is expected in this completed-window cohort.
   policy={b:[] for b in (1,2,5,10)}
   for d in np.unique(dates):
    rr=np.flatnonzero(dates==d);assert len(rr)==500 and len(np.unique(u[rr]))==500
    order=rr[np.lexsort((users[u[rr]],-p[rr]))]
    for b in policy:
     take=order[:b];policy[b].extend(take.tolist())
     for j in take:selected_rows.append(dict(model=n,seed=s,budget=b,date=str(d),user=users[u[j]],score=float(p[j]),window_positive=int(y[j]),endpoint_positive=int(m['endpoint'][j]),source_row=int(j)))
   for b,rr in policy.items():
    rr=np.array(rr);dc=np.bincount(u[rr],weights=y[rr],minlength=500)>0;budgetdet[n,s,b]=dc.astype(float);delays=[]
    for i in inds:
     a=rr[(u[rr]==i)&(y[rr]==1)]
     if len(a):delays.append(int((dates[a].min()-cal[np.flatnonzero(o['daily_y'][i])[0]]).astype(int)))
    budgets.append(dict(model=n,seed=s,budget=b,insiders_caught=int(dc.sum()),insiders_total=25,median_days_to_first_catch=float(np.median(delays)) if delays else None,caught_delay_n=len(delays),user_day_precision=float(y[rr].mean()),malicious_endpoint_day_precision=float(m['endpoint'][rr].mean()),total_alerts=len(rr),eligible_days=len(np.unique(dates)),unique_users_alerted=len(np.unique(u[rr])),tie_rule='pseudonym ascending',label_rule='max daily label within completed 20-day window'))
   status('OPERATIONAL_MODEL_COMPLETE',model=n,seed=s)
 # P2 six sets: within-model seed pairs and all nine between-model seed pairs.
 overlap=[]
 for a,b in combinations(sets,2):
  if a[0] not in ('TRACE','XGBoost-40') or b[0] not in ('TRACE','XGBoost-40'):continue
  x=sets[a]['false_alarm'];z=sets[b]['false_alarm'];overlap.append(dict(model_a=a[0],seed_a=a[1],model_b=b[0],seed_b=b[1],users_a=len(x),users_b=len(z),intersection=len(x&z),union=len(x|z),Jaccard=len(x&z)/len(x|z) if x|z else 1.))
 fa_counts=[dict(model=n,seed=s,noninsiders_flagged=len(sets[n,s]['false_alarm']),noninsiders_total=475,pseudonyms=sorted(sets[n,s]['false_alarm'])) for n in ('TRACE','XGBoost-40') for s in SEEDS]
 # P5 complete partitions of the 25 insider / 475 non-insider universes.
 complements=[]
 for s in SEEDS:
  for population,key,universe in [('insiders','detected',set(users[insider])),('noninsiders','false_alarm',set(users[~insider]))]:
   a=sets['TRACE',s][key];b=sets['XGBoost-40',s][key]
   for cell,vals in [('TRACE_only',a-b),('XGBoost-40_only',b-a),('both',a&b),('neither',universe-(a|b))]:complements.append(dict(seed=s,population=population,cell=cell,users=len(vals),denominator=len(universe),pseudonyms=sorted(vals)))
 c=np.load(P4P/'BOOTSTRAP_USER_MULTIPLICITIES.npy');contrasts=[]
 for b in (1,2,5,10):
  for other in ('XGBoost-40','L1'):
   delta=[];est=[]
   for s in SEEDS:
    d=budgetdet['TRACE',s,b]-budgetdet[other,s,b];bb=c@d;ee=d.sum();delta.append(bb);est.append(ee);contrasts.append(dict(contrast=f'TRACE minus {other}',budget=b,seed=s,metric='insiders_caught_count',**summary(bb,ee)))
   contrasts.append(dict(contrast=f'TRACE minus {other}',budget=b,seed='mean_three',metric='insiders_caught_count',**summary(np.mean(delta,0),np.mean(est))))
 assert len(contrasts)==32
 wide=[]
 for i in inds:
  rows=[r for r in timing if r['user']==users[i]];row=dict(user=users[i],scenario=scenarios[users[i]],malicious_days=int(o['daily_y'][i].sum()),first_malicious_day=rows[0]['first_malicious_day'])
  for r in rows:
   for k in ('detected','first_any_alert_date','first_any_alert_delay_days','first_any_alert_rank','first_malicious_window_alert_date','detection_delay_days','first_malicious_window_alert_rank'):row[f"{r['model']}_seed{r['seed']}_{k}"]=r[k]
  wide.append(row)
 for name,rows in [('P3_INSIDER_TIMING_LONG.csv',timing),('P3_INSIDER_TIMING_25_ROWS.csv',wide),('P3_MODEL_DELAY_SUMMARY.csv',summaryrows),('P3_SCENARIO_SUMMARY.csv',scenrows),('P2_FALSE_ALARM_COUNTS.csv',fa_counts),('P2_FALSE_ALARM_JACCARD.csv',overlap),('P2_ALERT_EPISODES.csv',eps),('P2_ALERTS_PER_USER.csv',userrows),('P2_ALERTS_PER_DAY.csv',dailyrows),('P4_DAILY_BUDGET_RESULTS.csv',budgets),('P4_SELECTED_USER_DAY_ALERTS.csv',selected_rows),('P4_COUNT_CONTRASTS.csv',contrasts),('P5_COMPLEMENTARITY.csv',complements)]:csv(name,rows)
 np.savez_compressed(PRIVATE/'P4_detection_vectors.npz',**{f'{n}_{s}_{b}':v for (n,s,b),v in budgetdet.items()})
 dump(OUT/'OPERATIONAL_RESULTS.json',dict(utc=utc(),timing=timing,timing_25_rows=wide,model_delay_summary=summaryrows,scenario_summary=scenrows,P2_counts=fa_counts,P2_Jaccard=overlap,P2_episode_rows=len(eps),P2_user_rows=len(userrows),P2_daily_rows=len(dailyrows),P4_budget_results=budgets,P4_contrasts=contrasts,P4_selected_alert_rows=len(selected_rows),P5_complementarity=complements,models=list(NAMES.values()),new_holdout_inference=False));status('OPERATIONAL_ANALYSIS_COMPLETE',timing_rows=len(timing),budget_rows=len(budgets),contrasts=len(contrasts))
if __name__=='__main__':main()
