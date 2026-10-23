from common8 import *
import subprocess
def run(name):
 with (PRIVATE/f'logs/finalize_{name}.log').open('w',encoding='utf-8') as h:
  p=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/name)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  try:rc=p.wait(timeout=7200)
  except subprocess.TimeoutExpired:p.kill();p.wait();rc='TIMEOUT'
 return rc
def main():
 while True:
  p=OUT/'PIPELINE_OUTCOMES.json'
  if p.exists() and len(read(p))==6:break
  time.sleep(5)
 for script in ('figures8.py','report8.py'):
  rc=run(script)
  if rc!=0:status('FINALIZATION_FAILED',script=script,exit=rc);return
 status('AWAITING_VISUAL_QA')
 while not (OUT/'VISUAL_QA_RECEIPT.json').exists():time.sleep(5)
 rc=run('verify8.py');status('FINALIZATION_FINISHED',audit_exit=rc)
if __name__=='__main__':main()
