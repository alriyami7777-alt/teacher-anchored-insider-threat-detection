from common10 import *
def main(s):
 gate();co=cohort(development=True);nt=read(OUT/'R62_SPLIT_RECEIPT.json')['n_train_days'];m=co['start']>=nt;records=[]
 for n in MODELS:
  p=cached(n,s,co)[m];y=co['y'][m];assert y.sum()>0;t=rt.threshold(y,p);records.append(dict(model=n,seed=s,old_threshold=oldspec(n,s)['threshold'],threshold=t,validation_windows=len(y),validation_positives=int(y.sum()),checkpoint_sha256=oldspec(n,s)['sha256']))
 dump(OUT/f'P1_THRESHOLDS_{s}.json',dict(utc=utc(),development_validation_only=True,records=records));print('P1_THRESHOLDS_FROZEN',s,flush=True)
if __name__=='__main__':main(int(sys.argv[1]))
