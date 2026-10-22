"""Paired user-cluster AP comparisons; frozen before outer predictions."""
import numpy as np
from sklearn.metrics import average_precision_score


def prepare_ap(y,p):
    y=np.asarray(y,dtype=np.int8);p=np.asarray(p,dtype=np.float64)
    if y.shape!=p.shape or y.ndim!=1 or not np.isfinite(p).all() or not np.isin(y,[0,1]).all(): raise ValueError('Invalid AP arrays')
    order=np.argsort(-p,kind='stable')
    ends=np.r_[np.flatnonzero(p[order][1:]!=p[order][:-1]),len(y)-1]
    return order,ends,y[order]


def weighted_ap(prepared,weights):
    order,ends,y=prepared;w=np.asarray(weights,dtype=np.float64)[order]
    tp=np.cumsum(w*y)[ends];total=np.cumsum(w)[ends]
    if tp[-1]<=0 or total[-1]<=tp[-1]: return float('nan')
    positive_in_group=np.diff(np.r_[0.,tp])
    precision=np.divide(tp,total,out=np.zeros_like(tp),where=total>0)
    return float((precision*positive_in_group).sum()/tp[-1])


def paired_cluster_ap(y,arm_a,arm_b,user_index,n_users,attempts=2000,seed=42):
    y=np.asarray(y,dtype=np.int8);a=np.asarray(arm_a,dtype=float);b=np.asarray(arm_b,dtype=float)
    users=np.asarray(user_index,dtype=np.int64)
    if a.shape!=b.shape or a.ndim!=2 or a.shape[1]!=len(y) or users.shape!=y.shape or not len(y): raise ValueError('Pairing shape')
    if users.min()<0 or users.max()>=n_users or not np.array_equal(np.unique(users),np.arange(n_users)): raise ValueError('Cluster membership')
    prepared_a=[prepare_ap(y,p) for p in a];prepared_b=[prepare_ap(y,p) for p in b]
    observed=float(np.mean([average_precision_score(y,pa)-average_precision_score(y,pb) for pa,pb in zip(a,b)]))
    rng=np.random.default_rng(seed);draws=[];invalid=0
    for _ in range(attempts):
        counts=np.bincount(rng.integers(0,n_users,size=n_users),minlength=n_users)
        weights=counts[users]
        delta=[weighted_ap(pa,weights)-weighted_ap(pb,weights) for pa,pb in zip(prepared_a,prepared_b)]
        if not np.isfinite(delta).all(): invalid+=1;continue
        draws.append(float(np.mean(delta)))
    sufficient=len(draws)>=int(np.ceil(.95*attempts))
    ci=np.percentile(draws,[2.5,97.5],method='linear').tolist() if draws else None
    lower=float(np.percentile(draws,5,method='linear')) if draws else None
    return dict(observed_mean_seed_ap_difference=observed,attempted_draws=attempts,valid_draws=len(draws),invalid_single_class_draws=invalid,
                paired_95_percentile_interval=ci,one_sided_95_lower_bound=lower,interval_reliable=sufficient,
                practical_gain_margin=.005,primary_improvement_rule_met=bool(sufficient and observed>=.005 and ci[0]>0),
                random_seed=seed,rng='numpy.default_rng PCG64',percentile_method='linear',
                scope='Conditional on fitted models and observed calendar; no selection/time-shock/retraining uncertainty'),np.asarray(draws)
