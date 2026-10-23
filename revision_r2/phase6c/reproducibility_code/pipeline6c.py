from common6c import *
import subprocess
def stage(name,limit=7200):
 status('PIPELINE_STAGE',script=name)
 with (PRIVATE/'logs'/f'pipeline_{name}.log').open('w',encoding='utf-8') as h:
  p=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/name)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  try:rc=p.wait(timeout=limit)
  except subprocess.TimeoutExpired:p.kill();p.wait();rc='TIMEOUT'
 if rc!=0:status('PIPELINE_NEEDS_REPAIR',script=name,exitcode=rc);raise SystemExit(1)
def main():
 while not (OUT/'TRAINING_COMPLETE.json').exists():time.sleep(10)
 stage('score6c.py',43200);stage('c2_analysis.py')
 status('WAITING_FOR_C1')
 while not (OUT/'C1_COMPLETE.json').exists():time.sleep(10)
 stage('report6c.py');stage('verify6c.py')
if __name__=='__main__':main()
