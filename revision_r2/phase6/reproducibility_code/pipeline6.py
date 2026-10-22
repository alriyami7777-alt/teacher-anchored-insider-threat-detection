from common6 import *
import subprocess
PYTHON=ROOT/'phase4/.venv/Scripts/python.exe'
def main():
 while not (OUT/'TRAINING_COMPLETE.json').exists():time.sleep(20)
 for name in ('inference6.py','training_analysis6.py','report6.py','verify6.py'):
  status('POSTTRAIN_STAGE',script=name)
  with (PRIVATE/'logs'/name.replace('.py','.log')).open('w',encoding='utf-8') as f:
   proc=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/name)],stdout=f,stderr=subprocess.STDOUT,env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'),creationflags=subprocess.CREATE_NO_WINDOW)
   try:rc=proc.wait(timeout=7200)
   except subprocess.TimeoutExpired:proc.kill();proc.wait();rc='TIMEOUT'
  if rc!=0:dump(OUT/'PIPELINE_FAILURE.json',dict(utc=utc(),script=name,exit=rc));raise RuntimeError(f'{name} failed, inspect private log')
 print('PHASE6_COMPLETE',flush=True)
if __name__=='__main__':main()
