from common10 import *
from report10 import main as report
def main():
 previous=None
 while time.time()<DEADLINE:
  signature=(len(list((P/'metrics').glob('*.json'))),len(list((P/'training').glob('*/results/*.json'))),len(list((P/'complete').glob('*.json'))))
  if signature!=previous:
   if signature[0]:child('contrasts10.py',[],f'contrasts_report_{int(time.time())}')
   report(False);previous=signature
  if (OUT/'COMPUTATION_FINISHED.json').exists() and (OUT/'ANALYSIS_FINISHED.json').exists():break
  time.sleep(min(30,max(0,DEADLINE-time.time())))
 report(True);dump(OUT/'REPORT_FINISHED.json',dict(utc=utc(),all_scientific_children_finished_or_deadline=True));print('REPORT_FINISHED',flush=True)
if __name__=='__main__':main()
