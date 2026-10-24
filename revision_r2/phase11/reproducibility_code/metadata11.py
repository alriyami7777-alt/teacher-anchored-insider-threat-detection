from common11 import *
def ensure_metadata():
 path=P/'COHORT_METADATA.npz'
 if not path.exists():
  gate();co=cohort();daily=np.load(B/'malicious_day_labels.npy',mmap_mode='r');u=co['global_u'];st=co['start'];y=np.empty(len(u),np.int8)
  for a in range(0,len(u),8192):
   b=min(a+8192,len(u));y[a:b]=daily[u[a:b,None],st[a:b,None]+np.arange(20)].max(1)
  np.savez_compressed(path,u=u.astype(np.int32),start=st.astype(np.int16),end=co['end'].astype(np.int16),y=y,users=co['users'],official=np.load(P/'OFFICIAL.npy'),affected=np.load(P/'AFFECTED.npy'),pseudonyms=np.load(P/'PSEUDONYMS.npy'),fold=np.load(P/'FOLD_ASSIGNMENT.npy'),scenarios=np.load(B/'official_incident_codes.npy'),dates=np.load(B/'calendar_dates.npy'))
  codes=np.load(B/'official_incident_codes.npy');official=np.load(P/'OFFICIAL.npy');bits=np.load(B/'answer_scenario_day_bitmask.npy',mmap_mode='r')
  for i in np.flatnonzero(official):
   scenario=int(str(codes[i]).rsplit('-',1)[1]);assert np.all((bits[i,daily[i]>0]&(1<<(scenario-1)))!=0)
  dump(OUT/'COHORT_METADATA_RECEIPT.json',dict(utc=utc(),sha256=sha(path),users=4000,official=int(official.sum()),affected=int(np.load(P/'AFFECTED.npy').sum()),windows=len(y),positive_windows=int(y.sum()),first_window_endpoint=str(np.load(B/'calendar_dates.npy')[19]),metadata_only=True))
 return dict(np.load(path))
if __name__=='__main__':ensure_metadata()
