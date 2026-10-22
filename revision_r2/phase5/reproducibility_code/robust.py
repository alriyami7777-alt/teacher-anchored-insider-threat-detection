from p5common import *
import argparse
from sklearn.metrics import average_precision_score
NAMES=('TA2','F00','F10','L1','XGBoost_40','RF_40','Transformer','TCN','BiLSTM_noAttn')
SOURCES=('logon','device','file','email','http')
def conditions():return [(s,r) for s in SOURCES for r in (.25,.5,.75,1.)]+[('noise',r) for r in (.025,.05,.075,.1,.15,.2)]
def key(source,level):return f'{source}_{level:.3f}'
def perturb(x,source,level,f):
    sys.path.append(str(REPO/'src'))
    if source=='noise':
        from objective3_perturbations import apply_paired_perturbation
        return apply_paired_perturbation(x,'gaussian_noise_continuous',level,perturbation_seed=101)
    from objective3_missing_source_robustness import apply_missing_source_condition
    scaler=f['scalers']['development'];scaler=dict(mean=np.array(scaler['mean']),scale=np.array(scaler['scale']))
    full=apply_missing_source_condition(x,'without_'+source,scaler)
    return ((1-level)*x+level*full).astype(np.float32)
def score():
    f=check_frozen();sentinel('B_ROBUSTNESS');cohort=holdout();x=cohort['X'];target=PRIVATE/'robustness';target.mkdir(exist_ok=False);dev=device();specs=[s for s in f['models']['development'] if s['model'] in NAMES];assert len(specs)==27
    rows=[]
    for source,level in conditions():
        name=key(source,level);sentinel('B_'+name);xp=perturb(x,source,level,f);h=hashlib.sha256(xp.tobytes()).hexdigest();assert xp.shape==x.shape and np.isfinite(xp).all()
        for i,spec in enumerate(specs):
            status('B_ROBUSTNESS_SCORING',source=source,severity=level,model=model_name(spec['model']),seed=spec['seed'],completed=i,total=27)
            path=target/f"{name}_{spec['model']}_{spec['seed']}.npy";assert not path.exists();p=predict_array(spec,xp,dev);np.save(path,p)
        rows.append(dict(condition=name,source=source,severity=level,perturbed_tensor_sha256=h,paired_across_all_models_and_seeds=True,model_seeds=27));dump(OUT/'B_PERTURBATION_RECEIPTS.json',rows);del xp
    dump(OUT/'B_SCORING_COMPLETE.json',dict(utc=utc(),conditions=26,model_seeds_per_condition=27,new_inference_passes=702,clean_passes_reused=True,reruns=0));status('B_ROBUSTNESS_SCORED')
def analyze():
    import pandas as pd
    from boot import counts_for,bootstrap,contrast
    f=check_frozen();assert (OUT/'B_SCORING_COMPLETE.json').exists();cohort=holdout();y=cohort['y'];u=cohort['cluster'];counts=counts_for(500);assert np.array_equal(counts,np.load(P4PRIVATE/'BOOTSTRAP_USER_MULTIPLICITIES.npy'))
    specs=[s for s in f['models']['development'] if s['model'] in NAMES];rows=[];curves={};boot={};clean={};bclean={}
    for spec in specs:
        n,s=spec['model'],spec['seed'];clean[n,s]=float(average_precision_score(y,base_score(spec)))
        if n in ('TA2','L1','XGBoost_40','Transformer'):bclean[n,s]=np.load(P4PRIVATE/'bootstrap'/f'pooled_completed_{n}_{s}.npy')
    for source in (*SOURCES,'noise'):
        levels=[0,.025,.05,.075,.1,.15,.2] if source=='noise' else [0,.25,.5,.75,1]
        for spec in specs:
            name,s=spec['model'],spec['seed'];apvals=[];bvals=[]
            for level in levels:
                if level==0:ap=clean[name,s];b=bclean.get((name,s))
                else:
                    p=np.load(PRIVATE/'robustness'/f'{key(source,level)}_{name}_{s}.npy',mmap_mode='r');ap=float(average_precision_score(y,p));b=None
                    if name in ('TA2','L1','XGBoost_40','Transformer'):
                        status('B_AURC_BOOTSTRAP',source=source,severity=level,model=model_name(name),seed=s);b=bootstrap(y,p,u,counts)[0]
                retention=ap/clean[name,s];rows.append(dict(source=source,severity=level,model=model_name(name),seed=s,PR_AUC=ap,clean_PR_AUC=clean[name,s],retention=retention));apvals.append(retention)
                if b is not None:bvals.append(b/bclean[name,s])
            curves[source,name,s]=float(np.trapezoid(apvals,levels)/levels[-1])
            if bvals:boot[source,name,s]=np.trapezoid(np.array(bvals),levels,axis=0)/levels[-1]
    aurc=[]
    for name in NAMES:
        for seed in SEEDS:
            curves['source_mean',name,seed]=float(np.mean([curves[s,name,seed] for s in SOURCES]))
            if ('logon',name,seed) in boot:boot['source_mean',name,seed]=np.mean([boot[s,name,seed] for s in SOURCES],axis=0)
        for source in (*SOURCES,'source_mean','noise'):
            for seed in SEEDS:aurc.append(dict(source=source,model=model_name(name),seed=seed,AURC=curves[source,name,seed]))
            aurc.append(dict(source=source,model=model_name(name),seed='mean',AURC=float(np.mean([curves[source,name,s] for s in SEEDS]))))
    contrasts=[]
    for source in (*SOURCES,'source_mean','noise'):
        a=np.mean([boot[source,'TA2',s] for s in SEEDS],axis=0)
        for name in ('L1','XGBoost_40','Transformer'):
            b=np.mean([boot[source,name,s] for s in SEEDS],axis=0);point=np.mean([curves[source,'TA2',s]-curves[source,name,s] for s in SEEDS]);contrasts.append(dict(source=source,contrast='TRACE - '+name,metric='normalised severity-retention AURC',**contrast(a,b,point)))
    save_csv('B_RETENTION_CURVES.csv',rows);save_csv('B_AURC.csv',aurc);save_csv('B_AURC_CONTRASTS.csv',contrasts)
    os.environ['MPLCONFIGDIR']=str(OUT/'matplotlib_cache');import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
    df=pd.DataFrame(rows)
    for source in (*SOURCES,'noise'):
        d=df[df.source==source];d.to_csv(OUT/f'B_RETENTION_{source}_data.csv',index=False);fig,ax=plt.subplots(figsize=(9,5.5))
        for name in NAMES:
            z=d[d.model==model_name(name)].groupby('severity').retention.mean();ax.plot(z.index,z.values,marker='o',ms=3,label=model_name(name),lw=2.4 if name=='TA2' else 1.2)
        ax.set(xlabel='Noise severity λ' if source=='noise' else 'Source removal severity ρ',ylabel='PR-AUC / clean PR-AUC (three-seed mean)',title=f'Unseen users · {source} degradation · HOLDOUT TRAIN + VALIDATION');ax.legend(ncol=3,fontsize=8);ax.grid(alpha=.2);fig.tight_layout();fig.savefig(OUT/f'B_RETENTION_{source}.png',dpi=300);plt.close(fig)
    dump(OUT/'B_RESULTS.json',dict(curves=rows,AURC=aurc,contrasts=contrasts));status('B_ANALYSIS_COMPLETE')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--analyze',action='store_true');a=p.parse_args();analyze() if a.analyze else score()
