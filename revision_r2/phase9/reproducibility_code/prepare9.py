from common9 import *
def trigger(raw):
 z=raw.copy();old=z[:,-3:,0].copy();z[:,-3:,2]=0;z[:,-3:,8]=0;z[:,-3:,9]=1;z[:,-3:,0]=z[:,-3:,1:6].sum(-1);z[:,-3:,12]=(z[:,-3:,0]>0);z[:,-3:,6]*=np.divide(z[:,-3:,0],old,out=np.zeros_like(old),where=old>0);return z
def main():
 gate();assert not (OUT/'PREPARATION_COMPLETE.json').exists();(PRIVATE/'data').mkdir(exist_ok=True);(PRIVATE/'outcomes').mkdir(exist_ok=True);(PRIVATE/'scores').mkdir(exist_ok=True)
 paths=[P8/'CHATGPT_PHASE8_REPORT.md',P8/'FINAL_AUDIT.json',P8/'Q5_FEATURE_SHIFT_PSI.csv',P4/'MODELS_FROZEN_PHASE4.json',P5/'MODELS_AND_METHODS_FROZEN_PHASE5.json',HP/'DEVELOPMENT_DAILY_SCALER.json',P4P/'HOLDOUT_COHORT.npz',B6P/'cohorts/T20_metadata.npz',P5/'private/HOLDOUT_OPERATIONAL_METADATA.npz',EXPL/'HOLDOUT_SELECTION.json']
 paths+=[ROOT/'phase2_runtime.py',Path(rt.aggregate_common13_windows.__code__.co_filename)]
 for part in ('train','validation'):paths +=[HP/f'tensors/{part}_{k}.npy' for k in ('X','X40','y')]+[HP/f'tensors/{part}_metadata.npz']
 for n in MODELS:
  for s in SEEDS:paths +=[Path(oldspec(n,s)['checkpoint']),P4P/f'scores/{n}_{s}.npz']
 dump(OUT/'SOURCE_INTEGRITY_MANIFEST.json',dict(utc=utc(),sources={str(p):sha(p) for p in paths},prior_phase8_prefix_preserved=True,r52_test_read=False))
 tab=pd.read_csv(P8/'Q5_FEATURE_SHIFT_PSI.csv');sets=[set(tab[(tab.release==r)&(tab.absolute_standardized_mean_shift>.25)].feature) for r in ('r6.1','r6.2')];drop=[f for f in FEATURES if f in sets[0]&sets[1]];keep=[j for j,f in enumerate(FEATURES) if f not in drop];assert keep and drop
 dump(OUT/'L2_FEATURES_FROZEN.json',dict(utc=utc(),dropped=drop,kept=[FEATURES[j] for j in keep],indices=keep,source_sha256=sha(P8/'Q5_FEATURE_SHIFT_PSI.csv'),rule='absolute shift >0.25 in both r6.1 and r6.2; no PSI/labels'))
 # Freeze all unlabelled transfer-only target scalers before any transfer labels are opened.
 s=scaler();m0=np.array(s['original']['mean']);s0=np.array(s['original']['scale']);targets={}
 for release in ('r5.1','r6.1','r6.2'):
  c=Cohort(release);a=c.dense.reshape(-1,13);sm=np.zeros(13);sq=np.zeros(13);N=0
  for lo in range(0,len(a),100000):z=a[lo:lo+100000].astype(float)*s0+m0;sm+=z.sum(0);sq+=(z*z).sum(0);N+=len(z)
  mu=sm/N;sd=np.sqrt(np.maximum(sq/N-mu*mu,0));targets[release]=dict(mean=mu,scale=np.where(sd>0,sd,1),population_SD=sd,daily_rows=N,source=str(c.folder/'scaled_dense_daily.npy'),source_sha256=sha(c.folder/'scaled_dense_daily.npy'),labels_read=False)
 dump(OUT/'L1_TARGET_SCALERS_FROZEN.json',dict(utc=utc(),releases=targets,holdout_scaling=False))
 y=np.load(HP/'tensors/train_y.npy');users=np.load(HP/'tensors/train_metadata.npz')['user'];ins=np.unique(users[y==1]);order=np.random.default_rng(42).permutation(ins);p=np.flatnonzero(y==1);back=np.sort(np.random.default_rng(42).choice(p,int(np.ceil(.01*len(p))),replace=False));s1=scaler()['development'];mu=np.array(s1['mean']);sd=np.array(s1['scale']);records=[]
 for config in CONFIGS:
  dest=PRIVATE/f'data/{config}';dest.mkdir();selected=np.array([],int);poisonusers=[]
  if config.startswith('flip'):
   rho={'flip01':.01,'flip05':.05,'flip10':.1}[config];goal=int(np.ceil(rho*len(p)));picked=[];count=0
   for u in order:
    picked.append(u);count+=np.count_nonzero((users==u)&(y==1))
    if count>=goal:break
   selected=np.flatnonzero(np.isin(users,picked)&(y==1));poisonusers=list(map(pseudo,picked))
  elif config=='backdoor01':selected=back
  np.save(dest/'poison_indices.npy',selected);manifest=dict(utc=utc(),config=config,features=[FEATURES[j] for j in keep] if config=='reduced' else FEATURES,indices=keep if config=='reduced' else list(range(13)),training_population='1500 development users TRAIN only',selection_population='clean development VALIDATION only',original_positive_windows=int(y.sum()),modified_positive_windows=len(selected),actual_modified_fraction=len(selected)/int(y.sum()),affected_users=poisonusers,poison_index_sha256=sha(dest/'poison_indices.npy'),added_trigger_copies=len(back) if config=='backdoor01' else 0)
  for part in ('train','validation'):
   src=np.load(HP/f'tensors/{part}_X.npy',mmap_mode='r');ys=np.load(HP/f'tensors/{part}_y.npy').astype(np.float32);extra=len(back) if config=='backdoor01' and part=='train' else 0;n=len(src)+extra;ix=manifest['indices'];xx=np.lib.format.open_memmap(dest/f'{part}_X.npy',mode='w+',dtype=np.float32,shape=(n,20,len(ix)));tabx=np.lib.format.open_memmap(dest/f'{part}_X40.npy',mode='w+',dtype=np.float32,shape=(n,sum(4 if j<7 else 2 for j in ix)))
   if part=='train' and config!='reduced':ys[selected]=0
   if extra:ys=np.r_[ys,np.zeros(extra,np.float32)]
   for lo in range(0,n,8192):
    hi=min(lo+8192,n);idx=np.arange(lo,hi);sourceidx=np.where(idx<len(src),idx,back[np.maximum(idx-len(src),0).clip(0,len(back)-1)]) if extra else idx;z=np.array(src[sourceidx])
    if config=='backdoor01' and part=='train':
     mask=np.isin(sourceidx,back);raw=z[mask].astype(float)*sd+mu;raw=trigger(raw);z[mask]=((raw-mu)/sd).astype(np.float32)
    z=z[:,:,ix];xx[lo:hi]=z;tabx[lo:hi]=aggregate(z,ix)[0]
   xx.flush();tabx.flush();np.save(dest/f'{part}_y.npy',ys);manifest[part]=dict(windows=n,positive_windows=int(ys.sum()),X_sha256=sha(dest/f'{part}_X.npy'),X40_sha256=sha(dest/f'{part}_X40.npy'),y_sha256=sha(dest/f'{part}_y.npy'))
  dump(dest/'manifest.json',manifest);records.append(manifest);status('DATA_READY',config=config,drop=drop,modified=len(selected))
 dump(OUT/'TRAINING_DATA_FROZEN.json',dict(utc=utc(),conditions=records));dump(OUT/'TRAINING_CODE_FROZEN.json',dict(utc=utc(),runtime_sha256=sha(ROOT/'phase2_runtime.py'),code={n:sha(CODE/n) for n in ('common9.py','prepare9.py','train9.py','training_worker9.py')}));dump(OUT/'PREPARATION_COMPLETE.json',dict(utc=utc(),dropped=drop,configs=list(CONFIGS),r52_test_read=False));status('PREPARATION_COMPLETE')
if __name__=='__main__':main()
