from p5common import *
import pandas as pd
from scipy.special import expit,logit
def margins(p):return logit(np.clip(np.asarray(p,np.float64),np.finfo(float).eps,1-np.finfo(float).eps))
def reliability(y,p):
    bins=np.minimum((p*15).astype(int),14);rows=[];ece=0.
    for b in range(15):
        mask=bins==b;n=int(mask.sum());conf=float(p[mask].mean()) if n else None;freq=float(y[mask].mean()) if n else None
        if n:ece+=n/len(y)*abs(conf-freq)
        rows.append(dict(bin=b,lower=b/15,upper=(b+1)/15,windows=n,mean_probability=conf,observed_positive_fraction=freq))
    return float(ece),rows
def main():
    from sklearn.metrics import brier_score_loss
    from sklearn.linear_model import LogisticRegression
    from scipy.optimize import minimize_scalar
    f=check_frozen();sentinel('E_CALIBRATION_ONCE');data=rt.data();x=data['validation']['X'];yv=data['validation']['y'].astype(np.int8);assert len(yv)==48000
    co=holdout();y=co['y'];dv=device();rows=[];bins=[];maps=[];pooled={}
    for name in ('TA2','XGBoost_40'):
        specs=[s for s in f['models']['development'] if s['model']==name];development=[]
        for spec in specs:
            status('E_DEVELOPMENT_INFERENCE',model=model_name(name),seed=spec['seed']);p=predict_array(spec,x,dv);development.append(margins(p))
        z=np.concatenate(development);yy=np.tile(yv,3)
        if name=='TA2':
            result=minimize_scalar(lambda t:float(np.mean(np.logaddexp(0,z/np.exp(t))-yy*z/np.exp(t))),bounds=(-10,10),method='bounded');T=float(np.exp(result.x));mapping=dict(model='TRACE',method='temperature_scaling',temperature=T,fit_calls=1,optimizer_success=bool(result.success),fit_population='DEVELOPMENT VALIDATION; three fixed seeds pooled equally',rows=len(z),positive_labels=int(yy.sum()),negative_log_likelihood=float(result.fun));transform=lambda p:expit(margins(p)/T)
        else:
            m=LogisticRegression(penalty=None,solver='lbfgs',max_iter=1000);m.fit(z[:,None],yy);a,b=float(m.coef_[0,0]),float(m.intercept_[0]);mapping=dict(model=name,method='Platt_scaling',slope=a,intercept=b,fit_calls=1,fit_population='DEVELOPMENT VALIDATION; three fixed seeds pooled equally',rows=len(z),positive_labels=int(yy.sum()),iterations=int(m.n_iter_[0]));transform=lambda p:expit(a*margins(p)+b)
        maps.append(mapping);dump(OUT/'E_CALIBRATORS.json',maps)
        raw=[];cal=[]
        for spec in specs:
            p=base_score(spec);q=transform(p);raw.append(p);cal.append(q)
            for state,prob in [('raw',p),('calibrated',q)]:
                ece,br=reliability(y,prob);rows.append(dict(model=model_name(name),seed=spec['seed'],state=state,Brier_score=float(brier_score_loss(y,prob)),ECE_15_equal_width=ece,probabilities_at_boundary=int(((p<=0)|(p>=1)).sum()),frozen_operational_thresholds_changed=False))
                bins.extend(dict(model=model_name(name),seed=spec['seed'],state=state,**r) for r in br)
        for state,prob in [('raw',np.concatenate(raw)),('calibrated',np.concatenate(cal))]:
            target=np.tile(y,3);ece,br=reliability(target,prob);rows.append(dict(model=model_name(name),seed='pooled_three_seeds',state=state,Brier_score=float(brier_score_loss(target,prob)),ECE_15_equal_width=ece,frozen_operational_thresholds_changed=False));bins.extend(dict(model=model_name(name),seed='pooled_three_seeds',state=state,**r) for r in br)
        pooled[model_name(name)]=(np.concatenate(raw),np.concatenate(cal))
    save_csv('E_CALIBRATION_METRICS.csv',rows);save_csv('E_RELIABILITY_DATA.csv',bins)
    os.environ['MPLCONFIGDIR']=str(OUT/'matplotlib_cache');import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
    d=pd.DataFrame(bins)
    for name in ('TRACE','XGBoost_40'):
        q=d[(d.model==name)&(d.seed=='pooled_three_seeds')];q.to_csv(OUT/f'E_RELIABILITY_{name}_data.csv',index=False);fig,ax=plt.subplots(figsize=(6.5,5.5));ax.plot([0,1],[0,1],'--',color='0.6',label='Perfect calibration')
        for state in ('raw','calibrated'):
            s=q[(q.state==state)&(q.windows>0)];ax.plot(s.mean_probability,s.observed_positive_fraction,'o-',label=state)
        ax.set(xlabel='Mean predicted probability (15 equal-width bins)',ylabel='Observed malicious-window fraction',title=f'{name} · pooled three-seed HOLDOUT reliability',xlim=(0,1),ylim=(0,1));ax.legend();ax.grid(alpha=.2);fig.tight_layout();fig.savefig(OUT/f'E_RELIABILITY_{name}.png',dpi=300);plt.close(fig)
    dump(OUT/'E_RESULTS.json',dict(calibrators=maps,metrics=rows,reliability=bins,holdout_inference_repeated=False,numerical_rule='Both fitting and application use logit of the frozen probability convention, clipped only to machine-epsilon boundaries; no new holdout forward pass'));status('E_CALIBRATION_COMPLETE',calibrator_fits=2)
if __name__=='__main__':main()
