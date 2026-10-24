from common9 import *
from stats9 import *
def validation(n,s,dv):
 p=PRIVATE/f'validation/{n}_{s}.npy';p.parent.mkdir(exist_ok=True)
 if p.exists():return np.load(p)
 x=np.load(HP/'tensors/validation_X.npy',mmap_mode='r');m=loadmodel(oldspec(n,s),dv);out=[]
 for lo in range(0,len(x),512):out.append(predict(m,n,np.array(x[lo:lo+512]),dv));time.sleep(.002)
 a=np.concatenate(out);np.save(p,a);return a
def main():
 gate();dv=device();y=np.load(HP/'tensors/validation_y.npy');frozen=[]
 for n in ('TA2','F00','XGBoost_40'):
  vals=[validation(n,s,dv) for s in ALL]
  for label,ss in (('three',SEEDS),('eight',ALL)):
   a=np.mean(vals[:len(ss)],0);t=rt.threshold(y,a);frozen.append(dict(model=n,group=label,seeds=list(ss),threshold=t,validation_score_sha256=hashlib.sha256(a.tobytes()).hexdigest(),population='clean development VALIDATION only'))
 dump(OUT/'L5_THRESHOLDS_FROZEN.json',dict(utc=utc(),thresholds=frozen,validation_labels_sha256=sha(HP/'tensors/validation_y.npy')));co=Cohort('r5.2_HOLDOUT',True);points=[];rows=[]
 for f in frozen:
  n=f['model'];ss=f['seeds'];probs=[original(n,s) for s in ss];a=np.mean(probs,0);p,b=cachedmetrics(f"ensemble_{n}_{f['group']}",co,a,f['threshold']);component=[cachedmetrics(f'zero_r5.2_HOLDOUT_{n}_{s}',co,v,oldspec(n,s)['threshold']) for s,v in zip(ss,probs)];points.append(f|p)
  for k in ('PR_AUC','insiders_detected','noninsiders_flagged'):
   est=p[k]-np.mean([z[0][k] for z in component]);rep=b[k]-np.mean([z[1][k] for z in component],0);rows.append(dict(model=n,group=f['group'],metric=k,contrast='averaged scores minus mean single-seed metrics',single_seed_mean=float(np.mean([z[0][k] for z in component])),**interval(rep,est)))
 holm(rows,'L5',18);csv('L5_ENSEMBLE_METRICS.csv',points);csv('L5_CONTRASTS.csv',rows);dump(OUT/'L5_RESULTS.json',dict(utc=utc(),points=points,contrasts=rows,thresholds=frozen,Holm_family_size=18,no_new_target_forward=True))
if __name__=='__main__':main()
