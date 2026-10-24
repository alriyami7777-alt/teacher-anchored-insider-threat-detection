from common10 import *
def main():
 (P/'outcomes').mkdir(exist_ok=True);cycles=max([int(p.stem.rsplit('_',1)[1]) for p in (P/'logs').glob('metrics_scan_*.log')]+[0])
 while time.time()<DEADLINE:
  cycles+=1;r=child('stats10.py',[],f'metrics_scan_{cycles}')
  if r['status']!='ok':break
  if (OUT/'COMPUTATION_FINISHED.json').exists():break
  time.sleep(min(30,max(0,DEADLINE-time.time())))
 dump(OUT/'ANALYSIS_FINISHED.json',dict(utc=utc(),scans=cycles,hard_deadline_respected=True));print('ANALYSIS_FINISHED',flush=True)
if __name__=='__main__':main()
