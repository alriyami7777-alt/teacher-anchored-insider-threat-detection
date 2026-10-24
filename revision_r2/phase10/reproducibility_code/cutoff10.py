from common10 import *
import psutil
# Independent safeguard: Windows venv python.exe can launch a base interpreter;
# stopping only its launcher would not stop the actual scientific computation.
SCRIPTS={os.path.normcase(str(CODE/n)) for n in ('prepare10.py','train10.py','infer10.py','stats10.py','contrasts10.py','numerical_audit10.py')}
def main():
 events=[];seen=set();end=DEADLINE+30
 while time.time()<end:
  current=time.time()
  for proc in psutil.process_iter(['pid','cmdline','create_time']):
   try:
    args=proc.info['cmdline'] or [];matches=[a for a in args if os.path.normcase(a) in SCRIPTS]
    if not matches:continue
    elapsed=current-proc.info['create_time'];reason='NOT RUN (time): hard stop 18:30 +08' if current>=DEADLINE else 'TIMEOUT: 45-minute per-run limit' if elapsed>=2700 else None
    if reason:
     pid=proc.pid
     if pid in seen:continue
     seen.add(pid);children=proc.children(recursive=True)
     for child in reversed(children):
      ca=child.cmdline()
      if any(os.path.normcase(a) in SCRIPTS for a in ca):child.kill()
     proc.kill();events.append(dict(utc=utc(),pid=pid,script=matches[0],args=args,elapsed_seconds=elapsed,reason=reason,owned_phase10_exact_script_match=True));dump(OUT/'CUTOFF_TERMINATIONS.json',events)
   except (psutil.NoSuchProcess,psutil.AccessDenied):continue
  if (OUT/'COMPUTATION_FINISHED.json').exists() and (OUT/'ANALYSIS_FINISHED.json').exists():break
  time.sleep(.5)
 dump(OUT/'CUTOFF_MONITOR_FINISHED.json',dict(utc=utc(),events=len(events),scoped_to_exact_Phase10_scripts=True));print('CUTOFF_MONITOR_FINISHED',len(events),flush=True)
if __name__=='__main__':main()
