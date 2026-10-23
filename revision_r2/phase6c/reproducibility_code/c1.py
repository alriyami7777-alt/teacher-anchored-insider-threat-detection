from common6c import *
import argparse,subprocess
from bootstrap6b import bootstrap
import pandas as pd
CP=PRIVATE/'c1';MAXB=50000
def meta(t):return dict(np.load(B6P/f'cohorts/T{t}_metadata.npz'))
def identity(r):
 return tuple(str(r.get(k,'')) for k in ('H','contrast','view','metric','seed')) if r['H']!='H6' else tuple(str(r[k]) for k in ('H','level','seed','k','sign','stratum','metric'))
def prepare():
 if (CP/'READY.json').exists():
  assert (OUT/'C1_PREFIX_VERIFICATION.json').exists(),'Complete exact-prefix verification before extending'
  return read(CP/'READY.json')
 CP.mkdir(parents=True,exist_ok=True);(CP/'indices').mkdir(exist_ok=True)
 f=read(B6/'MODELS_FROZEN_PHASE6B.json');ms={t:meta(t) for t in (10,20,30)};specs={(r['model'],r['seed']):r for r in f['models']};requests=[];lookup={}
 def add(spec,c,v,tag=None,indices=None):
  n,s,t=spec['model'],spec['seed'],spec['length'];i=len(requests);filename=f'{tag or v}_{n}_{s}_{c}.npz';old=B6P/'bootstrap'/filename;assert old.exists()
  if indices is not None:np.save(CP/f'indices/{i}.npy',indices)
  requests.append(dict(index=i,model=n,seed=s,condition=c,view=v,length=t,threshold=spec['threshold'],old_bootstrap_path=str(old),old_bootstrap_sha256=sha(old),selected_indices=indices is not None,prediction_path=str(B6P/f'scores/{n}_{s}_{c}.npy'),prediction_sha256=sha(B6P/f'scores/{n}_{s}_{c}.npy')));return i
 for r in read(B6/'SCORING_COMPLETE.json')['outcomes']:
  assert r['state']=='COMPLETE'
  for v in VIEWS:lookup[(r['model'],r['seed'],r['condition'],v)]=add(specs[(r['model'],r['seed'])],r['condition'],v)
 defs=[('H1','XGBoost-260','XGBoost-40','original','original'),('H1','RF-260','RF-40','original','original'),('H1','LightGBM-260','LightGBM-40','original','original'),('H1','TRACE','XGBoost-260','original','original'),('H1','TRACE','RF-260','original','original'),('H2','MLP-260','MLP-40','original','original'),('H3','TRACE','TRACE-orderfree','original','original')]+[('H4',n,n,c,'original') for n in ('TRACE','XGBoost-260') for c in ('reversed','fixed_shuffle','recent1','recent5','recent10')]+[('H5',n+f'-{t}',n,'original','original') for n in ('TRACE','XGBoost-40') for t in (30,10)]
 oldrows=read(B6/'H1_H5_RESULTS.json')['contrasts'];oldlookup={identity(r):r for r in oldrows};maps=[]
 for h,a,b,ac,bc in defs:
  label=f'{a} {ac} minus {b} {bc}'
  for v in VIEWS:
   pairs={}
   for s in SEEDS:
    if h=='H5':
     ma,mb=ms[specs[(a,s)]['length']],ms[20];ia,ya=view(ma,v);ib,yb=view(mb,v);ka=pd.MultiIndex.from_arrays([ma['user'][ia],ma['partition'][ia],ma['end_date'][ia]]);kb=pd.MultiIndex.from_arrays([mb['user'][ib],mb['partition'][ib],mb['end_date'][ib]]);assert ka.is_unique and kb.is_unique;loc=kb.get_indexer(ka);keep=loc>=0;ai=ia[keep];bi=ib[loc[keep]];assert np.array_equal(ma['cluster'][ai],mb['cluster'][bi]);pairs[s]=(add(specs[(a,s)],ac,v,f'H5_{a}_{v}_left',ai),add(specs[(b,s)],bc,v,f'H5_{a}_{v}_right',bi))
    else:pairs[s]=(lookup[(a,s,ac,v)],lookup[(b,s,bc,v)])
   for metric in ('PR_AUC','F1'):
    for s in (*SEEDS,'mean_three'):
     old=oldlookup[(h,label,v,metric,str(s))];seeds=SEEDS if s=='mean_three' else (s,);maps.append(dict(old=old,left=[pairs[z][0] for z in seeds],right=[pairs[z][1] for z in seeds],metric_index=0 if metric=='PR_AUC' else 1))
 assert len(requests)==480 and len(maps)==840 and {identity(r['old']) for r in maps}=={identity(r) for r in oldrows}
 shape=(len(requests),MAXB,2);arr=np.lib.format.open_memmap(CP/'model_bootstraps.npy',mode='w+',dtype=np.float64,shape=shape)
 for r in requests:
  z=np.load(r['old_bootstrap_path']);assert len(z['PR_AUC'])==2000;arr[r['index'],:2000,0]=z['PR_AUC'];arr[r['index'],:2000,1]=z['F1']
 arr.flush();del arr
 # Exact integer-draw stream used by Phase 6B; never infer a resampling population from scores.
 c=np.lib.format.open_memmap(CP/'counts500.npy',mode='w+',dtype=np.int16,shape=(MAXB,500));rng=np.random.default_rng(42)
 for i in range(MAXB):c[i]=np.bincount(rng.integers(0,500,size=500),minlength=500)
 assert np.array_equal(c[:2000],np.load(P4P/'BOOTSTRAP_USER_MULTIPLICITIES.npy'));c.flush();del c
 effects=read(B6/'H6_RESULTS.json')['effects'];co=np.load(EXPL/'cohort_pseudonyms.npz');users=co['user'];y=co['y'];summ=np.zeros((396,500));ns=summ.copy();groups=[]
 from analysis6b import load_interventions
 loaded={};ref=read(P4P/'EXPLANATION_DEVELOPMENT_REFERENCES.json')
 for i,r in enumerate(effects):
  lev,s,k,sign,stratum,metric=(r[z] for z in ('level','seed','k','sign','stratum','metric'));cachekey=(lev,s)
  if cachekey not in loaded:
   p=EXPL/f'TA2_seed{s}_feature_interventions.npz' if lev=='feature' else B6P/f'explanation/seed{s}/{lev}_interventions.npz';loaded[cachekey]=load_interventions(p)
  data=loaded[cachekey]
  if lev=='temporal':z=data[(k,0)]
  elif sign=='class_supporting':z={key:np.where(y==1,data[(k,1)][key],data[(k,-1)][key]) for key in ('signed_change','random_signed_change','accuracy','random_accuracy')}
  else:z=data[(k,1 if sign=='positive' else -1)]
  spread=ref['validation_logit_sd']['TA2'][str(s)];values=(z['signed_change']-z['random_signed_change'])/spread if metric=='normalized_change_gap_from_random' else z['accuracy']-z['random_accuracy'];mask=np.ones(len(y),bool) if stratum=='overall' else y==(1 if stratum=='malicious' else 0);u,inv=np.unique(users[mask],return_inverse=True);v=values[mask];valid=np.isfinite(v);m=len(u);summ[i,:m]=np.bincount(inv,weights=np.where(valid,v,0),minlength=m);ns[i,:m]=np.bincount(inv,weights=valid.astype(float),minlength=m);groups.append(m);assert np.isclose(np.sum(summ[i])/np.sum(ns[i]),r['estimate'],atol=1e-10)
 np.savez_compressed(CP/'effect_summaries.npz',sums=summ,counts=ns,groups=np.array(groups));earr=np.lib.format.open_memmap(CP/'effect_bootstraps.npy',mode='w+',dtype=np.float64,shape=(396,MAXB))
 for m in sorted(set(groups)):
  rng=np.random.default_rng(42);cm=np.lib.format.open_memmap(CP/f'effect_counts{m}.npy',mode='w+',dtype=np.int16,shape=(MAXB,m))
  for lo in range(0,MAXB,100):cm[lo:lo+100]=rng.multinomial(m,np.full(m,1/m),size=min(100,MAXB-lo))
  cm.flush();del cm
 earr.flush();del earr
 fill_effects(0,2000)
 manifest=dict(utc=utc(),requests=requests,contrasts=maps,effects=effects,source_hashes={str(p):sha(p) for p in [B6/'H1_H5_RESULTS.json',B6/'H6_RESULTS.json',B6/'FINAL_AUDIT.json',B6/'MODELS_FROZEN_PHASE6B.json']},code_hashes={n:sha(CODE/n) for n in ('c1.py','common6c.py')},families=dict(H1_H5=840,temporal=72,feature=162,tree=162),r52_test_read=False,no_new_scoring=True)
 dump(CP/'READY.json',manifest);dump(CP/'PROGRESS.json',dict(completed_B=2000,target_B=MAXB,blocks=[]));finalize(2000,verify_prefix=True);return manifest
def chunk(start,stop):
 f=read(CP/'READY.json');assert all(sha(CODE/n)==h for n,h in f['code_hashes'].items());co={t:meta(t) for t in (10,20,30)};c=np.load(CP/'counts500.npy',mmap_mode='r')[start:stop];arr=np.load(CP/'model_bootstraps.npy',mmap_mode='r+');started=time.perf_counter()
 for r in f['requests']:
  m=co[r['length']];idx,y=view(m,r['view'])
  if r['selected_indices']:idx=np.load(CP/f"indices/{r['index']}.npy")
  p=np.load(r['prediction_path'],mmap_mode='r')[idx];out=bootstrap(y[idx].astype(np.int8),p,m['cluster'][idx].astype(np.int16),c,r['threshold']);arr[r['index'],start:stop,0]=out['PR_AUC'];arr[r['index'],start:stop,1]=out['F1']
  if r['index']%80==0:print('C1_CHUNK',start,stop,r['index'],len(f['requests']),flush=True)
 arr.flush();del arr
 fill_effects(start,stop);dump(CP/f'block_{start}_{stop}.json',dict(utc=utc(),start=start,stop=stop,seconds=time.perf_counter()-started,model_requests=480,effects=396,complete=True));print('C1_BLOCK_COMPLETE',start,stop,flush=True)
def fill_effects(start,stop):
 e=np.load(CP/'effect_summaries.npz');sums=e['sums'];ns=e['counts'];groups=e['groups'];out=np.load(CP/'effect_bootstraps.npy',mmap_mode='r+');mat={m:np.load(CP/f'effect_counts{m}.npy',mmap_mode='r') for m in np.unique(groups)}
 # Match Phase 6B's single-metric GEMV and exact 100-replicate cadence; a multi-metric GEMM can change floating-point zero-tail counts.
 for i,m in enumerate(groups):
  for lo in range(start,stop,100):
   hi=min(lo+100,stop);c=np.array(mat[m][lo:hi],dtype=np.int64);den=c@ns[i,:m];num=c@sums[i,:m];out[i,lo:hi]=np.divide(num,den,out=np.full_like(num,np.nan),where=den>0)
 out.flush()
def repair_prefix():
 f=read(CP/'READY.json');old=f['code_hashes'];fill_effects(0,2000);f['code_hashes']={n:sha(CODE/n) for n in ('c1.py','common6c.py')};dump(CP/'READY.json',f);finalize(2000,verify_prefix=True);dump(OUT/'C1_NUMERICAL_CADENCE_RECEIPT.json',dict(utc=utc(),old_code_hashes=old,new_code_hashes=f['code_hashes'],reason='Restore exact Phase 6B per-metric 100-row GEMV cadence before any extension; no statistical definition changed',no_scoring=True,extension_started=False))
def comparison(old,new,B,family):
 keys={k:v for k,v in old.items() if k not in ('ci95_low','ci95_high','raw_p','Holm_p','Holm_decision','Holm_family_size','CI_decision','valid_bootstrap_replicates','attempted_replicates','bootstrap_seed','cluster','status')};keys.update(family=family,B_old=2000,B_new=B)
 for prefix,r in [('old',old),('new',new)]:
  for k in ('ci95_low','ci95_high','raw_p','Holm_p','Holm_decision','CI_decision','valid_bootstrap_replicates'):keys[prefix+'_'+k]=r[k]
 keys['Holm_family_size']=new['Holm_family_size'];return keys
def finalize(B,verify_prefix=False):
 f=read(CP/'READY.json');arr=np.load(CP/'model_bootstraps.npy',mmap_mode='r');families={};h=[]
 for r in f['contrasts']:
  delta=np.mean([arr[a,:B,r['metric_index']]-arr[b,:B,r['metric_index']] for a,b in zip(r['left'],r['right'])],axis=0);h.append(summary(delta,r['old']['estimate']))
 holm(h);families['H1_H5']=[comparison(r['old'],new,B,'H1_H5') for r,new in zip(f['contrasts'],h)]
 ea=np.load(CP/'effect_bootstraps.npy',mmap_mode='r')
 for lev in ('temporal','feature','tree'):
  indices=[i for i,r in enumerate(f['effects']) if r['level']==lev];rows=[summary(ea[i,:B],f['effects'][i]['estimate']) for i in indices];holm(rows);families[lev]=[comparison(f['effects'][i],r,B,lev) for i,r in zip(indices,rows)]
 allrows=sum(families.values(),[]);assert len(allrows)==1236
 if verify_prefix:
  assert B==2000
  for r in allrows:
   for k in ('ci95_low','ci95_high','raw_p','Holm_p'):
    assert np.isclose(r['old_'+k],r['new_'+k],atol=1e-10,equal_nan=True),(r,k)
   assert r['old_CI_decision']==r['new_CI_decision'] and r['old_Holm_decision']==r['new_Holm_decision']
  dump(OUT/'C1_PREFIX_VERIFICATION.json',dict(utc=utc(),all_1236_B2000_statistics_identical=True,family_sizes=f['families'],no_new_scoring=True));return
 csv('C1_FULL_SIDE_BY_SIDE.csv',allrows)
 for name,rows in families.items():csv(f'C1_{name}_SIDE_BY_SIDE.csv',rows)
 progress=read(CP/'PROGRESS.json');dump(OUT/'C1_RESULTS.json',dict(utc=utc(),target_B=MAXB,completed_B=B,family_sizes=f['families'],comparisons=allrows,progress=progress,no_new_scoring=True,r52_test_read=False));status('C1_COMPLETE',B=B,tests=len(allrows))
def coordinate():
 started=time.perf_counter();f=prepare();progress=read(CP/'PROGRESS.json');campaign=CP/'CAMPAIGN_START.json'
 if campaign.exists():origin=read(campaign)['unix_time']
 else:origin=time.time();dump(campaign,dict(utc=utc(),unix_time=origin,budget_seconds=21600))
 while progress['completed_B']<MAXB:
  elapsed=time.time()-origin;remaining=21600-elapsed
  if remaining<=30:break
  step=min(2000,MAXB-progress['completed_B'])
  if progress['blocks']:
   rate=max(z['seconds']/(z['stop']-z['start']) for z in progress['blocks'][-3:]);step=min(step,int((remaining-30)/max(rate,1e-6)/1.2)//100*100)
  if step<100:break
  lo=progress['completed_B'];hi=lo+step;log=PRIVATE/'logs'/f'C1_block_{lo}_{hi}.log';status('C1_BOOTSTRAP_BLOCK',start=lo,stop=hi,target=MAXB)
  with log.open('w',encoding='utf-8') as handle:
   p=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/'c1.py'),'--start',str(lo),'--stop',str(hi)],stdout=handle,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
   try:rc=p.wait(timeout=min(7200,max(1,remaining-10)))
   except subprocess.TimeoutExpired:p.kill();p.wait();rc='TIMEOUT'
  if rc!=0:progress['failure']=dict(state='TIMEOUT' if rc=='TIMEOUT' else 'FAILED',start=lo,stop=hi,reason=f'Exit {rc}; incomplete tail excluded');dump(CP/'PROGRESS.json',progress);break
  block=read(CP/f'block_{lo}_{hi}.json');progress['blocks'].append(block);progress['completed_B']=hi;progress['elapsed_seconds']=time.time()-origin;dump(CP/'PROGRESS.json',progress)
 finalize(progress['completed_B']);dump(OUT/'C1_COMPLETE.json',dict(utc=utc(),B=progress['completed_B'],target_B=MAXB,wall_seconds=time.perf_counter()-started,fallback=progress['completed_B']<MAXB))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--start',type=int);p.add_argument('--stop',type=int);p.add_argument('--finalize',type=int);p.add_argument('--repair-prefix',action='store_true');a=p.parse_args()
 if a.start is not None:chunk(a.start,a.stop)
 elif a.finalize:finalize(a.finalize)
 elif a.repair_prefix:repair_prefix()
 else:coordinate()
