from p5common import *
import pandas as pd
def main():
    import pyarrow.dataset as ds
    from datetime import date
    f=check_frozen();co=holdout();u=co['cluster'];y=co['y'];endpoint=co['endpoint'];part=co['partition'];rowdates=np.empty(len(y),dtype='datetime64[D]')
    train_dates=np.arange('2010-01-21','2011-02-19',dtype='datetime64[D]');val_dates=np.arange('2011-03-10','2011-04-11',dtype='datetime64[D]');assert len(train_dates)==394 and len(val_dates)==32
    users=(HPRIVATE/'HOLDOUT_USERS.txt').read_text(encoding='utf-8').splitlines();pseudos=[pseudo(s) for s in users]
    for ui in range(500):
        a=(u==ui)&(part=='train');b=(u==ui)&(part=='validation');assert a.sum()==394 and b.sum()==32;rowdates[a]=train_dates;rowdates[b]=val_dates;assert set(co['user'][u==ui])=={pseudos[ui]}
    calendar=np.arange('2010-01-02','2011-04-11',dtype='datetime64[D]');assert len(calendar)==464
    path=Path(r'C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\interval_level\r52_user_day_intervals_dense.parquet')
    filt=ds.field('user').isin(users)&(ds.field('interval_date')>=date(2010,1,2))&(ds.field('interval_date')<=date(2011,4,10))
    frame=ds.dataset(path,format='parquet').to_table(columns=['user','interval_date','is_malicious_interval'],filter=filt).to_pandas();frame['interval_date']=pd.to_datetime(frame.interval_date);frame=frame.sort_values(['user','interval_date'])
    assert len(frame)==232000 and frame.interval_date.max()<=pd.Timestamp('2011-04-10');daily=np.empty((500,464),np.int8)
    for ui,user in enumerate(users):
        g=frame[frame.user==user];assert np.array_equal(g.interval_date.to_numpy().astype('datetime64[D]'),calendar);daily[ui]=g.is_malicious_interval.to_numpy()
    scen={s:set() for s in users};folder=Path(r'C:\PhD\07_Projects\cert-r42-feasibility\data\raw\answers')
    for number in range(1,5):
        for p in (folder/f'r5.2-{number}').glob('r5.2-*.csv'):
            user=p.stem.split('-')[-1]
            if user in scen:scen[user].add(number)
    insider=np.array([bool(scen[s]) for s in users]);assert insider.sum()==25 and (~insider).sum()==475
    np.savez_compressed(PRIVATE/'HOLDOUT_OPERATIONAL_METADATA.npz',rowdate=rowdates,calendar=calendar,daily_y=daily,insider=insider,user=np.array(pseudos))
    mapping=[dict(user=pseudos[i],scenario=';'.join(map(str,sorted(scen[s]))),allowed_malicious_days=int(daily[i].sum())) for i,s in enumerate(users) if insider[i]];save_csv('C_INSIDER_SCENARIO_MAP.csv',mapping)
    summary=[];perinsider=[];dailyrows=[];episodes=[];scenario_rows=[];triage=[]
    specs=[s for s in f['models']['development'] if s['model'] in ('TA2','XGBoost_40','F00','L1','Transformer')]
    for spec in specs:
        n=spec['model'];seed=spec['seed'];label=model_name(n);p=base_score(spec);flag=p>=spec['threshold'];detected=[];delays=[];model_eps=[]
        for ui,user in enumerate(users):
            mask=u==ui;dates=rowdates[mask];pp=p[mask];ff=flag[mask];yy=y[mask]
            if insider[ui]:
                positive_flag=ff&(yy==1);isdet=bool(positive_flag.any());detected.append((ui,isdet));firstday=calendar[np.flatnonzero(daily[ui])[0]] if daily[ui].any() else None;firstalert=dates[positive_flag].min() if isdet else None;delay=int((firstalert-firstday).astype(int)) if isdet else None
                if delay is not None:delays.append(delay)
                perinsider.append(dict(model=label,seed=seed,user=pseudos[ui],scenario=';'.join(map(str,sorted(scen[user]))),positive_windows=int(yy.sum()),allowed_malicious_days=int(daily[ui].sum()),detected=isdet,first_allowed_malicious_day=str(firstday) if firstday is not None else None,first_positive_window_alert_day=str(firstalert) if firstalert is not None else None,delay_days=delay,eligible_positive_windows=bool(yy.any())))
            alertdates=np.sort(dates[ff])
            if len(alertdates):
                groups=np.split(alertdates,np.flatnonzero(np.diff(alertdates).astype(int)>1)+1)
                for group in groups:
                    lo,hi=group[0],group[-1];mal=bool(daily[ui,(calendar>=lo)&(calendar<=hi)].any());row=dict(model=label,seed=seed,user=pseudos[ui],start_date=str(lo),end_date=str(hi),alert_days=len(group),contains_malicious_day=mal,official_insider=bool(insider[ui]));model_eps.append(row);episodes.append(row)
        for d in calendar:
            mask=rowdates==d;flagged=np.unique(u[mask&flag]);fp=int((~insider[flagged]).sum());scorable=bool(mask.any())
            dailyrows.append(dict(model=label,seed=seed,date=str(d),scorable=scorable,scorable_users=int(mask.sum()),users_flagged=len(flagged) if scorable else None,noninsiders_flagged=fp if scorable else None,false_positive_user_rate=fp/475 if scorable else None))
        det=dict(detected);n_det=sum(det.values());fp_ever=len(np.unique(u[flag&(~insider[u])]))
        summary.append(dict(model=label,seed=seed,insiders_detected=n_det,registered_insiders=25,insiders_with_allowed_malicious_days=int(((daily.sum(1)>0)&insider).sum()),noninsiders_ever_flagged=fp_ever,noninsiders_ever_flagged_rate=fp_ever/475,median_delay_days=float(np.median(delays)) if delays else None,delay_Q1=float(np.quantile(delays,.25)) if delays else None,delay_Q3=float(np.quantile(delays,.75)) if delays else None,alert_episodes=len(model_eps),episodes_per_1000_calendar_user_days=len(model_eps)/232000*1000,episodes_per_1000_scorable_user_days=len(model_eps)/213000*1000,episode_malicious_day_share=np.mean([r['contains_malicious_day'] for r in model_eps]) if model_eps else None))
        for number in range(1,5):
            ids=[i for i,s in enumerate(users) if number in scen[s]]
            scenario_rows.append(dict(model=label,seed=seed,scenario=number,insiders=len(ids),insiders_detected=sum(det.get(i,False) for i in ids),insiders_with_allowed_malicious_days=sum(bool(daily[i].any()) for i in ids)))
        order=np.argsort(-p,kind='stable')
        for k in (10,25,50,100):
            take=order[:k];triage.append(dict(model=label,seed=seed,k=k,precision_actual_malicious_day=float(endpoint[take].mean()),precision_completed_window=float(y[take].mean()),distinct_users=len(np.unique(u[take])),tie_rule='stable descending score in frozen user/date row order'))
    for name,rows in [('C_OPERATIONAL_SUMMARY.csv',summary),('C_INSIDER_DETECTION.csv',perinsider),('C_USERS_FLAGGED_PER_DAY.csv',dailyrows),('C_ALERT_EPISODES.csv',episodes),('C_SCENARIO_DETECTION.csv',scenario_rows),('C_TOPK_TRIAGE.csv',triage)]:save_csv(name,rows)
    dump(OUT/'C_RESULTS.json',dict(summary=summary,insider_detection=perinsider,users_flagged_per_day=dailyrows,alert_episodes=episodes,scenario_detection=scenario_rows,top_k_triage=triage,scenario_mapping=mapping,label_payload_read_from_answer_files=False,allowed_daily_label_bounds=['2010-01-02','2011-04-10']));status('C_OPERATIONAL_COMPLETE')
if __name__=='__main__':main()
