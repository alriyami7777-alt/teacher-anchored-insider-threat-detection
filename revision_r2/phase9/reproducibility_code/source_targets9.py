from common9 import *
def main():
 import pyarrow.dataset as ds,pyarrow.compute as pc
 gate();assert (OUT/'AMENDMENT9_CLARIFICATION_RECEIPT.json').exists();users=(HP/'HOLDOUT_USERS.txt').read_text().splitlines();o=operational();rawusers=[users[i] for i in np.flatnonzero(o['insider'])];base=Path(r'C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\event_level');mat=np.zeros((500,5),int);receipts=[]
 for j,name in enumerate(('logon','device','file','email','http')):
  source=base/f'{name}_labelled.parquet';dataset=ds.dataset(source);date=ds.field('date');year=pc.utf8_slice_codeunits(date,6,10);md=pc.utf8_slice_codeunits(date,0,5);period=((year=='2010')&(md>='01/02'))|((year=='2011')&(md<='04/10'));filt=ds.field('user').isin(rawusers)&(ds.field('is_malicious')==1)&period;df=dataset.to_table(columns=['user','date','is_malicious'],filter=filt).to_pandas();dt=pd.to_datetime(df.date,format='%m/%d/%Y %H:%M:%S');assert ((dt>=pd.Timestamp('2010-01-02'))&(dt<pd.Timestamp('2011-04-11'))).all()
  counts0=df.groupby('user').size()
  for i,u in enumerate(users):mat[i,j]=int(counts0.get(u,0))
  receipts.append(dict(source=name,path=str(source),rows=len(df),columns=['user','date','is_malicious'],date_filter='2010-01-02 through2011-04-10 before materialisation',raw_payload_read=False));print('SOURCE_COUNTS_READY',name,len(df),flush=True)
 assert (mat.sum(1)[o['insider']]>0).all();target=np.argmax(mat,1);rows=[dict(user=o['user'][i],source=['logon','device','file','email','http'][target[i]],malicious_event_counts=mat[i].tolist(),malicious_events=int(mat[i].sum())) for i in np.flatnonzero(o['insider'])];dump(OUT/'L7_MALICIOUS_SOURCE_TARGETS_FROZEN.json',dict(utc=utc(),rows=rows,source_index_by_holdout_cluster=target,receipts=receipts,r52_test_read=False,raw_payload_read=False));csv('L7_MALICIOUS_SOURCE_TARGETS.csv',rows)
if __name__=='__main__':main()
