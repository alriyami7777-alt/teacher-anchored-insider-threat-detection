from common8 import *
import subprocess
def run(script,timeout=7200):
 status('PIPELINE_STAGE',script=script);log=PRIVATE/f'logs/pipeline_{script}.log'
 with log.open('w',encoding='utf-8') as h:
  p=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/script)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  try:rc=p.wait(timeout=timeout)
  except subprocess.TimeoutExpired:p.kill();p.wait();rc='TIMEOUT'
 r=dict(script=script,utc=utc(),exit=rc,status='ok' if rc==0 else 'TIMEOUT' if rc=='TIMEOUT' else 'FAILED',log=str(log));return r
def main():
 gate();status('PIPELINE_WAITING_FOR_Q1_TRAINING')
 while not (OUT/'Q1_TRAINING_COMPLETE.json').exists():time.sleep(5)
 stages=[]
 for script,timeout in [('score8.py',None),('q1_analysis8.py',7200),('gradient8.py',None),('q3_routes8.py',7200),('randomization8.py',None),('shift8.py',None)]:
  stages.append(run(script,timeout));dump(OUT/'PIPELINE_OUTCOMES.json',stages)
 status('ANALYSES_FINISHED_REPORT_PENDING',stages=stages)
if __name__=='__main__':main()
