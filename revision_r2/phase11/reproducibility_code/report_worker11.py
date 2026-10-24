from common11 import *
from report11 import main as report
def main():
 previous=None
 while time.time()<DEADLINE:
  signature=(len(list((P/'training').glob('*/results/*.json'))),len(list((P/'metrics').glob('*.json'))),len(list((P/'complete').glob('*.json'))),len(list((P/'posthoc').glob('*.json'))),len(list((P/'cost').glob('*.json'))))
  if signature!=previous:report(False);previous=signature
  if (OUT/'COMPUTATION_FINISHED.json').exists() and (OUT/'ANALYSIS_FINISHED.json').exists():break
  time.sleep(min(20,max(0,DEADLINE-time.time())))
 report(True);dump(OUT/'REPORT_FINISHED.json',dict(utc=utc()));print('REPORT_FINISHED',flush=True)
if __name__=='__main__':main()
