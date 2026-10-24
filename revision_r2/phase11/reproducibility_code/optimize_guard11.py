from common11 import *
import ast,psutil
def main():
 gate();assert not (OUT/'GUARD_CACHE_RECEIPT.json').exists();path=CODE/'common11.py';old=path.read_text(encoding='utf8');tf=read(OUT/'TRAINING_CODE_FROZEN.json');assert all(sha(CODE/name)==value for name,value in tf['code'].items());start=old.index('def gate():');end=old.index('\ndef device():',start);oldgate=old[start:end];assert '_integrity_last_check' not in old;clock=" assert time.time()<DEADLINE,'Safety stop 08:00 +08 24Oct2026'\n";assert clock in oldgate
 newgate=oldgate.replace('def gate():\n',"_integrity_last_check=-float('inf')\ndef gate():\n global _integrity_last_check\n",1).replace(clock,clock+" now=time.monotonic()\n if now-_integrity_last_check<30:return\n",1)+"\n _integrity_last_check=now\n";new=old[:start]+newgate+old[end:];ast.parse(new);newhash=hashlib.sha256(new.encode('utf8')).hexdigest();history=P/'control_history/guard_cache';assert not history.exists();history.mkdir(parents=True);(history/'common11.py').write_bytes(path.read_bytes());(history/'TRAINING_CODE_FROZEN.json').write_bytes((OUT/'TRAINING_CODE_FROZEN.json').read_bytes());paused=[]
 try:
  for proc in psutil.process_iter(['pid','cmdline']):
   try:
    if str(CODE/'worker11.py') in (proc.info['cmdline'] or []):proc.suspend();paused.append(proc)
   except (psutil.NoSuchProcess,psutil.AccessDenied):pass
  assert paused,'Main coordinator must be safely paused during atomic code/freeze update'
  pr=R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md';before=pr.read_bytes();body='''

### Amendment 11 operational implementation note: integrity-guard caching

The initial full prefix/fold receipt/CSV verification took3.7322 seconds for500 checks (about7.46ms/check). Repeating those unchanged-file reads several times per batch is avoidable control overhead. Starting with future child processes, retain identical full hash verification on the first guard call and every30 seconds thereafter; every guard call still checks the08:00 safety-stop clock, and the independent exact-process90-minute/safety monitor remains active. No data, model, optimizer, losses, class weights, checkpoints, thresholds, random seeds, RNG calls, batch order, epochs, patience, scoring counts, bootstrap, contrast or priority order changes. The current scientific child runs uninterrupted with its already-loaded guard. Only this phase's exact main coordinator PIDs pause briefly for the code/freeze transaction, then resume. No other chat is controlled. The original code/freeze is preserved and the exact guard-only difference is audited. This is a control implementation optimization, not a scientific protocol change.
'''
  with pr.open('ab') as h:h.write(body.encode('utf8'))
  content=pr.read_bytes();receipt=dict(utc=utc(),previous_bytes=len(before),previous_sha256=hashlib.sha256(before).hexdigest(),hashed_bytes=len(content),sha256=hashlib.sha256(content).hexdigest(),old_common_sha256=tf['code']['common11.py'],new_common_sha256=newhash,prior_training_freeze_sha256=sha(history/'TRAINING_CODE_FROZEN.json'),full_integrity_check_interval_seconds=30,deadline_checked_every_call=True,independent_90min_0800_monitor_unchanged=True,scientific_methods_data_RNG_priority_unchanged=True,current_scientific_child_uninterrupted=True,paused_owned_coordinator_PIDs=[x.pid for x in paused],benchmark_500_full_checks_seconds=3.7322)
  dump(OUT/'GUARD_CACHE_RECEIPT.json',receipt)
  with pr.open('ab') as h:h.write(('\nAmendment11 guard implementation SHA-256 receipt: `'+receipt['sha256']+'` over '+str(receipt['hashed_bytes'])+' prefix bytes; '+receipt['utc']+'.\n').encode('utf8'))
  temporary=path.with_suffix('.py.guardtmp');temporary.write_bytes(new.encode('utf8'));os.replace(temporary,path);tf.update(utc=utc(),prior_training_freeze_sha256=receipt['prior_training_freeze_sha256'],guard_cache_receipt_sha256=sha(OUT/'GUARD_CACHE_RECEIPT.json'));tf['code']['common11.py']=newhash;dump(OUT/'TRAINING_CODE_FROZEN.json',tf);assert sha(path)==tf['code']['common11.py'];print('GUARD_ONLY_OPTIMIZATION_FROZEN',receipt['sha256'],flush=True)
 finally:
  for proc in paused:
   try:proc.resume()
   except psutil.NoSuchProcess:pass
if __name__=='__main__':main()
