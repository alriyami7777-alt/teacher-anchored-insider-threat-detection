from common11 import *
import ast,ctypes,psutil
from ctypes import wintypes

def main():
 gate()
 prompt=R2/'CHATGPT_PHASE11_PROMPT.md'
 assert 'No safety limit (Qasim, 24 Oct 05:53 +08)' in prompt.read_text()
 history=P/'control_history/no_overall_limit'
 assert not history.exists()
 history.mkdir(parents=True)
 for name in ('common11.py','report11.py','audit11.py'):
  (history/name).write_bytes((CODE/name).read_bytes())
 for name in ('TRAINING_CODE_FROZEN.json','ANALYSIS_CODE_FROZEN.json','EXECUTION_LOG.json','CHATGPT_PHASE11_REPORT.md','PHASE11_RESULTS.json'):
  (history/name).write_bytes((OUT/name).read_bytes())
 tf=read(OUT/'TRAINING_CODE_FROZEN.json')
 assert all(sha(CODE/name)==value for name,value in tf['code'].items())
 old=(CODE/'common11.py').read_text()
 deadline="DEADLINE=datetime.fromisoformat('2026-10-24T08:00:00+08:00').timestamp()"
 assert old.count(deadline)==1
 new=old.replace(deadline,"DEADLINE=float('inf')").replace("'Safety stop 08:00 +08 24Oct2026'","'Phase 11 overall deadline removed by Qasim 24Oct05:53+08'").replace("safety_stop_local='24Oct08:00+08'","safety_stop_local=None")
 ast.parse(new)
 pr=R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md'
 before=pr.read_bytes()
 body='''

### Amendment 11 authorised schedule update: no overall time limit

Qasim's explicit 24 October 2026 05:53 (+08) update removes the 08:00 safety stop. The updated Phase 11 prompt was reread and states: "No safety limit (Qasim, 24 Oct 05:53 +08): let every condition and seed finish." Run all four conditions for detector seeds 42, 52 and 62 in the existing priority order; every individual run still has a 90-minute TIMEOUT. No scientific design, data, fitting, scaler, label, teacher, checkpoint, threshold, RNG call, batch order, recipe, inference count, statistic or contrast changes. TEST remains sealed; evaluation users remain excluded from fitting and selection; pseudonyms and GPU sharing remain unchanged.

Only this phase's exact coordinator processes will be replaced so their in-memory deadline is refreshed. Any current scientific training/inference/analysis children finish naturally, without interruption or rerun, before fresh coordinators resume from existing model and single-use scoring receipts. The independent 90-minute monitor is replaced with the same implementation using an infinite overall deadline. Preserve old code/freezes, current child exit codes, execution records, and exact process ownership. No other chat is controlled. The only common-code changes are the overall deadline, its message and the status display. Hash this note before those changes.
'''
 with pr.open('ab') as h:h.write(body.encode('utf8'))
 content=pr.read_bytes()
 receipt=dict(utc=utc(),approval_local='2026-10-24T05:53:00+08:00',previous_bytes=len(before),previous_sha256=hashlib.sha256(before).hexdigest(),hashed_bytes=len(content),sha256=hashlib.sha256(content).hexdigest(),prompt_sha256=sha(prompt),old_common_sha256=sha(CODE/'common11.py'),new_common_sha256=hashlib.sha256(new.encode('utf8')).hexdigest(),prior_training_freeze_sha256=sha(history/'TRAINING_CODE_FROZEN.json'),overall_time_limit=None,per_run_limit_seconds=5400,scientific_methods_data_RNG_priority_unchanged=True,no_heldout_rescoring=True,current_scientific_children_uninterrupted=True)
 dump(OUT/'NO_OVERALL_LIMIT_RECEIPT.json',receipt)
 with pr.open('ab') as h:h.write(('\nAmendment11 no-overall-limit SHA-256 receipt: `'+receipt['sha256']+'` over '+str(receipt['hashed_bytes'])+' prefix bytes; '+receipt['utc']+'.\n').encode('utf8'))
 coordinators={str(CODE/name) for name in ('worker11.py','analysis_worker11.py','report_worker11.py','finalize11.py')}
 stopped=[];oldcutoff=[]
 for proc in psutil.process_iter(['pid','cmdline','create_time']):
  try:
   args=proc.info['cmdline'] or []
   if any(x in coordinators for x in args):stopped.append(dict(pid=proc.pid,args=args,created=proc.info['create_time']));proc.suspend()
   elif str(CODE/'cutoff11.py') in args:oldcutoff.append(proc.pid)
  except (psutil.NoSuchProcess,psutil.AccessDenied):pass
 assert len(stopped)>=8,'Expected all four owned coordinator launchers/interpreters'
 science={str(CODE/name) for name in ('prepare11.py','train11.py','infer11.py','stats11.py','contrasts11.py')}
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
 kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
 kernel.CloseHandle.argtypes=[wintypes.HANDLE]
 active=[]
 for path in (P/'active').glob('*.json'):
  z=read(path)
  try:
   proc=psutil.Process(z['pid']);args=proc.cmdline()
   if str(CODE/z['script']) not in args or not any(x in science for x in args):continue
   handle=kernel.OpenProcess(0x100000|0x1000,False,z['pid']);assert handle
   active.append((z,handle))
  except psutil.NoSuchProcess:pass
 for z in reversed(stopped):
  try:psutil.Process(z['pid']).kill()
  except psutil.NoSuchProcess:pass
 temporary=CODE/'common11.py.nolimittmp';temporary.write_bytes(new.encode('utf8'));os.replace(temporary,CODE/'common11.py')
 tf.update(utc=utc(),prior_no_limit_freeze_sha256=receipt['prior_training_freeze_sha256'],no_overall_limit_receipt_sha256=sha(OUT/'NO_OVERALL_LIMIT_RECEIPT.json'));tf['code']['common11.py']=receipt['new_common_sha256'];dump(OUT/'TRAINING_CODE_FROZEN.json',tf)
 assert all(sha(CODE/name)==value for name,value in tf['code'].items())
 dump(OUT/'NO_LIMIT_COORDINATOR_TRANSITION.json',dict(utc=utc(),stopped_owned_coordinators=stopped,old_cutoff_pids=oldcutoff,active_children=[z for z,h in active],scientific_children_not_killed=True))
 print('DEADLINE_REMOVED_AND_FROZEN; waiting for existing scientific children',flush=True)
 adopted=[]
 for z,handle in active:
  code=wintypes.DWORD(259)
  while True:
   assert kernel.GetExitCodeProcess(handle,ctypes.byref(code))
   if code.value!=259:break
   print('WAIT_UNINTERRUPTED',z['key'],utc(),flush=True);time.sleep(30)
  kernel.CloseHandle(handle)
  outcome=P/f'outcomes/{z["key"]}.json'
  if not outcome.exists():
   r=dict(utc=utc(),key=z['key'],exit=int(code.value),status='ok' if code.value==0 else str(code.value),wall_seconds=time.time()-datetime.fromisoformat(z['started_utc']).timestamp(),log=str(P/f'logs/{z["key"]}.log'),adopted_after_authorised_schedule_update=True)
   dump(outcome,r)
   if z['script'] in ('prepare11.py','train11.py','infer11.py'):
    rows=read(OUT/'EXECUTION_LOG.json');assert not any(x['key']==z['key'] for x in rows);rows.append(r);dump(OUT/'EXECUTION_LOG.json',rows)
   adopted.append(r)
  assert code.value==0,('Current scientific child failed independently',z,code.value)
 for pid in oldcutoff:
  try:
   proc=psutil.Process(pid)
   if str(CODE/'cutoff11.py') in proc.cmdline():proc.kill()
  except psutil.NoSuchProcess:pass
 assert not (OUT/'COMPUTATION_FINISHED.json').exists() and not (OUT/'ANALYSIS_FINISHED.json').exists() and not (OUT/'REPORT_FINISHED.json').exists()
 dump(OUT/'NO_LIMIT_TRANSITION_READY.json',dict(utc=utc(),adopted_current_children=adopted,stopped_old_cutoff_pids=oldcutoff,all_current_children_exit_zero=True,no_rescoring=True))
 print('NO_LIMIT_TRANSITION_READY',flush=True)

if __name__=='__main__':main()
