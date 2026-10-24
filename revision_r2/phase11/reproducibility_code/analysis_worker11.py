from common11 import *
def main():
 cycles=max([int(p.stem.rsplit('_',1)[1]) for p in (P/'logs').glob('metrics_scan_*.log') if p.stem.rsplit('_',1)[1].isdigit()]+[0]);last=None
 while time.time()<DEADLINE:
  signature=len(list((P/'complete').glob('*.json')))
  if signature!=last:
   cycles+=1;result=child('stats11.py',[],f'metrics_scan_{cycles}');last=signature
   if result['status']!='ok':dump(OUT/'ANALYSIS_ERROR.json',result);break
   child('contrasts11.py',[],f'contrasts_scan_{cycles}')
  if (OUT/'COMPUTATION_FINISHED.json').exists():
   # A fresh final scan after the main writer ends avoids a last-receipt race.
   cycles+=1;result=child('stats11.py',[],f'metrics_scan_{cycles}_final');child('contrasts11.py',[],f'contrasts_scan_{cycles}_final');break
  time.sleep(min(30,max(0,DEADLINE-time.time())))
 dump(OUT/'ANALYSIS_FINISHED.json',dict(utc=utc(),scans=cycles));print('ANALYSIS_FINISHED',flush=True)
if __name__=='__main__':main()
