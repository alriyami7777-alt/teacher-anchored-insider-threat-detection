from common11 import *
import psutil
SCRIPTS={os.path.normcase(str(CODE/name)) for name in ('prepare11.py','train11.py','infer11.py','stats11.py','contrasts11.py','audit11.py','numerical11.py')}
def main():
 events=[];seen=set()
 while time.time()<DEADLINE+30:
  now=time.time()
  for proc in psutil.process_iter(['pid','cmdline','create_time']):
   try:
    args=proc.info['cmdline'] or [];match=[x for x in args if os.path.normcase(x) in SCRIPTS]
    if not match:continue
    elapsed=now-proc.info['create_time'];reason='NOT RUN (time): 08:00 safety stop' if now>=DEADLINE else 'TIMEOUT: 90 minutes' if elapsed>=RUN_LIMIT else None
    if reason and proc.pid not in seen:
     seen.add(proc.pid)
     for child in reversed(proc.children(recursive=True)):
      if any(os.path.normcase(x) in SCRIPTS for x in child.cmdline()):child.kill()
     proc.kill();events.append(dict(utc=utc(),pid=proc.pid,script=match[0],args=args,elapsed_seconds=elapsed,reason=reason));dump(OUT/'CUTOFF_EVENTS.json',events)
   except (psutil.NoSuchProcess,psutil.AccessDenied):continue
  if (OUT/'COMPUTATION_FINISHED.json').exists() and (OUT/'ANALYSIS_FINISHED.json').exists():break
  time.sleep(.5)
 dump(OUT/'CUTOFF_MONITOR_FINISHED.json',dict(utc=utc(),events=len(events)));print('CUTOFF_MONITOR_FINISHED',len(events),flush=True)
if __name__=='__main__':main()
