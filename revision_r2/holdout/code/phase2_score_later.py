"""Frozen future one-pass evaluation. This file is hashed tonight, never executed tonight."""
from pathlib import Path
from datetime import date,datetime,timezone
import argparse,os,json,hashlib

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-once',action='store_true',required=True)
    parser.add_argument('--supervisor-disclosure-record',type=Path,required=True)
    args=parser.parse_args()
    assert args.supervisor_disclosure_record.is_file(),'Record the approved option B disclosure to the supervisor before scoring'
    import phase2_runtime as rt
    import numpy as np
    import pandas as pd
    import pyarrow.dataset as ds
    import torch,joblib
    from sklearn.metrics import average_precision_score
    from torch.utils.data import DataLoader,TensorDataset
    rt.gate()
    out,private=rt.OUT,rt.PRIVATE
    freeze=json.loads((out/'MODELS_FROZEN.json').read_text(encoding='utf-8'))
    assert freeze['training_finished'] and freeze['holdout_scored'] is False
    parity=json.loads((out/'PARITY_GATE.json').read_text(encoding='utf-8'))
    assert parity['status'] in ('PARITY_GATE_PASS','PARITY_GATE_FIXED'), 'Mandatory parity gate is not passed'
    assert parity['holdout_scored'] is False and parity['test_read'] is False
    assert rt.sha(out/'PARITY_GATE.json')==freeze['parity_gate_sha256'], 'Parity gate receipt changed'
    assert rt.sha(Path(__file__))==freeze['scoring_script']['sha256'],'Frozen scoring script changed'
    for entry in freeze['implementation_files']:
        assert rt.sha(Path(entry['path']))==entry['sha256'],'Frozen model/scoring dependency changed'
    assert rt.sha(private/'DEVELOPMENT_DAILY_SCALER.json')==freeze['scaler_sha256']
    assert rt.sha(private/'HOLDOUT_USERS.txt')==freeze['holdout_list_sha256']
    models={ (r['model'],r['seed']):r for r in freeze['models'] if 'PRECURSOR' not in r['model'] }
    for model in ('TA2','F00','XGBoost_40'):
        assert all((model,s) in models for s in rt.SEEDS),'Primary three-seed contrast unavailable; do not score'
    for spec in models.values(): assert rt.sha(spec['checkpoint'])==spec['sha256']
    # Consume the one-pass lock BEFORE any holdout feature row or checkpoint inference.
    lock=private/'HOLDOUT_SCORING_CONSUMED.json'
    with lock.open('x',encoding='utf-8') as f:
        json.dump({'utc':datetime.now(timezone.utc).isoformat(),'freeze_sha256':rt.sha(out/'MODELS_FROZEN.json'),'disclosure_sha256':rt.sha(args.supervisor_disclosure_record),'no_reruns':True},f,indent=2)
    users=(private/'HOLDOUT_USERS.txt').read_text().splitlines();assert len(users)==500
    scaler=json.loads((private/'DEVELOPMENT_DAILY_SCALER.json').read_text())
    feats=scaler['features'];mean=np.array(scaler['mean']);scale=np.array(scaler['scale'])
    path=Path(r'C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\interval_level\r52_user_day_intervals_dense.parquet')
    predicate=ds.field('user').isin(users)&(ds.field('interval_date')>=date(2011,2,19))&(ds.field('interval_date')<=date(2011,6,2))
    frame=ds.dataset(path,format='parquet').to_table(columns=['user','interval_date',*feats,'is_malicious_interval'],filter=predicate).to_pandas()
    frame['interval_date']=pd.to_datetime(frame['interval_date'])
    frame=frame.sort_values(['user','interval_date'],kind='mergesort')
    xx=[];tt=[];yy=[];ep=[];cluster=[];offset=[];part=[]
    for ui,u in enumerate(users):
        group=frame.loc[frame.user==u]
        for pname,lo,hi in [('validation','2011-02-19','2011-04-10'),('test','2011-04-11','2011-06-02')]:
            g=group.loc[(group.interval_date>=lo)&(group.interval_date<=hi)]
            expected=51 if pname=='validation' else 53
            assert len(g)==expected and (g.interval_date.diff().dropna()==pd.Timedelta(days=1)).all()
            raw=g[feats].to_numpy(dtype=np.float64);lab=g.is_malicious_interval.to_numpy()
            ix=np.arange(len(g)-19)[:,None]+np.arange(20)[None,:];rw=raw[ix]
            xx.append(((rw-mean)/scale).astype(np.float32));yy.extend(lab[ix].max(1));ep.extend(lab[ix[:,-1]])
            tt.append(rt.aggregate_common13_windows(xx[-1])[0]);cluster.extend([ui]*len(ix));offset.extend(np.arange(len(ix))%20==0);part.extend([pname]*len(ix))
    X=np.concatenate(xx);X40=np.concatenate(tt);y=np.array(yy,dtype=np.int8);endpoint=np.array(ep,dtype=np.int8);cluster=np.array(cluster);offset=np.array(offset,dtype=bool)
    assert X.shape==(33000,20,13) and len(y)==len(cluster)
    predictions={};score_dir=private/'scoring_once';score_dir.mkdir()
    loader=DataLoader(TensorDataset(torch.from_numpy(X)),batch_size=1024,shuffle=False,num_workers=0)
    for (name,seed),spec in models.items():
        if name in ('RF_40','XGBoost_40'):
            if name=='XGBoost_40':
                from xgboost import XGBClassifier
                m=XGBClassifier();m.load_model(spec['checkpoint'])
            else:m=joblib.load(spec['checkpoint'])
            p=m.predict_proba(X40)[:,1].astype(np.float64)
        else:
            m=rt.load_model(name,seed,'cuda');p=rt.probs(rt.logits(m,loader,torch.device('cuda'),'linear' if name=='L1' else 'odst'))
        predictions[name,seed]=p
        np.savez_compressed(score_dir/f'{name}_seed{seed}.npz',probabilities=p,predicted_positive=(p>=spec['threshold']),threshold=spec['threshold'],cluster_index=cluster,y_completed=y,y_endpoint=endpoint,deoverlap_offset0=offset,partition=np.array(part))
        del m
        if torch.cuda.is_available():torch.cuda.empty_cache()
    contrasts=[('TA2','XGBoost_40','primary'),('TA2','F00','primary'),('TA2','L1','secondary'),('TA2','RF_40','secondary'),('F10','F00','secondary'),('TA2','uniTA2','secondary')]
    rng=np.random.default_rng(42)
    counts=np.array([np.bincount(rng.integers(0,500,size=500),minlength=500) for _ in range(2000)],dtype=np.int16)
    public={'utc':datetime.now(timezone.utc).isoformat(),'freeze_sha256':rt.sha(out/'MODELS_FROZEN.json'),'evaluation_periods':['validation','test'],'bootstrap_replicates':2000,'bootstrap_seed':42,'all_outcomes_reported':True,'views':{}}
    for view,mask,labels in [('completed_window',np.ones(len(y),dtype=bool),y),('deoverlap_offset0',offset,y),('endpoint',np.ones(len(y),dtype=bool),endpoint)]:
        cy=labels[mask];cu=cluster[mask];prev=float(cy.mean());results={};reps={}
        for name in sorted({key[0] for key in predictions}):
            if not all((name,s) in predictions for s in rt.SEEDS):continue
            seed_aps=[];seed_boot=[]
            for seed in rt.SEEDS:
                p=predictions[name,seed][mask]
                seed_aps.append(float(average_precision_score(cy,p)))
                # Pre-sort once; weighted AP below preserves sklearn's tied-score grouping.
                order=np.argsort(-p,kind='stable');sy=cy[order];su=cu[order];sp=p[order]
                ends=np.r_[np.flatnonzero(np.diff(sp)),len(sp)-1]
                vals=[]
                for c in counts:
                    w=c[su].astype(np.float64);tp=np.cumsum(w*sy)[ends];tot=np.cumsum(w)[ends]
                    if tp[-1]==0:vals.append(float('nan'));continue
                    dtp=np.diff(np.r_[0.,tp]);precision=np.divide(tp,tot,out=np.zeros_like(tp),where=tot>0)
                    vals.append(float(np.sum(dtp*precision)/tp[-1]))
                seed_boot.append(vals)
            reps[name]=np.mean(seed_boot,axis=0)
            results[name]={'seed_average_precision':seed_aps,'three_seed_mean_average_precision':float(np.mean(seed_aps)),'ranking_excess':float(np.mean(seed_aps)-prev)}
        compared=[]
        for a,b,role in contrasts:
            if a not in results or b not in results:
                compared.append({'contrast':a+' - '+b,'role':role,'status':'unavailable_missing_frozen_model'});continue
            delta=reps[a]-reps[b];ci=np.nanpercentile(delta,[2.5,97.5]).tolist()
            decision='ranks below' if ci[1]<0 else ('ranks above (bounded to unseen CERT r5.2 users)' if ci[0]>0 else 'comparable / not distinguishable')
            compared.append({'contrast':a+' - '+b,'role':role,'delta_three_seed_mean_AP':results[a]['three_seed_mean_average_precision']-results[b]['three_seed_mean_average_precision'],'ci95_percentile':ci,'decision':decision,'valid_bootstrap_replicates':int(np.isfinite(delta).sum())})
        public['views'][view]={'windows':int(mask.sum()),'positive_windows':int(cy.sum()),'prevalence':prev,'models':results,'contrasts':compared}
    rt.dump(out/'HOLDOUT_ONE_PASS_RESULTS.json',public)

if __name__=='__main__':main()
