"""CPU-only Phase 2 preparation. Never opens TEST tensors or returns TEST rows."""
from pathlib import Path
from datetime import datetime, timezone, date
import hashlib, json, time, sys
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT=Path(r'C:\PhD\07_Projects\r2_holdout')
OUT=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision\holdout')
PRIVATE=OUT/'private'
FEAS=Path(r'C:\PhD\07_Projects\cert-r42-feasibility')
sys.path.insert(0,str(ROOT/'parity_source'))
from r52_locked_baselines.data import aggregate_common13_windows
FEATURES=['total_events','logon_count','device_count','file_count','email_count','http_count','active_duration_minutes','has_logon_activity','has_device_activity','has_file_activity','has_email_activity','has_http_activity','is_active_day']
def utc(): return datetime.now(timezone.utc).isoformat()
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()
def writej(p,x): Path(p).write_text(json.dumps(x,indent=2),encoding='utf-8')

def main():
    t0=time.perf_counter()
    baseline=ROOT/'PREREGISTRATION_BASELINE.md'
    assert baseline.exists() and (OUT/'PREREGISTRATION_R2_HOLDOUT.md').exists()
    assert sha(baseline) in (OUT/'PREREGISTRATION_R2_HOLDOUT.md').read_text(encoding='utf-8')
    assert not (PRIVATE/'HOLDOUT_USERS.txt').exists(), 'Split already exists; refuse rerandomization'
    originals={}
    audit=[]
    for split in ('train','validation'):
        p=FEAS/f'data/processed/r5.2/tensors/r52_T20_s1_{split}.npz'
        # NPZ member access is lazy: no original X member is read or decompressed.
        with np.load(p,allow_pickle=True) as z:
            originals[split]={k:z[k] for k in ('user','y','start_date','end_date','sequence_id','feature_names')}
        audit.append({'source':str(p),'members_read':['user','y','start_date','end_date','sequence_id','feature_names'],'X_read':False})
    users=sorted(set(originals['train']['user'].astype(str)))
    assert len(users)==2000 and set(users)==set(originals['validation']['user'].astype(str))
    insiders=set()
    answer_files=0
    for scenario in range(1,5):
        folder=FEAS/f'data/raw/answers/r5.2-{scenario}'
        for p in sorted(folder.glob('r5.2-*.csv')):
            # Answer-file names index insider users; byte size > 0 proves event payload exists.
            # No answer payload, timestamp, or activity from any TEST day is opened.
            assert p.stat().st_size>0, 'Empty answer file needs investigation'
            insiders.add(p.stem.split('-')[-1]);answer_files+=1
    assert insiders and insiders.issubset(set(users))
    strata=[('insider',sorted(insiders)),('non_insider',sorted(set(users)-insiders))]
    rng=np.random.default_rng(20261022)
    sizes=[round(.25*len(s)) for _,s in strata]
    adjustment=500-sum(sizes)
    assert abs(adjustment)<=1
    if adjustment: sizes[int(np.argmax([len(s) for _,s in strata]))]+=adjustment
    holdout=[]
    for (_,ss),n in zip(strata,sizes):
        a=np.array(ss);rng.shuffle(a);holdout.extend(a[:n].tolist())
    holdout=sorted(holdout);dev=sorted(set(users)-set(holdout))
    assert len(holdout)==500 and len(dev)==1500 and not set(dev)&set(holdout)
    for name,values in [('HOLDOUT_USERS',holdout),('DEVELOPMENT_USERS',dev)]:
        with (PRIVATE/f'{name}.txt').open('x',encoding='utf-8',newline='\n') as f: f.write('\n'.join(values)+'\n')
    receipt={'utc':utc(),'rng':'one numpy.random.default_rng(20261022), insider then non_insider; sorted before each shuffle','rounding_adjustment_larger_stratum':adjustment,'answer_file_index_count':answer_files,'groups':{}}
    for name,values in [('HOLDOUT',holdout),('DEVELOPMENT',dev)]:
        group={'users':len(values),'insider':len(set(values)&insiders),'non_insider':len(set(values)-insiders),'list_sha256':sha(PRIVATE/f'{name}_USERS.txt'),'periods':{}}
        for split,orig in originals.items():
            mask=np.isin(orig['user'].astype(str),values)
            group['periods'][split]={'windows':int(mask.sum()),'positive_windows':int(orig['y'][mask].sum())}
        receipt['groups'][name]=group
    writej(OUT/'SPLIT_RECEIPT.json',receipt)
    with (OUT/'PREREGISTRATION_R2_HOLDOUT.md').open('a',encoding='utf-8',newline='\n') as f:
        f.write('\n## Materialized split receipt (counts and hashes only)\n\n```json\n'+json.dumps(receipt,indent=2)+'\n```\n')
    print('Split frozen:',json.dumps(receipt),flush=True)
    daily_path=FEAS/'data/processed/r5.2/interval_level/r52_user_day_intervals_dense.parquet'
    predicate=(ds.field('user').isin(dev)) & (ds.field('interval_date')>=date(2010,1,2)) & (ds.field('interval_date')<=date(2011,4,10))
    daily=ds.dataset(daily_path,format='parquet').to_table(columns=['user','interval_date',*FEATURES,'is_malicious_interval'],filter=predicate).to_pandas()
    daily['interval_date']=pd.to_datetime(daily['interval_date'])
    daily=daily.sort_values(['user','interval_date'],kind='mergesort').reset_index(drop=True)
    assert set(daily.user)==set(dev) and daily.interval_date.max()<=pd.Timestamp('2011-04-10')
    assert len(daily)==1500*(413+51)
    train_days=daily.loc[daily.interval_date<=pd.Timestamp('2011-02-18'),FEATURES].to_numpy(dtype=np.float64)
    assert len(train_days)==1500*413
    mean=train_days.mean(axis=0);scale=train_days.std(axis=0,ddof=0);scale[scale==0]=1
    writej(PRIVATE/'DEVELOPMENT_DAILY_SCALER.json',{'features':FEATURES,'mean':mean.tolist(),'scale':scale.tolist(),'fit_rows':len(train_days),'fit_users':1500,'fit_partition':'TRAIN','utc':utc()})
    groups={str(u):g.reset_index(drop=True) for u,g in daily.groupby('user',sort=False)}
    tensor_dir=PRIVATE/'tensors';tensor_dir.mkdir()
    manifest={'utc':utc(),'features':FEATURES,'sequence_length':20,'stride':1,'development_users':1500,'holdout_users':500,'test_read':False,'holdout_features_materialized':False,'daily_date_filter':['2010-01-02','2011-04-10'],'scaler_fit_user_days':len(train_days),'scaler_sha256':sha(PRIVATE/'DEVELOPMENT_DAILY_SCALER.json'),'splits':{},'positive_counts':receipt['groups'],'sanity_mismatches':0,'original_tensor_member_access':audit,'tabular_feature_recipe':'40 summaries of standardized float32 sequence tensors; exact producing aggregate_common13_windows'}
    feature_names=[]
    for col in FEATURES[:7]: feature_names.extend([col+'_'+a for a in ('sum','mean','max','std')])
    for col in FEATURES[7:]: feature_names.extend([col+'_active_days',col+'_active_proportion'])
    manifest['tabular_feature_names']=feature_names
    for split,orig in originals.items():
        mask=np.isin(orig['user'].astype(str),dev)
        o={k:v[mask] for k,v in orig.items() if k!='feature_names'}
        n=len(o['y'])
        X=np.lib.format.open_memmap(tensor_dir/f'{split}_X.npy',mode='w+',dtype=np.float32,shape=(n,20,13))
        X40=np.lib.format.open_memmap(tensor_dir/f'{split}_X40.npy',mode='w+',dtype=np.float32,shape=(n,40))
        labels=np.empty(n,dtype=np.int8)
        for u in dev:
            pos=np.flatnonzero(o['user'].astype(str)==u)
            g=groups[u]
            raw=g[FEATURES].to_numpy(dtype=np.float64)
            starts=np.searchsorted(g.interval_date.to_numpy(),o['start_date'][pos].astype('datetime64[ns]'))
            ix=starts[:,None]+np.arange(20)[None,:]
            assert np.array_equal(g.interval_date.to_numpy()[ix[:,-1]],o['end_date'][pos].astype('datetime64[ns]'))
            assert np.all(np.diff(ix,axis=1)==1)
            rw=raw[ix]
            X[pos]=((rw-mean)/scale).astype(np.float32)
            labels[pos]=g.is_malicious_interval.to_numpy()[ix].max(axis=1)
            X40[pos]=aggregate_common13_windows(np.asarray(X[pos]))[0]
        mismatches=int(np.count_nonzero(labels!=o['y']))
        manifest['sanity_mismatches']+=mismatches
        assert mismatches==0, f'{split} rebuilt labels do not match producing tensor subset'
        assert n==1500*(394 if split=='train' else 32)
        assert np.isfinite(X).all() and np.isfinite(X40).all()
        X.flush();X40.flush();del X,X40
        np.save(tensor_dir/f'{split}_y.npy',labels,allow_pickle=False)
        np.savez_compressed(tensor_dir/f'{split}_metadata.npz',**{k:v.astype(str) for k,v in o.items() if k!='y'})
        manifest['splits'][split]={'shape':[n,20,13],'summary_shape':[n,40],'positives':int(labels.sum()),'label_mismatches':mismatches,'count_matches_original_development_subset':True,'files':{p.name:sha(p) for p in tensor_dir.glob(f'{split}_*')}}
        print('Rebuilt',split,n,'windows;',int(labels.sum()),'positive; label mismatches',mismatches,flush=True)
    tr=manifest['splits']['train'];manifest['pos_weight']=.25*(tr['shape'][0]-tr['positives'])/tr['positives']
    manifest['cpu_seconds']=time.perf_counter()-t0
    manifest['completed_utc']=utc()
    writej(OUT/'DATA_MANIFEST.json',manifest)
    print('CPU preparation complete',manifest['cpu_seconds'],'seconds',flush=True)

if __name__=='__main__': main()
