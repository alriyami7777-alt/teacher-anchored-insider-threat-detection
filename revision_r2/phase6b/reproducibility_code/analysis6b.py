from common6b import *
from bootstrap6b import bootstrap,counts,ci,selfcheck
import pandas as pd
VIEWS=('pooled_completed','train_completed','validation_completed','pooled_offset0','pooled_endpoint')
METRICS=('PR_AUC','F1')
def summary(values,estimate):
 r=ci(values,estimate);v=np.asarray(values);v=v[np.isfinite(v)]
 p=min(1.,2*min((1+np.sum(v<=0))/(1+len(v)),(1+np.sum(v>=0))/(1+len(v)))) if len(v) else 1.
 r.update(raw_p=float(p),CI_decision='above' if r['ci95_low']>0 else 'below' if r['ci95_high']<0 else 'comparable',status='ok' if len(v) else 'unavailable_no_valid_replicates');return r
def holm(rows):
 n=len(rows);order=np.argsort([r.get('raw_p',1.) for r in rows],kind='stable');running=0.
 for j,i in enumerate(order):
  r=rows[i];running=max(running,min(1.,(n-j)*r.get('raw_p',1.)));r['Holm_p']=running;r['Holm_family_size']=n;r['Holm_decision']='above' if running<.05 and r.get('estimate',0)>0 else 'below' if running<.05 and r.get('estimate',0)<0 else 'comparable'
 return rows
def meta(t):return dict(np.load(PRIVATE/f'cohorts/T{t}_metadata.npz'))
def view(m,v):
 mask=np.ones(len(m['y']),bool)
 if v=='train_completed':mask=m['partition']=='train'
 elif v=='validation_completed':mask=m['partition']=='validation'
 elif v=='pooled_offset0':mask=m['offset0'].astype(bool)
 return np.flatnonzero(mask),m['endpoint'] if v=='pooled_endpoint' else m['y']
def pred(name,s,condition='original'):return np.load(PRIVATE/f'scores/{name}_{s}_{condition}.npy')
def calculations(spec,condition,m,v,c,cachetag=None,selected=None):
 name,s=spec['model'],spec['seed'];idx,y=view(m,v)
 if selected is not None:idx=selected
 pp=pred(name,s,condition)[idx];yy=y[idx].astype(np.int8);uu=m['cluster'][idx].astype(np.int16);t=spec['threshold'];point=metrics(yy,pp,t)
 point['prevalence']=float(yy.mean());point['ranking_excess']=point['PR_AUC']/point['prevalence'] if point['prevalence'] else np.nan;point['AP_minus_prevalence']=point['PR_AUC']-point['prevalence'];point['users']=len(np.unique(uu));point['positive_users']=len(np.unique(uu[yy==1]));point['alerts_per_1000']=float((pp>=t).mean()*1000)
 file=PRIVATE/'bootstrap'/f'{cachetag or v}_{name}_{s}_{condition}.npz';file.parent.mkdir(parents=True,exist_ok=True)
 if file.exists():boot=dict(np.load(file))
 else:
  oldpath=P4P/'bootstrap'/f"{v}_{spec.get('source_model')}_{s}.npy"
  if selected is None and spec.get('reused_phase4') and condition=='original' and oldpath.exists():
   ap=np.load(oldpath);assert np.allclose(ap[:2],bootstrap(yy,pp,uu,c[:2]),equal_nan=True,atol=1e-12);flag=pp>=t;n=500;tp=np.bincount(uu,weights=(yy==1)&flag,minlength=n);fp=np.bincount(uu,weights=(yy==0)&flag,minlength=n);fn=np.bincount(uu,weights=(yy==1)&~flag,minlength=n);a=c@tp;b=c@fp;d=c@fn;den=2*a+b+d;boot=dict(PR_AUC=ap,F1=np.divide(2*a,den,out=np.zeros_like(a),where=den>0))
  else:boot=bootstrap(yy,pp,uu,c,t)
  np.savez_compressed(file,**boot)
 return point,boot
def unavailable(**kw):return dict(**kw,status='unavailable_missing_model_or_scores',estimate=np.nan,ci95_low=np.nan,ci95_high=np.nan,raw_p=1.,CI_decision='comparable',valid_bootstrap_replicates=0)
def main():
 selfcheck();c=counts(500);assert np.array_equal(c,np.load(P4P/'BOOTSTRAP_USER_MULTIPLICITIES.npy'));f=read(OUT/'MODELS_FROZEN_PHASE6B.json');specs={(r['model'],r['seed']):r for r in f['models']};ms={t:meta(t) for t in (10,20,30)}
 cache={};rows=[];insiders=[]
 for out in read(OUT/'SCORING_COMPLETE.json')['outcomes']:
  if out['state']!='COMPLETE':continue
  name,s,cond=out['model'],out['seed'],out['condition'];spec=specs[(name,s)];m=ms[spec['length']]
  assert sha(PRIVATE/f'scores/{name}_{s}_{cond}.npy')==out['prediction_sha256']
  p=pred(name,s,cond);positive=m['y']==1;detected=np.unique(m['user'][positive&(p>=spec['threshold'])]);allpos=np.unique(m['user'][positive]);assert len(allpos)==25
  insiders.append(dict(model=name,seed=s,condition=cond,detected_insiders=len(detected),total_insiders=25,insider_recall=len(detected)/25,detected_pseudonyms=detected.tolist(),threshold=spec['threshold'],length=spec['length']))
  for v in VIEWS:
   status('BOOTSTRAP',model=name,seed=s,condition=cond,view=v);point,b=calculations(spec,cond,m,v,c);cache[(name,s,cond,v)]=(point,b);rows.append(dict(model=name,seed=s,condition=cond,view=v,length=spec['length'],**point))
 for (name,cond,v),g in pd.DataFrame(rows).groupby(['model','condition','view'],sort=False):
  if len(g)!=3:continue
  row=dict(model=name,seed='mean_three',condition=cond,view=v,length=int(g.length.iloc[0]),windows=int(g.windows.iloc[0]),positive_windows=int(g.positive_windows.iloc[0]),prevalence=float(g.prevalence.iloc[0]),users=int(g.users.iloc[0]),positive_users=int(g.positive_users.iloc[0]),threshold=None)
  for k in ('PR_AUC','F1','precision','recall','ranking_excess','AP_minus_prevalence','alerts_per_1000'):row[k]=float(g[k].mean())
  rows.append(row)
 csv('ALL_MODEL_VIEWS.csv',rows);csv('INSIDER_RECALL.csv',[{k:v for k,v in r.items() if k!='detected_pseudonyms'} for r in insiders]);dump(OUT/'INSIDER_RECALL.json',insiders)
 contrastdefs=[('H1','XGBoost-260','XGBoost-40','original','original'),('H1','RF-260','RF-40','original','original'),('H1','LightGBM-260','LightGBM-40','original','original'),('H1','TRACE','XGBoost-260','original','original'),('H1','TRACE','RF-260','original','original'),('H2','MLP-260','MLP-40','original','original'),('H3','TRACE','TRACE-orderfree','original','original')]
 contrastdefs += [('H4',n,n,a,'original') for n in ('TRACE','XGBoost-260') for a in ('reversed','fixed_shuffle','recent1','recent5','recent10')]
 contrastdefs += [('H5',n+f'-{t}',n,'original','original') for n in ('TRACE','XGBoost-40') for t in (30,10)]
 assert len(contrastdefs)==21;contrasts=[];matches=[]
 for h,a,b,ac,bc in contrastdefs:
  label=f'{a} {ac} minus {b} {bc}'
  for v in VIEWS:
   points={};boots={};extra={}
   for s in SEEDS:
    if (a,s,ac,v) not in cache or (b,s,bc,v) not in cache:continue
    if h=='H5':
     ma,mb=ms[specs[(a,s)]['length']],ms[20];ia,ya=view(ma,v);ib,yb=view(mb,v)
     ka=pd.MultiIndex.from_arrays([ma['user'][ia],ma['partition'][ia],ma['end_date'][ia]]);kb=pd.MultiIndex.from_arrays([mb['user'][ib],mb['partition'][ib],mb['end_date'][ib]]);assert ka.is_unique and kb.is_unique;loc=kb.get_indexer(ka);keep=loc>=0;ai=ia[keep];bi=ib[loc[keep]]
     assert np.array_equal(ma['cluster'][ai],mb['cluster'][bi]);extra=dict(matched_windows=len(ai),matched_users=len(np.unique(ma['cluster'][ai])),matched_label_disagreements=int(np.sum(ya[ai]!=yb[bi])),match_key='pseudonym, period, end_date',paired_population='intersection of each length-specific view')
     if s==42:matches.append(dict(contrast=label,view=v,**extra))
     if not len(ai):continue
     pa,ba=calculations(specs[(a,s)],ac,ma,v,c,f'H5_{a}_{v}_left',ai);pb,bb=calculations(specs[(b,s)],bc,mb,v,c,f'H5_{a}_{v}_right',bi)
    else:pa,ba=cache[(a,s,ac,v)];pb,bb=cache[(b,s,bc,v)]
    points[s]=(pa,pb);boots[s]=(ba,bb)
   for metric in METRICS:
    for s in (*SEEDS,'mean_three'):
     keys=dict(H=h,contrast=label,view=v,metric=metric,seed=s,**extra)
     seeds=SEEDS if s=='mean_three' else (s,)
     if any(z not in boots for z in seeds):contrasts.append(unavailable(**keys));continue
     values=np.mean([boots[z][0][metric]-boots[z][1][metric] for z in seeds],axis=0);est=float(np.mean([points[z][0][metric]-points[z][1][metric] for z in seeds]));contrasts.append(dict(**keys,**summary(values,est)))
 assert len(contrasts)==840;holm(contrasts);csv('H1_H5_FULL_CONTRASTS_HOLM.csv',contrasts);csv('H5_MATCHED_END_DAYS.csv',matches)
 dump(OUT/'H1_H5_RESULTS.json',dict(models=rows,insider_recall=insiders,contrasts=contrasts,matched_end_days=matches,Holm_family_size=840,ranking_excess_definition='PR_AUC / prevalence',bootstrap_seed=42,bootstrap_replicates=2000,r52_test_read=False))
 explanation_analysis();status('ANALYSIS_COMPLETE',contrasts=len(contrasts))
def load_interventions(path):
 out={}
 with np.load(path) as z:
  for key in z.files:
   a,b,name=key.split('_',2);out.setdefault((int(a[1:]),int(b[1:])),{})[name]=z[key]
 return out
def cluster_effect(values,users):
 # Matches the inherited Phase 4 engine: multinomial whole-user draws in batches of 100.
 groups,u=np.unique(users,return_inverse=True);n=len(groups);valid=np.isfinite(values);sums=np.bincount(u,weights=np.where(valid,values,0),minlength=n);ns=np.bincount(u,weights=valid.astype(float),minlength=n);rng=np.random.default_rng(42);draws=[]
 for lo in range(0,2000,100):
  c=rng.multinomial(n,np.full(n,1/n),size=min(100,2000-lo));den=c@ns;num=c@sums;draws.extend(np.divide(num,den,out=np.full_like(num,np.nan),where=den>0))
 est=float(np.sum(sums)/np.sum(ns)) if np.sum(ns) else np.nan
 return summary(np.array(draws),est)|dict(n_eligible=int(valid.sum()),n_total=len(values),n_skipped=int((~valid).sum()),n_users_in_stratum=n,n_users_eligible=len(np.unique(users[valid])))
def explanation_analysis():
 ref=read(P4P/'EXPLANATION_DEVELOPMENT_REFERENCES.json');co=np.load(EXPL/'cohort_pseudonyms.npz');y=co['y'];users=co['user'];rows=[];reusedparity=[]
 old=pd.read_csv(EXPL/'faithfulness.csv')
 for level,ks in [('temporal',(1,3,5,10)),('feature',(1,3,5)),('tree',(1,2,3))]:
  family=[]
  for s in SEEDS:
   path=EXPL/f'TA2_seed{s}_feature_interventions.npz' if level=='feature' else PRIVATE/f'explanation/seed{s}/{level}_interventions.npz';spread=float(ref['validation_logit_sd']['TA2'][str(s)])
   result=load_interventions(path) if path.exists() else {}
   for k in ks:
    for signname in (('class_supporting',) if level=='temporal' else ('positive','negative','class_supporting')):
     if (k,0) in result and level=='temporal':r=result[(k,0)]
     elif signname=='class_supporting' and (k,1) in result and (k,-1) in result:r={key:np.where(y==1,result[(k,1)][key],result[(k,-1)][key]) for key in ('signed_change','random_signed_change','accuracy','random_accuracy')}
     else:r=result.get((k,1 if signname=='positive' else -1))
     for stratum,mask in [('overall',np.ones(len(y),bool)),('malicious',y==1),('benign',y==0)]:
      for metric in ('normalized_change_gap_from_random','directional_accuracy_gap_from_random'):
       key=dict(H='H6',level=level,seed=s,k=k,sign=signname,stratum=stratum,metric=metric,validation_logit_sd=spread,random_controls=200 if level=='feature' else 25)
       if r is None:family.append(unavailable(**key));continue
       values=(r['signed_change']-r['random_signed_change'])/spread if metric=='normalized_change_gap_from_random' else r['accuracy']-r['random_accuracy'];row=key|cluster_effect(values[mask],users[mask]);family.append(row)
       if level=='feature' and signname!='class_supporting':
        existing=old.loc[(old.model=='TA2')&(old.seed==s)&(old.level=='feature')&(old.k==k)&(old.sign==signname)&(old.stratum==stratum)&(old.metric==metric)].iloc[0]
        err=max(abs(row['estimate']-existing.estimate),abs(row['ci95_low']-existing.ci_low),abs(row['ci95_high']-existing.ci_high));assert err<1e-10;reusedparity.append(dict(seed=s,k=k,sign=signname,stratum=stratum,metric=metric,max_abs_error=err))
  holm(family);rows+=family;csv(f'H6_{level.upper()}_CONTRASTS_HOLM.csv',family)
 csv('H6_ALL_EXPLANATION_EFFECTS.csv',rows);dump(OUT/'H6_RESULTS.json',dict(effects=rows,feature_reuse_numerical_parity=reusedparity,level_family_sizes={level:sum(r['level']==level for r in rows) for level in ('temporal','feature','tree')},r52_test_read=False))
if __name__=='__main__':main()
