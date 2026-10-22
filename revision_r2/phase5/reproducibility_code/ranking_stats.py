from p5common import *
import pandas as pd
from scipy.stats import spearmanr,norm
def main():
    from sklearn.metrics import roc_auc_score,roc_curve,average_precision_score
    from boot import counts_for,bootstrap,contrast
    f=check_frozen();co=holdout();y=co['y'];u=co['cluster'];counts=counts_for(500);rows=[];reps={};aucs={};groups={}
    for spec in f['models']['development']:
        n,s=spec['model'],spec['seed'];p=base_score(spec);auc=float(roc_auc_score(y,p));order=np.argsort(-p,kind='stable');fpr,tpr,_=roc_curve(y,p,drop_intermediate=False)
        row=dict(model=model_name(n),seed=s,ROC_AUC=auc)
        for fraction in (.01,.05):row[f'precision_at_{fraction:.2f}_alert_budget']=float(y[order[:int(np.ceil(len(y)*fraction))]].mean())
        for rate in (.001,.01):row[f'recall_at_FPR_{rate:.3f}']=float(tpr[fpr<=rate].max())
        rows.append(row);groups.setdefault(n,[]).append(row);aucs.setdefault(n,[]).append(auc);status('D_ROC_BOOTSTRAP',model=model_name(n),seed=s);reps.setdefault(n,[]).append(bootstrap(y,p,u,counts)[1])
    for n,rs in groups.items():rows.append(dict(model=model_name(n),seed='mean',**{k:float(np.mean([r[k] for r in rs])) for k in rs[0] if k not in ('model','seed')}))
    contrasts=[]
    for n in groups:
        if n=='TA2':continue
        contrasts.append(dict(contrast='TRACE - '+model_name(n),metric='ROC_AUC',**contrast(np.mean(reps['TA2'],0),np.mean(reps[n],0),np.mean(aucs['TA2'])-np.mean(aucs[n]))))
    save_csv('D_RANKING_METRICS.csv',rows);save_csv('D_ROC_CONTRASTS.csv',contrasts);dump(OUT/'D_RESULTS.json',dict(metrics=rows,contrasts=contrasts))
    results=pd.read_csv(P4/'HOLDOUT_RESULTS.csv');pooled=results[(results.view=='pooled_completed')&(results.seed!='mean')];stability=[]
    for n,g in pooled.groupby('model'):
        stability.append(dict(model=model_name(n),between_seed_AP_SD=float(g.AP.std(ddof=1)),mean_AP=float(g.AP.mean()),min_AP=float(g.AP.min()),max_AP=float(g.AP.max())))
    ta={s:base_score(next(r for r in f['models']['development'] if r['model']=='TA2' and r['seed']==s)) for s in SEEDS};corr=[];top=[];topsets={}
    for s,p in ta.items():
        spec=next(r for r in f['models']['development'] if r['model']=='TA2' and r['seed']==s);ix=np.flatnonzero(p>=spec['threshold']);ix=ix[np.argsort(-p[ix],kind='stable')[:100]];topsets[s]=set(ix.tolist())
        for rank,i in enumerate(ix,1):top.append(dict(seed=s,rank=rank,window_row_index=int(i),user=str(co['user'][i]),score=float(p[i])))
    for i,a in enumerate(SEEDS):
        for b in SEEDS[i+1:]:
            inter=len(topsets[a]&topsets[b]);union=len(topsets[a]|topsets[b]);corr.append(dict(seed_a=a,seed_b=b,score_Spearman=float(spearmanr(ta[a],ta[b]).statistic),top100_flagged_intersection=inter,top100_flagged_union=union,Jaccard=inter/union if union else None,overlap_fraction=inter/min(len(topsets[a]),len(topsets[b])) if min(len(topsets[a]),len(topsets[b])) else None))
    explain=[]
    for cohort,folder in [('original_validation',R2/'explanation'),('holdout_retrained',R2/'explanation/holdout')]:
        d=pd.read_csv(folder/'integrated_gradients_features.csv')
        for (stratum,target),g in d.groupby(['stratum','target']):
            values={s:g[g.seed==s].set_index('feature').mean_abs_ig_sum_days for s in SEEDS}
            for i,a in enumerate(SEEDS):
                for b in SEEDS[i+1:]:
                    common=values[a].index.intersection(values[b].index);explain.append(dict(cohort=cohort,stratum=stratum,target=target,seed_a=a,seed_b=b,feature_ranking_Spearman=float(spearmanr(values[a].loc[common],values[b].loc[common]).statistic),features=len(common),primary_target=target=='final_logit'))
    pc=pd.read_csv(P4/'HOLDOUT_CONTRASTS.csv');secondary=pc[(pc.view=='pooled_completed')&(pc.role!='primary')];holm=[]
    def boot_model(n):return np.mean([np.load(P4PRIVATE/'bootstrap'/f'pooled_completed_{n}_{s}.npy') for s in SEEDS],axis=0)
    for _,r in secondary.iterrows():
        a,b=r['contrast'].split(' - ');d=boot_model(a)-boot_model(b);d=d[np.isfinite(d)];pv=min(1.,2*min((1+np.sum(d<=0))/(len(d)+1),(1+np.sum(d>=0))/(len(d)+1)));holm.append(dict(contrast=r['contrast'].replace('TA2','TRACE'),raw_bootstrap_two_sided_p=float(pv),original_label=r.decision,estimate=r.delta_AP))
    order=np.argsort([r['raw_bootstrap_two_sided_p'] for r in holm],kind='stable');previous=0.
    for rank,i in enumerate(order):
        adjusted=min(1.,max(previous,(len(holm)-rank)*holm[i]['raw_bootstrap_two_sided_p']));previous=adjusted;new='comparable / not distinguishable'
        if adjusted<.05:new='ranks above (bounded to unseen CERT r5.2 users)' if holm[i]['estimate']>0 else 'ranks below'
        holm[i].update(Holm_adjusted_p=adjusted,Holm_reject_0_05=adjusted<.05,adjusted_label=new,label_changed=new!=holm[i]['original_label'])
    primary=pc[(pc.view=='pooled_completed')&(pc['contrast']=='TA2 - XGBoost_40')].iloc[0];width=float(primary.ci95_high-primary.ci95_low);se=width/(2*norm.ppf(.975));power=dict(contrast='TRACE - XGBoost_40',observed_estimate=float(primary.delta_AP),observed_ci95_low=float(primary.ci95_low),observed_ci95_high=float(primary.ci95_high),observed_CI_width=width,normal_SE_proxy=float(se),approx_95pct_half_width=width/2,approx_MDE_80pct_power_two_sided_alpha_0_05=float((norm.ppf(.975)+norm.ppf(.8))*se),assumptions='Normal approximation using observed bootstrap CI width; not a prospective power guarantee or evidence of equivalence')
    for name,data in [('F_SEED_STABILITY.csv',stability),('F_TRACE_SCORE_AND_TOP100_STABILITY.csv',corr),('F_TRACE_TOP100_FLAGGED_WINDOWS.csv',top),('F_EXPLANATION_RANK_STABILITY.csv',explain),('F_HOLM_SECONDARY_CONTRASTS.csv',holm),('F_POWER.csv',[power])]:save_csv(name,data)
    dump(OUT/'F_RESULTS.json',dict(seed_stability=stability,TRACE_score_stability=corr,top100_flagged=top,explanation_ranking_stability=explain,Holm_secondary_contrasts=holm,power=power));status('D_F_ANALYSIS_COMPLETE')
if __name__=='__main__':main()
