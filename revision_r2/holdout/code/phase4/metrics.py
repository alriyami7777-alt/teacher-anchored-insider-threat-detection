"""Metrics from saved one-pass predictions only; no model inference."""
from common import *
import numpy as np,pandas as pd
from numba import njit,prange,set_num_threads
from sklearn.metrics import average_precision_score,precision_score,recall_score,f1_score
set_num_threads(2)
@njit(parallel=True)
def weighted_ap(labels,clusters,ends,counts):
    out=np.empty(len(counts),np.float64)
    for r in prange(len(counts)):
        tp=0.;total=0.;last_tp=0.;area=0.;e=0
        for i in range(len(labels)):
            w=float(counts[r,clusters[i]]);total+=w;tp+=w*labels[i]
            if i==ends[e]:
                if tp>last_tp and total>0:area+=(tp-last_tp)*tp/total
                last_tp=tp;e+=1
        out[r]=area/tp if tp>0 else np.nan
    return out
def check_algorithm():
    # A meaningful tied-score and user-multiplicity check before real analysis.
    y=np.array([1,0,1,0,0,1],np.int8);p=np.array([.9,.9,.6,.4,.4,.1]);u=np.array([0,1,0,1,2,2],np.int16);c=np.array([[1,1,1],[2,0,1],[0,1,2]],np.int16)
    order=np.argsort(-p,kind='stable');sp=p[order];ends=np.r_[np.flatnonzero(np.diff(sp)),len(sp)-1]
    actual=weighted_ap(y[order],u[order],ends,c)
    expected=np.array([average_precision_score(y,p,sample_weight=r[u]) for r in c]);assert np.allclose(actual,expected,atol=1e-14)
def main():
    check_algorithm();assert (P4/'SCORING_COMPLETE.json').exists()
    f=json.loads((P4/'MODELS_FROZEN_PHASE4.json').read_text());done=json.loads((P4/'SCORING_COMPLETE.json').read_text())
    for name,h in done['prediction_hashes'].items():assert sha(PRIVATE/'scores'/name)==h
    with np.load(PRIVATE/'HOLDOUT_COHORT.npz') as z:y=z['y'];ep=z['endpoint'];u=z['cluster'];offset=z['offset0'];part=z['partition']
    rng=np.random.default_rng(42);counts=np.array([np.bincount(rng.integers(0,500,size=500),minlength=500) for _ in range(2000)],np.int16)
    np.save(PRIVATE/'BOOTSTRAP_USER_MULTIPLICITIES.npy',counts)
    views=[('pooled_completed',np.ones(len(y),bool),y),('train_completed',part=='train',y),('validation_completed',part=='validation',y),('pooled_offset0',offset,y),('pooled_endpoint',np.ones(len(y),bool),ep)]
    pairs=[('TA2','XGBoost_40','primary'),('TA2','F00','primary'),('TA2','L1','secondary'),('TA2','RF_40','secondary'),('F10','F00','secondary'),('TA2','uniTA2','secondary')]+[('TA2',n,'secondary_exploratory') for n in BASELINES]
    rows=[];contrasts=[];public={};bootdir=PRIVATE/'bootstrap';bootdir.mkdir(exist_ok=True)
    for view,mask,labels in views:
        cy=labels[mask];cu=u[mask];prev=float(cy.mean());group={};reps={}
        for spec in f['models']:
            name,seed=spec['model'],spec['seed'];status('BOOTSTRAP',view=view,model=name,seed=seed)
            with np.load(PRIVATE/'scores'/f'{name}_{seed}.npz') as z:p=z['scores'][mask]
            pred=p>=spec['threshold'];ap=float(average_precision_score(cy,p));row=dict(view=view,model=name,seed=seed,windows=len(cy),positives=int(cy.sum()),prevalence=prev,AP=ap,ranking_excess=ap-prev,threshold=spec['threshold'],precision=float(precision_score(cy,pred,zero_division=0)),recall=float(recall_score(cy,pred,zero_division=0)),F1=float(f1_score(cy,pred,zero_division=0)),alerts_per_1000=float(pred.mean()*1000))
            rows.append(row);group.setdefault(name,[]).append(row)
            order=np.argsort(-p,kind='stable');sp=p[order];ends=np.r_[np.flatnonzero(np.diff(sp)),len(sp)-1]
            boot=weighted_ap(cy[order],cu[order],ends,counts);np.save(bootdir/f'{view}_{name}_{seed}.npy',boot);reps.setdefault(name,[]).append(boot)
        means={}
        for name,rs in group.items():
            if len(rs)!=3:continue
            row={k:float(np.mean([r[k] for r in rs])) for k in ('AP','ranking_excess','precision','recall','F1','alerts_per_1000')};row.update(view=view,model=name,seed='mean',windows=len(cy),positives=int(cy.sum()),prevalence=prev,threshold=None);rows.append(row);means[name]=row
        vc=[]
        for a,b,role in pairs:
            if a not in means or b not in means:
                row=dict(view=view,contrast=a+' - '+b,role=role,status='unavailable_missing_frozen_three_seed_model');contrasts.append(row);vc.append(row);continue
            delta=np.mean(reps[a],axis=0)-np.mean(reps[b],axis=0);ci=np.nanpercentile(delta,[2.5,97.5]);decision='ranks below' if ci[1]<0 else ('ranks above (bounded to unseen CERT r5.2 users)' if ci[0]>0 else 'comparable / not distinguishable')
            row=dict(view=view,contrast=a+' - '+b,role=role,status='ok',delta_AP=means[a]['AP']-means[b]['AP'],ci95_low=float(ci[0]),ci95_high=float(ci[1]),decision=decision,valid_bootstrap_replicates=int(np.isfinite(delta).sum()));contrasts.append(row);vc.append(row)
        public[view]=dict(windows=len(cy),positives=int(cy.sum()),prevalence=prev,models=means,contrasts=vc)
        pd.DataFrame(rows).to_csv(P4/'HOLDOUT_RESULTS.csv',index=False);pd.DataFrame(contrasts).to_csv(P4/'HOLDOUT_CONTRASTS.csv',index=False)
    dump(P4/'HOLDOUT_RESULTS.json',dict(utc=utc(),evaluation_periods=['train','validation'],primary_view='pooled_completed',bootstrap_replicates=2000,bootstrap_seed=42,bootstrap_unit='HOLDOUT user; same multiplicities paired across models and seeds',views=public,per_seed_and_mean=rows,test_read=False,all_outcomes_reported=True))
    figures();status('METRICS_FINISHED',result_rows=len(rows),contrast_rows=len(contrasts))
def figures():
    os.environ['MPLCONFIGDIR']=str(P4/'matplotlib_cache')
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    df=pd.read_csv(P4/'HOLDOUT_RESULTS.csv');d=df[df.view=='pooled_completed'].copy();d.to_csv(P4/'mean_AP_seed_dots_data.csv',index=False)
    m=d[d.seed=='mean'].sort_values('AP',ascending=False);fig,ax=plt.subplots(figsize=(12,5.8));ix=np.arange(len(m));ax.bar(ix,m.AP,color='#b4c4ce')
    for i,name in enumerate(m.model):
        vals=d[(d.model==name)&(d.seed!='mean')].sort_values('seed');ax.scatter(i+np.linspace(-.15,.15,len(vals)),vals.AP,color='#243d4d',s=18,zorder=3,label='Seeds 42, 52, 62' if i==0 else None)
    ax.axhline(float(m.prevalence.iloc[0]),ls=':',color='#666666',label='Prevalence');ax.set_xticks(ix,m.model,rotation=45,ha='right');ax.set_ylabel('Average precision (PR-AUC)');ax.set_xlabel('Frozen model');ax.set_title('Unseen users: pooled HOLDOUT TRAIN + VALIDATION');ax.legend();ax.set_ylim(0,1);fig.tight_layout();fig.savefig(P4/'mean_AP_seed_dots.png',dpi=300);plt.close(fig)
    c=pd.read_csv(P4/'HOLDOUT_CONTRASTS.csv');c=c[(c.view=='pooled_completed')&(c.status=='ok')].copy();c.to_csv(P4/'contrasts_forest_data.csv',index=False)
    fig,ax=plt.subplots(figsize=(10,7));ix=np.arange(len(c));ax.hlines(ix,c.ci95_low,c.ci95_high,color='#243d4d');ax.scatter(c.delta_AP,ix,color='#243d4d',s=22);ax.axvline(0,ls='--',color='#888888');ax.set_yticks(ix,c.contrast);ax.invert_yaxis();ax.set_xlabel('Difference in three-seed mean average precision (95% user-cluster CI)');ax.set_ylabel('Preregistered contrast');ax.set_title('Unseen users: pooled HOLDOUT TRAIN + VALIDATION');fig.tight_layout();fig.savefig(P4/'contrasts_forest.png',dpi=300);plt.close(fig)
if __name__=='__main__':main()
