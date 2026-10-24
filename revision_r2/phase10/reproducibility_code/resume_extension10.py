from common10 import *
import psutil
def same(rec):
 try:
  proc=psutil.Process(rec['pid']);return proc if abs(proc.create_time()-rec['created'])<.01 else None
 except psutil.NoSuchProcess:return None
def stop(rec):
 proc=same(rec)
 if proc:
  try:proc.kill()
  except psutil.NoSuchProcess:pass
def main():
 change=read(OUT/'DEADLINE_EXTENSION_CONTROL_CHANGE.json');controls=change['coordinators_suspended'];jobs=change['current_scientific_jobs'];maincontrols=[r for r in controls if r['script'] in ('launch10.py','worker10.py')]
 for rec in controls:
  if rec not in maincontrols:stop(rec)
 dump(OUT/'EXTENSION_NONMAIN_CONTROLLERS_STOPPED.json',dict(utc=utc(),only_exact_owned_recorded_PIDs=True,current_scientific_children_left_running=True))
 # Wait for the existing scientific run(s), not for newly resumed CPU scans.
 wanted={(r['script'],tuple(r['args'])) for r in jobs}
 while True:
  active=[]
  for proc in psutil.process_iter(['cmdline']):
   try:
    args=proc.info['cmdline'] or []
    for i,arg in enumerate(args):
     if os.path.normcase(os.path.dirname(arg))==os.path.normcase(str(CODE)) and (Path(arg).name,tuple(args[i+1:])) in wanted:active.append(proc.pid)
   except (psutil.NoSuchProcess,psutil.AccessDenied):pass
  if not active:break
  time.sleep(1)
 for rec in maincontrols:stop(rec)
 rows=read(OUT/'EXECUTION_LOG.json') if (OUT/'EXECUTION_LOG.json').exists() else []
 recovered=[]
 for job in jobs:
  script=job['script'];args=job['args'];key=None;success=False
  if script=='train10.py':
   c,n,s=args;key=f'train_{c}_{n}_{s}';success=(P/f'training/{c}/results/{n}_{s}.json').exists()
  elif script=='infer10.py':
   c,n,s,release=args;key=f'infer_{c}_{n}_{s}_{release}';success=(P/f'complete/{c}_{n}_{s}_{release}.json').exists()
  elif script=='prepare10.py':
   c=args[0];key=f'prepare_{c}';success=(P/f'data/{c}/manifest.json').exists()
  if key and not any(r['key']==key for r in rows):
   record=dict(utc=utc(),key=key,exit=0 if success else 'CONTROL_RESTART',status='ok' if success else 'INTERRUPTED (control restart)',wall_seconds=time.time()-job['created'],log=str(P/f'logs/{key}.log'),recovered_after_approved_deadline_extension=True,success_confirmed_from_completed_result_or_receipt=success);dump(P/f'outcomes/{key}.json',record);rows.append(record);recovered.append(record)
 dump(OUT/'EXECUTION_LOG.json',rows);dump(OUT/'DEADLINE_EXTENSION_READY_TO_RESUME.json',dict(utc=utc(),recovered_jobs=recovered,old_coordinators_stopped=True,scientific_children_finished_without_interruption=True,new_deadline_local='2026-10-23T18:30:00+08:00'));print('READY_TO_RESUME_WITH_1830_DEADLINE',flush=True)
if __name__=='__main__':main()
