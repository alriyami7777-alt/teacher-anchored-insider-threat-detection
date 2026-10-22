from common6b import *
def main():
 pr=(H/'PREREGISTRATION_R2_HOLDOUT.md').read_bytes();mark=b'\n\nAmendment 5 SHA-256 receipt';pos=pr.index(mark);assert hashlib.sha256(pr[:pos]).hexdigest()=='c4d82ec9ba726877bd436a744b3ec9dc38e67d3b189790327ec2931568a8b3b2'
 assert hashlib.sha256(pr[:19979]).hexdigest()=='5c6d6df2ecb33da9a5dd55b711de7150a5079e80020b88256ba0162647d9ad8c'
 PRIVATE.mkdir(parents=True,exist_ok=True)
 dump(OUT/'AMENDMENT5_RECEIPT.json',dict(utc='2026-10-22T11:37:35.9827764Z',sha256=hashlib.sha256(pr[:pos]).hexdigest(),hashed_bytes=pos,previous_prefix_bytes=19979,previous_prefix_sha256=hashlib.sha256(pr[:19979]).hexdigest(),preregistration_final_sha256=sha(H/'PREREGISTRATION_R2_HOLDOUT.md'),before_scoring=True))
 # Prepare only development tensors. No HOLDOUT values are read here.
 b=rt.data();p=PRIVATE/'data/orderfree';p.mkdir(parents=True,exist_ok=True)
 for split in ('train','validation'):
  x=b[split]['X'];target=p/f'{split}_X.npy'
  if not target.exists():
   out=np.lib.format.open_memmap(target,mode='w+',shape=x.shape,dtype=np.float32)
   for i in range(len(x)):
    out[i]=x[i,np.random.default_rng(np.random.SeedSequence([42,i])).permutation(20)]
   out.flush();del out
  np.save(p/f'{split}_y.npy',b[split]['y']);np.save(p/f'{split}_X40.npy',b[split]['X40'])
  status('ORDERFREE_DEVELOPMENT_READY',split=split,windows=len(x))
 # Verify the completed Phase 6 development-only T1 campaign before reusing it.
 f6=read(R2/'phase6/TRAINING_COMPLETE.json');data6=read(R2/'phase6/DATA_MANIFEST_PHASE6.json');assert data6['r52_test_read']==False and data6['holdout_data_read']==False
 reuse=[]
 for t in (10,30):
  base=R2/f'phase6/private/data/r52_T{t}_F13';manifest=read(base/'manifest.json');assert manifest['length']==t and manifest['features']==FEATURES
  assert sha(base/'scaler.json')==manifest['scaler_sha256'];sc=read(base/'scaler.json');assert sc['fit_partition']=='TRAIN' and sc['fit_daily_rows']==1500*413
  for split in ('train','validation'):
   z=np.load(base/f'{split}_metadata.npz');users=set(z['user'].astype(str));assert users==set(devusers()) and not users&excluded()
  for m in ('TA2','XGBoost_40'):
   for s in SEEDS:
    r=read(R2/f'phase6/private/training/r52_T{t}_F13/results/{m}_{s}.json');assert r['status']=='ok' and sha(r['checkpoint'])==r['sha256']==f6['checkpoint_hashes'][r['checkpoint']]
    assert r['config']['development_only'] and r['config']['excluded_holdout'] and r['config']['training_partition']=='TRAIN' and r['config']['selection_partition']=='VALIDATION'
    if m=='TA2':assert r['config']['lambda_teacher']==.5 and r['config']['lambda_route']==.5
    reuse.append(r|dict(source_model=m,model=('TRACE' if m=='TA2' else 'XGBoost-40')+f'-{t}',length=t,reused_from_phase6=True))
 dump(OUT/'H5_REUSED_TRAINING.json',reuse)
 dump(OUT/'PREPARATION_COMPLETE.json',dict(utc=utc(),development_only=True,holdout_data_read=False,r52_test_read=False,orderfree_rng='SeedSequence([42,original_split_row_index])',H5_checkpoints_verified=len(reuse),H5_development_manifest_sha256=sha(R2/'phase6/DATA_MANIFEST_PHASE6.json')))
if __name__=='__main__':main()
