"""Frozen-model explanation evidence. No optimiser, fitting, or training entrypoint.

All exported identifiers are pseudonyms; original IDs never leave the input loader.
The runner, not this reusable numerical module, controls data and GPU access.
"""
from __future__ import annotations
import hashlib
import itertools
import json
from pathlib import Path
import numpy as np

FEATURES = ('total_events','logon_count','device_count','file_count','email_count',
            'http_count','active_duration_minutes','has_logon_activity',
            'has_device_activity','has_file_activity','has_email_activity',
            'has_http_activity','is_active_day')
SOURCES = ('logon','device','file','email','web')
SOURCE_FEATURES = ((1,7),(2,8),(3,9),(4,10),(5,11))
SUMMARY_RAW = np.array([j for j in range(7) for _ in range(4)] +
                       [j for j in range(7,13) for _ in range(2)])
SUMMARY_NAMES = tuple([f'{FEATURES[j]}_{a}' for j in range(7)
                      for a in ('sum','mean','max','std')] +
                     [f'{FEATURES[j]}_{a}' for j in range(7,13)
                      for a in ('active_days','active_proportion')])
SEEDS = (42,52,62)

def pseudonym(value):
    return 'U_'+hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:10]

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''): h.update(b)
    return h.hexdigest()

def checked(path, expected):
    if not expected or sha256(path)!=expected: raise RuntimeError('Frozen input hash mismatch')
    return Path(path)

def write_json(path, value):
    def clean(v):
        if isinstance(v,dict): return {str(k):clean(x) for k,x in v.items()}
        if isinstance(v,(list,tuple)): return [clean(x) for x in v]
        if isinstance(v,np.ndarray): return clean(v.tolist())
        if isinstance(v,np.generic): return clean(v.item())
        if isinstance(v,float) and not np.isfinite(v): return None
        return v
    Path(path).write_text(json.dumps(clean(value),indent=2,allow_nan=False),encoding='utf-8')

def aggregate40(x):
    cols=[]
    for j in range(7):
        a=x[:,:,j]
        cols.extend((a.sum(1),a.mean(1),a.max(1),a.std(1)))
    for j in range(7,13):
        a=x[:,:,j]; cols.extend((a.sum(1),a.mean(1)))
    return np.stack(cols,1).astype(np.float32)

def integrated_gradients(forward, x, baseline, steps=50, batch_size=64, progress=None):
    """50-interval composite trapezoid (51 nodes), nine output-specific gradients.

    forward takes a torch tensor and returns N x (8 trees + final logit).
    Completeness denominator is max(abs(output difference), 1e-6).
    """
    import torch
    n=len(x); attrs=np.empty((n,9,20,13),np.float32)
    differences=np.empty((n,9),np.float64)
    b=torch.as_tensor(baseline,dtype=torch.float32,device=forward.device)
    # cuDNN eval-mode RNN backward is unsupported. Native RNN preserves eval mode.
    with torch.backends.cudnn.flags(enabled=False):
        with torch.no_grad(): fb=forward(b[None]).detach().cpu().numpy()[0]
        for start in range(0,n,batch_size):
            stop=min(start+batch_size,n)
            xx=torch.as_tensor(x[start:stop],dtype=torch.float32,device=forward.device)
            d=xx-b
            grads=torch.zeros((len(xx),9,20,13),device=xx.device)
            for a in range(steps+1):
                z=(b+(a/steps)*d).detach().requires_grad_(True)
                outputs=forward(z)
                weight=(0.5 if a in (0,steps) else 1.0)/steps
                for j in range(9):
                    g=torch.autograd.grad(outputs[:,j].sum(),z,retain_graph=j<8)[0]
                    grads[:,j].add_(g,alpha=weight)
            attrs[start:stop]=(grads*d[:,None]).detach().cpu().numpy()
            with torch.no_grad(): differences[start:stop]=forward(xx).detach().cpu().numpy()-fb
            if progress: progress(stop,n)
    residual=attrs.astype(np.float64).sum((2,3))-differences
    relative=np.abs(residual)/np.maximum(np.abs(differences),1e-6)
    return attrs,differences,residual,relative

def group_columns(model, level):
    if level=='feature':
        return [np.array([j]) for j in range(13 if model=='TA2' else 40)]
    if level=='raw_feature':
        return [np.array([j]) if model=='TA2' else np.flatnonzero(SUMMARY_RAW==j) for j in range(13)]
    if level=='source':
        return [np.array(g) if model=='TA2' else np.flatnonzero(np.isin(SUMMARY_RAW,g))
                for g in SOURCE_FEATURES]
    raise ValueError('Unknown intervention level')

def group_attributions(attribution, groups):
    return np.stack([attribution[:,g].sum(1) for g in groups],1)

def _random_subsets(eligible,k,rng,draws):
    """Uniform independent random k-subsets, with repeated subsets evaluated once."""
    return np.sort(np.array([rng.choice(eligible,k,replace=False) for _ in range(draws)]),1)

def interventions(predict, x, baseline, attribution, groups, ks, *, seed=42,
                  draws=200, sequence_batch=64, prediction_batch=2048, progress=None):
    """Positive attribution -> expected decrease; negative -> expected increase.

    Insufficient same-sign inputs are ineligible, never silently padded. Random
    subsets use the same sign-eligible population, matching EDITOR-017's control.
    Results are sequence-level; 200 draws are averaged within each sequence.
    """
    n=len(x); original=predict(x); a=group_attributions(attribution,groups)
    results={}
    for k in ks:
        for sign in (1,-1):
            rng=np.random.default_rng(seed+1000*k+(0 if sign==1 else 1))
            delta=np.full(n,np.nan); random_delta=np.full(n,np.nan)
            random_accuracy=np.full(n,np.nan)
            for start in range(0,n,sequence_batch):
                stop=min(start+sequence_batch,n)
                samples=[]; owners=[]; specs=[]
                for i in range(start,stop):
                    eligible=np.flatnonzero(a[i]*sign>0)
                    if len(eligible)<k: continue
                    top=eligible[np.argsort(-sign*a[i,eligible],kind='stable')[:k]]
                    draws_idx=_random_subsets(eligible,k,rng,draws)
                    # First subset is top; inverse retains all 200 independent draws.
                    unique,inverse=np.unique(np.vstack((np.sort(top),draws_idx)),axis=0,return_inverse=True)
                    offset=len(samples)
                    for subset in unique:
                        z=x[i].copy(); columns=np.concatenate([groups[j] for j in subset])
                        if x.ndim==3: z[:,columns]=baseline[:,columns]
                        else: z[columns]=baseline[columns]
                        samples.append(z); owners.append(i)
                    specs.append((i,offset,inverse,len(unique)))
                if samples:
                    samples=np.asarray(samples,dtype=np.float32)
                    out=np.concatenate([predict(samples[j:j+prediction_batch])
                                        for j in range(0,len(samples),prediction_batch)])
                    for i,offset,inverse,size in specs:
                        changes=sign*(original[i]-out[offset:offset+size])
                        delta[i]=changes[inverse[0]]
                        random_delta[i]=changes[inverse[1:]].mean()
                        random_accuracy[i]=(changes[inverse[1:]]>0).mean()
                if progress: progress(k,sign,stop,n)
            results[(k,sign)]={'signed_change':delta,'accuracy':np.where(np.isfinite(delta),(delta>0).astype(float),np.nan),
                               'random_signed_change':random_delta,'random_accuracy':random_accuracy}
    return results

def cluster_summary(values,users,*,replicates=2000,seed=42):
    """Paired cluster bootstrap: same user multiplicities for every metric column.

    Resamples users, keeps all their windows and computes sequence-weighted means.
    Supports missing sign-ineligible windows via separate column denominators.
    """
    values=np.asarray(values,np.float64)
    if values.ndim==1: values=values[:,None]
    unique,inverse=np.unique(users,return_inverse=True); m=len(unique)
    sums=np.zeros((m,values.shape[1])); counts=np.zeros_like(sums)
    finite=np.isfinite(values)
    np.add.at(sums,inverse,np.where(finite,values,0))
    np.add.at(counts,inverse,finite.astype(float))
    den=counts.sum(0)
    point=np.divide(sums.sum(0),den,out=np.full(len(den),np.nan),where=den>0)
    rng=np.random.default_rng(seed); boot=np.full((replicates,len(den)),np.nan)
    if m:
        for start in range(0,replicates,100):
            take=min(100,replicates-start)
            multiplicity=rng.multinomial(m,np.full(m,1/m),size=take)
            numer=multiplicity@sums; denom=multiplicity@counts
            boot[start:start+take]=np.divide(numer,denom,out=np.full_like(numer,np.nan),where=denom>0)
    low=np.full(len(den),np.nan); high=low.copy()
    for j in range(len(den)):
        valid=boot[:,j][np.isfinite(boot[:,j])]
        if len(valid): low[j],high[j]=np.quantile(valid,[.025,.975])
    return {'mean':point,'ci_low':low,'ci_high':high,'n_valid':den.astype(int),
            'bootstrap_valid':np.isfinite(boot).sum(0),'n_users':m}

def metric_arrays(result,spread):
    if not np.isfinite(spread) or spread<=0: raise RuntimeError('Validation logit spread is zero or nonfinite')
    d=result['signed_change']/spread; r=result['random_signed_change']/spread
    a=result['accuracy']; ra=result['random_accuracy']
    return np.column_stack((a,d,ra,r,a-ra,d-r))

METRICS=('directional_accuracy','mean_signed_change_normalized',
         'random_directional_accuracy','random_mean_signed_change_normalized',
         'directional_accuracy_gap_from_random','normalized_change_gap_from_random')

def summarize_interventions(results,users,y,spread,model,seed,level):
    rows=[]
    for (k,sign),result in results.items():
        v=metric_arrays(result,spread)
        for label,mask in [('overall',np.ones(len(y),bool)),('malicious',y==1),('benign',y==0)]:
            summary=cluster_summary(v[mask],users[mask])
            for j,metric in enumerate(METRICS):
                rows.append({'model':model,'seed':seed,'level':level,'k':k,
                             'sign':'positive' if sign==1 else 'negative','stratum':label,
                             'metric':metric,'estimate':summary['mean'][j],
                             'ci_low':summary['ci_low'][j],'ci_high':summary['ci_high'][j],
                             'n_eligible':summary['n_valid'][j], 'n_total':int(mask.sum()),
                             'n_skipped':int(mask.sum()-summary['n_valid'][j]),
                             'n_users_in_stratum':summary['n_users'],
                             'n_users_eligible':int(len(np.unique(users[mask & np.isfinite(v[:,j])]))),
                             'bootstrap_valid':summary['bootstrap_valid'][j],
                             'validation_logit_sd':spread})
    return rows

def paired_primary(ta,xg,users,y):
    """Seedwise and equal-seed mean contrast on jointly eligible sequences.

    Primary sign is class-supporting (positive for malicious, negative for benign),
    matching historical local directional intervention. Both signs also reported.
    """
    rows=[]
    for sign_name in ('class_supporting','positive','negative'):
        diffs=[]; gaps=[]
        for seed in SEEDS:
            if sign_name=='class_supporting':
                aa=np.where(y==1,ta[seed][(3,1)]['accuracy'],ta[seed][(3,-1)]['accuracy'])
                bb=np.where(y==1,xg[seed][(3,1)]['accuracy'],xg[seed][(3,-1)]['accuracy'])
                ar=np.where(y==1,ta[seed][(3,1)]['random_accuracy'],ta[seed][(3,-1)]['random_accuracy'])
                br=np.where(y==1,xg[seed][(3,1)]['random_accuracy'],xg[seed][(3,-1)]['random_accuracy'])
            else:
                sign=1 if sign_name=='positive' else -1
                aa=ta[seed][(3,sign)]['accuracy']; bb=xg[seed][(3,sign)]['accuracy']
                ar=ta[seed][(3,sign)]['random_accuracy']; br=xg[seed][(3,sign)]['random_accuracy']
            diffs.append(aa-bb); gaps.append((aa-ar)-(bb-br))
        # Aggregate only sequences jointly eligible in all three paired seeds.
        all_d=np.stack(diffs); all_g=np.stack(gaps)
        for seed_index,seed in enumerate((*SEEDS,'mean_of_seeds')):
            d=all_d[seed_index] if seed_index<3 else all_d.mean(0)
            g=all_g[seed_index] if seed_index<3 else all_g.mean(0)
            for label,mask in [('overall',np.ones(len(y),bool)),('malicious',y==1)]:
                s=cluster_summary(np.column_stack((d,g))[mask],users[mask])
                for j,metric in enumerate(('TA2_minus_XGBoost_directional_accuracy','TA2_minus_XGBoost_accuracy_gap_from_random')):
                    rows.append({'seed':seed,'sign':sign_name,'stratum':label,'k':3,'metric':metric,
                                 'estimate':s['mean'][j],'ci_low':s['ci_low'][j],'ci_high':s['ci_high'][j],
                                 'n_paired':s['n_valid'][j],'bootstrap_valid':s['bootstrap_valid'][j]})
    return rows

def ig_summary(attrs,y,seed,relative,residual,differences):
    feature_rows=[]; day_rows=[]; complete=[]; top=[]; source=[]
    from scipy.stats import spearmanr
    # Fixed source-removal importance ranks, larger number = greater importance.
    benchmark=np.array([3,4,5,1,2])
    for label,mask in [('overall',np.ones(len(y),bool)),('malicious',y==1),('benign',y==0)]:
        if not mask.any(): continue
        at=attrs[mask].astype(np.float64)
        fa=np.abs(at).sum(2).mean(0); fs=at.sum(2).mean(0)
        da=np.abs(at).sum(3).mean(0)
        for target in range(9):
            name=f'tree_{target+1}' if target<8 else 'final_logit'
            for j,f in enumerate(FEATURES):
                feature_rows.append({'seed':seed,'stratum':label,'target':name,'feature':f,
                                     'mean_abs_ig_sum_days':fa[target,j],'mean_signed_ig_sum_days':fs[target,j],
                                     'mean_abs_ig_per_day_cell':fa[target,j]/20,
                                     'mean_signed_ig_per_day_cell':fs[target,j]/20})
            for day in range(20):
                day_rows.append({'seed':seed,'stratum':label,'target':name,'day':day+1,
                                 'mean_abs_ig_sum_features':da[target,day],
                                 'mean_abs_ig_per_feature_cell':da[target,day]/13})
            order=np.argsort(-fa[target],kind='stable')[:3]
            top.append({'seed':seed,'stratum':label,'target':name,'top3':[FEATURES[j] for j in order]})
            complete.append({'seed':seed,'stratum':label,'target':name,
                             'median_relative_error':np.median(relative[mask,target]),
                             'p95_relative_error':np.quantile(relative[mask,target],.95),
                             'median_absolute_error':np.median(np.abs(residual[mask,target])),
                             'near_zero_output_difference':int((np.abs(differences[mask,target])<1e-6).sum())})
            importance=np.array([fa[target,list(g)].sum() for g in SOURCE_FEATURES])
            rho=float(spearmanr(importance,benchmark).statistic) if np.ptp(importance)>0 else float('nan')
            source.append({'seed':seed,'stratum':label,'target':name,'spearman_vs_source_removal':rho,
                           'source_mean_abs_ig':dict(zip(SOURCES,importance)),
                           'shared_feature_mass_excluded':float(fa[target,[0,6,12]].sum())})
    return feature_rows,day_rows,complete,top,source

def figures(out,feature_rows,day_rows,metric_rows,primary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import pandas as pd
    f=pd.DataFrame(feature_rows); d=pd.DataFrame(day_rows)
    fig,axes=plt.subplots(2,2,figsize=(15,11),layout='constrained')
    for col,label in enumerate(('malicious','benign')):
        sub=f[(f.stratum==label)&(f.target!='final_logit')]
        a=sub.pivot_table(index='feature',columns='target',values='mean_abs_ig_sum_days',aggfunc='mean').reindex(FEATURES)
        im=axes[0,col].imshow(a.to_numpy(),aspect='auto',cmap='viridis')
        axes[0,col].set(xticks=range(8),xticklabels=range(1,9),yticks=range(13),yticklabels=FEATURES,
                        xlabel='Tree number',ylabel='Raw feature',title=f'{label.title()}: mean |IG|, summed over days')
        fig.colorbar(im,ax=axes[0,col],label='Attribution (tree output units)')
        sub=d[(d.stratum==label)&(d.target=='final_logit')]
        for seed in SEEDS:
            s=sub[sub.seed==seed]; axes[1,col].plot(s.day,s.mean_abs_ig_sum_features,label=f'Seed {seed}')
        axes[1,col].set(xlabel='Day in 20-day window',ylabel='Mean |IG|, summed over features (logit units)',
                       title=f'{label.title()}: final-logit daily profile',xticks=range(1,21,2))
        axes[1,col].legend()
    fig.suptitle('Frozen r5.2 validation · TA2 · 50-step IG · trees averaged across three seeds')
    fig.savefig(Path(out)/'integrated_gradients.png',dpi=300); plt.close(fig)
    m=pd.DataFrame(metric_rows)
    fig,axes=plt.subplots(1,2,figsize=(13,5),layout='constrained')
    for ax,label in zip(axes,('overall','malicious')):
        for model,offset,color in [('TA2',-.12,'#2166ac'),('XGBoost_40',.12,'#b35806')]:
            s=m[(m.model==model)&(m.level=='feature')&(m.stratum==label)&
                (m.metric=='directional_accuracy')&(m.sign=='positive')]
            a=s.groupby('k').estimate.mean()
            ax.plot(a.index+offset,a.to_numpy(),'o-',color=color,label=f'{model} (seed mean)')
        ax.set(xlabel='k intervened inputs',ylabel='Positive-evidence directional accuracy (fraction)',
               title=label.title(),xticks=[1,3,5],ylim=(0,1)); ax.legend()
    fig.suptitle('Local feature interventions · all outcomes and paired CIs in faithfulness.csv')
    fig.savefig(Path(out)/'faithfulness.png',dpi=300); plt.close(fig)
