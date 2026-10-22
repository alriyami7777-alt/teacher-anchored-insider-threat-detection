from common6b import *
import subprocess
def main():
 # Wait only for this campaign's training worker; do not inspect/control unrelated jobs.
 while not (OUT/'TRAINING_COMPLETE.json').exists():time.sleep(10)
 stages=('score6b.py','explain6b.py','analysis6b.py','report6b.py','verify6b.py')
 for script in stages:
  status('PIPELINE_STAGE',script=script)
  with (PRIVATE/'logs'/f'pipeline_{script}.log').open('w',encoding='utf-8') as h:
   proc=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/script)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
   # Scoring/explanation coordinators apply 120 minutes to each own child run.
   if script in ('score6b.py','explain6b.py'):rc=proc.wait()
   else:
    try:rc=proc.wait(timeout=7200)
    except subprocess.TimeoutExpired:proc.kill();proc.wait();rc='TIMEOUT'
  if rc!=0:status('PIPELINE_NEEDS_REPAIR',script=script,exitcode=rc);raise SystemExit(rc)
if __name__=='__main__':main()
