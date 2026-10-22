from p5common import *
import argparse
def inputs(release,f):
    folder=Path(f['bundles'][release]['folder']);dense=np.load(folder/'scaled_dense_daily.npy',mmap_mode='r');ix=np.load(folder/'window_index.npy',mmap_mode='r')
    assert ix.ndim==2 and ix.shape[1]==2
    y=np.load(folder/'completed_window_labels.npy');ep=np.load(folder/'endpoint_labels.npy');offset=np.load(folder/'deoverlap_offset0_mask.npy').astype(bool)
    return dense,ix[:,0].astype(np.int32),ix[:,1].astype(np.int32),y,ep,offset
def score(release):
    import torch
    f=check_frozen();sentinel('A_TRANSFER_'+release);target=PRIVATE/'transfer'/release;target.mkdir(parents=True,exist_ok=False)
    sys.path.append(str(REPO/'src'));from editor006b_harness.input_bundle import DenseDailyWindowProvider
    dense,u,start,y,ep,offset=inputs(release,f);assert len(y)==f['bundles'][release]['windows']
    np.savez_compressed(target/'metadata.npz',cluster=u,y=y,endpoint=ep,offset0=offset)
    dev=device();s0=f['scalers']['original'];s1=f['scalers']['development'];mean0=np.array(s0['mean']);scale0=np.array(s0['scale']);mean1=np.array(s1['mean']);scale1=np.array(s1['scale'])
    hashes={};total=69;finished=0
    for block,specs in f['models'].items():
        for spec in specs:
            status('A_TRANSFER_SCORING',release=release,block=block,model=model_name(spec['model']),seed=spec['seed'],completed=finished,total=total)
            path=target/f"{block}_{spec['model']}_{spec['seed']}.npy";assert not path.exists();p=np.lib.format.open_memmap(path,mode='w+',dtype=np.float64,shape=(len(y),));m=load_model(spec,dev)
            provider=DenseDailyWindowProvider(dense,u,start,batch_size=1024)
            for lo,hi,x in provider:
                if block=='development':x=((x.astype(np.float64)*scale0+mean0-mean1)/scale1).astype(np.float32)
                p[lo:hi]=infer_batch(m,spec,x,dev)
                if dev.type=='cuda':time.sleep(.001)
            provider.assert_never_full_sequence_tensor();assert np.isfinite(p).all();p.flush();del p,m
            if torch.cuda.is_available():torch.cuda.empty_cache()
            hashes[path.name]=sha(path);finished+=1
    dump(OUT/f'A_{release}_SCORING_COMPLETE.json',dict(utc=utc(),release=release,model_seeds=finished,score_hashes=hashes,reruns=0));status('A_TRANSFER_COMPLETE',release=release,model_seeds=finished)
def analyze():
    import pandas as pd
    from boot import counts_for,bootstrap,contrast
    f=check_frozen();rows=[];contrasts=[];hist=pd.read_csv(f['historical_file']);historic=[]
    for release in ('r5.1','r6.2'):
        target=PRIVATE/'transfer'/release;done=json.loads((OUT/f'A_{release}_SCORING_COMPLETE.json').read_text(encoding='utf-8'))
        assert all(sha(target/n)==h for n,h in done['score_hashes'].items())
        with np.load(target/'metadata.npz') as z:u=z['cluster'];y=z['y'];ep=z['endpoint'];offset=z['offset0']
        counts=counts_for(int(u.max()+1));views=[('completed',np.ones(len(y),bool),y),('offset0',offset,y),('endpoint',np.ones(len(y),bool),ep)]
        for block,specs in f['models'].items():
            for view,mask,labels in views:
                cy=labels[mask];cu=u[mask];aps={};reps={};group={}
                for spec in specs:
                    name=spec['model'];seed=spec['seed'];p=np.load(target/f'{block}_{name}_{seed}.npy',mmap_mode='r')[mask]
                    row=dict(release=release,block=block,view=view,model=model_name(name),seed=seed,**point_metrics(cy,p,spec['threshold']));rows.append(row);group.setdefault(name,[]).append(row);aps.setdefault(name,[]).append(row['PR_AUC'])
                    if name in ('TA2','XGBoost_40','F00','L1'):
                        status('A_TRANSFER_BOOTSTRAP',release=release,block=block,view=view,model=model_name(name),seed=seed)
                        reps.setdefault(name,[]).append(bootstrap(cy,p,cu,counts)[0])
                for name,rs in group.items():
                    means={k:np.mean([r[k] for r in rs]) for k in ('PR_AUC','ranking_excess','ratio_to_prevalence','precision','recall','F1','alerts_per_1000','threshold_exceedance_rate')};rows.append(dict(release=release,block=block,view=view,model=model_name(name),seed='mean',windows=len(cy),positive_windows=int(cy.sum()),prevalence=float(cy.mean()),**means))
                for other in ('XGBoost_40','F00','L1'):
                    delta=np.mean(aps['TA2'])-np.mean(aps[other]);c=contrast(np.mean(reps['TA2'],0),np.mean(reps[other],0),delta)
                    contrasts.append(dict(release=release,block=block,view=view,contrast='TRACE - '+other,cluster='user',**c,official_insider_incident_clusters=f['bundles'][release]['official_incidents'],incident_bootstrap_status='same user/incident correspondence as historical harness; no independent incident-only bootstrap defined'))
        save_csv('A_TRANSFER_RESULTS.csv',rows);save_csv('A_TRANSFER_CONTRASTS.csv',contrasts)
    for release,dataset in [('r5.1','r51_secondary_stress'),('r6.2','r62_external')]:
        h=hist[(hist.dataset==dataset)&(hist.view=='COMPLETED_WINDOW')]
        current=[r for r in rows if r['release']==release and r['block']=='original' and r['view']=='completed' and r['seed']=='mean' and r['model']=='TRACE'][0]
        for family,g in h.groupby('family'):
            historical=float(g.PR_AUC.mean());historic.append(dict(release=release,historical_family=family,historical_mean_AP=historical,current_original_TRACE_mean_AP=current['PR_AUC'],difference=current['PR_AUC']-historical,descriptive_transfer='better point estimate' if current['PR_AUC']>historical else ('worse point estimate' if current['PR_AUC']<historical else 'same point estimate'),inference='descriptive historical comparison; no paired superiority claim across different frozen families'))
    save_csv('A_HISTORICAL_COMPARISON.csv',historic)
    shifts=[]
    for release in ('r5.1','r6.1','r6.2'):
        folder=Path(f['bundles'][release]['folder']);d=np.load(folder/'scaled_dense_daily.npy',mmap_mode='r');means=d.astype(np.float64).mean(axis=(0,1))
        for j,name in enumerate(f['scalers']['original']['features']):shifts.append(dict(release=release,feature=name,standardised_mean_shift=float(means[j]),reference_r52_TRAIN_z_mean=0.0,target_daily_rows=int(d.shape[0]*d.shape[1]),reference_daily_rows=f['scalers']['original']['n_train_daily_rows'],reference='frozen all-user r5.2 TRAIN scaler; daily-row z-space reference mean 0; no target fitting'))
    save_csv('A_FEATURE_SHIFT.csv',shifts);dump(OUT/'A_RESULTS.json',dict(results=rows,contrasts=contrasts,historical=historic,feature_shift=shifts,skips=['No independent incident-only bootstrap is defined by the historical harness. Its user/official-incident one-to-one qualification is retained.']));status('A_ANALYSIS_COMPLETE')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release',choices=['r5.1','r6.2']);p.add_argument('--analyze',action='store_true');a=p.parse_args();analyze() if a.analyze else score(a.release)
