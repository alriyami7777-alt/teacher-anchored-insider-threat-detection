from common6c import *
from bootstrap6b import bootstrap,counts,selfcheck
import pandas as pd
def prediction(spec,c):
 if spec['model'].endswith('-aug'):return np.load(PRIVATE/f"scores/{spec['model']}_{spec['seed']}_{c}.npy")
 old,s=spec['source_model'],spec['seed']
 if c=='clean':return np.load(P4P/f'scores/{old}_{s}.npz')['scores']
 return np.load(P5/f'private/robustness/{c}_{old}_{s}.npy')
def main():
 selfcheck();f=read(OUT/'MODELS_FROZEN_PHASE6C.json');specs=f['original_models']+f['new_models'];m=dict(np.load(B6P/'cohorts/T20_metadata.npz'));y=m['y'];u=m['cluster'];c=counts(500);assert np.array_equal(c,np.load(P4P/'BOOTSTRAP_USER_MULTIPLICITIES.npy'));boot={};point={};metrics_rows=[];ops=[];positive_users=set(m['user'][y==1]);assert len(positive_users)==25;noninsiders=set(m['user'])-positive_users;assert len(noninsiders)==475;(PRIVATE/'c2_bootstrap').mkdir(exist_ok=True)
 for spec in specs:
  name,s=spec['model'],spec['seed']
  for source,level in conditions():
   cond=key(source,level);p=prediction(spec,cond);pred=p>=spec['threshold'];detected=set(m['user'][(y==1)&pred]);flagged_non=set(m['user'][pred])&noninsiders;ops.append(dict(model=name,seed=s,condition=cond,insiders_detected=len(detected),insiders_total=25,insider_recall=len(detected)/25,noninsiders_flagged=len(flagged_non),noninsiders_total=475,noninsider_flag_rate=len(flagged_non)/475,threshold=spec['threshold'],detected_pseudonyms=sorted(detected),flagged_noninsider_pseudonyms=sorted(flagged_non)))
   for v in VIEWS:
    ix,labels=view(m,v);r=dict(model=name,seed=s,condition=cond,source=source,severity=level,view=v,**metrics(labels[ix],p[ix],spec['threshold']));metrics_rows.append(r);point[(name,s,cond,v)]=r['PR_AUC']
   cache=PRIVATE/f'c2_bootstrap/{name}_{s}_{cond}.npy'
   if cache.exists():bb=np.load(cache)
   else:
    status('C2_AURC_BOOTSTRAP',model=name,seed=s,condition=cond);bb=bootstrap(y,p,u,c);np.save(cache,bb)
   boot[(name,s,cond)]=bb
 curves=[];aurcs=[];aurcpoint={};aurcboot={}
 for spec in specs:
  n,s=spec['model'],spec['seed'];base=boot[(n,s,'clean')]
  for source in (*SOURCES,'noise'):
   levels=(0.,*NOISE) if source=='noise' else (0.,.25,.5,.75,1.);vectors=[]
   for level in levels:
    cond='clean' if level==0 else key(source,level);vectors.append(boot[(n,s,cond)]/base)
    for v in VIEWS:
     cleanAP=point[(n,s,'clean',v)];ap=point[(n,s,cond,v)];curves.append(dict(model=n,seed=s,source=source,severity=level,view=v,PR_AUC=ap,clean_PR_AUC=cleanAP,retention=ap/cleanAP if cleanAP else np.nan))
   aurcboot[(n,s,source)]=np.trapezoid(np.array(vectors),levels,axis=0)/levels[-1]
   for v in VIEWS:
    values=[point[(n,s,'clean' if l==0 else key(source,l),v)]/point[(n,s,'clean',v)] for l in levels];ap=float(np.trapezoid(values,levels)/levels[-1]);aurcpoint[(n,s,source,v)]=ap;aurcs.append(dict(model=n,seed=s,source=source,view=v,AURC=ap))
  aurcboot[(n,s,'source_mean')]=np.mean([aurcboot[(n,s,z)] for z in SOURCES],axis=0)
  for v in VIEWS:
   ap=float(np.mean([aurcpoint[(n,s,z,v)] for z in SOURCES]));aurcpoint[(n,s,'source_mean',v)]=ap;aurcs.append(dict(model=n,seed=s,source='source_mean',view=v,AURC=ap))
 for (n,source,v),g in pd.DataFrame(aurcs).groupby(['model','source','view']):
  if len(g)==3:aurcs.append(dict(model=n,seed='mean_three',source=source,view=v,AURC=float(g.AURC.mean())))
 contrasts=[]
 for n,orig in [('TRACE-aug','TRACE'),('XGBoost-40-aug','XGBoost-40')]:
  vals=np.mean([boot[(n,s,'clean')]-boot[(orig,s,'clean')] for s in SEEDS],axis=0);est=float(np.mean([point[(n,s,'clean','pooled_completed')]-point[(orig,s,'clean','pooled_completed')] for s in SEEDS]));r=dict(contrast=f'{n} minus {orig}',endpoint='clean',metric='PR_AUC',seed='mean_three',view='pooled_completed',**summary(vals,est));r['preserves_clean_performance']=r['ci95_low']>-.03;r['preservation_margin']=-.03;contrasts.append(r)
 for source in (*SOURCES,'source_mean','noise'):
  for a,bn in [('TRACE-aug','TRACE'),('XGBoost-40-aug','XGBoost-40'),('TRACE-aug','XGBoost-40-aug')]:
   vals=np.mean([aurcboot[(a,s,source)]-aurcboot[(bn,s,source)] for s in SEEDS],axis=0);est=float(np.mean([aurcpoint[(a,s,source,'pooled_completed')]-aurcpoint[(bn,s,source,'pooled_completed')] for s in SEEDS]));contrasts.append(dict(contrast=f'{a} minus {bn}',endpoint=source,metric='normalized_retention_AURC',seed='mean_three',view='pooled_completed',**summary(vals,est)))
 assert len(contrasts)==23;holm(contrasts);preserve={r['contrast'].split(' minus ')[0]:r['preserves_clean_performance'] for r in contrasts if r['endpoint']=='clean'}
 for r in contrasts:
  if r['endpoint']!='clean':r['robustness_above_with_Holm']=r['ci95_low']>0 and r['Holm_p']<.05;r['clean_preservation_demonstrated']=preserve[r['contrast'].split(' minus ')[0]]
 csv('C2_ALL_MODEL_VIEW_METRICS.csv',metrics_rows);csv('C2_RETENTION_CURVES.csv',curves);csv('C2_AURC.csv',aurcs);csv('C2_CONTRASTS_HOLM.csv',contrasts);csv('C2_OPERATIONAL_COUNTS.csv',[{k:v for k,v in r.items() if not k.endswith('pseudonyms')} for r in ops]);dump(OUT/'C2_OPERATIONAL_DETAILS.json',ops)
 dump(OUT/'C2_RESULTS.json',dict(utc=utc(),metrics=metrics_rows,curves=curves,AURC=aurcs,contrasts=contrasts,operational=ops,Holm_family_size=23,bootstrap_B=2000,bootstrap_seed=42,views=VIEWS,r52_test_read=False,clean_preservation=preserve));status('C2_ANALYSIS_COMPLETE',contrasts=23)
if __name__=='__main__':main()
