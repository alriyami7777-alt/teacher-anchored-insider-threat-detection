from common10 import *
import psutil,shutil
def main():
 receipt_path=OUT/'DEADLINE_EXTENSION_RECEIPT.json';assert not receipt_path.exists()
 controls={'launch10.py','worker10.py','analysis_worker10.py','report_worker10.py','cutoff10.py','finalize10.py'};scientific={'prepare10.py','train10.py','infer10.py','stats10.py','contrasts10.py','numerical_audit10.py'};inventory=[];coordinators=[];jobs={}
 for proc in psutil.process_iter(['pid','cmdline','exe','create_time','ppid']):
  try:
   args=proc.info['cmdline'] or [];ix=next((i for i,a in enumerate(args) if os.path.normcase(os.path.dirname(a))==os.path.normcase(str(CODE)) and Path(a).suffix=='.py'),None)
   if ix is None:continue
   name=Path(args[ix]).name;rec=dict(pid=proc.pid,script=name,args=args[ix+1:],created=proc.info['create_time'],exe=proc.info['exe']);inventory.append(rec)
   if name in controls:
    # Suspend the actual interpreter, retaining the launcher/job handle so its
    # active scientific child can finish undisturbed.
    if os.path.normcase(proc.info['exe'] or '')!=os.path.normcase(str(PY)):proc.suspend()
    coordinators.append(rec)
   elif name in scientific:jobs[(name,tuple(rec['args']))]=rec
  except (psutil.NoSuchProcess,psutil.AccessDenied):continue
 history=P/'control_history/deadline_extension';history.mkdir(parents=True,exist_ok=True)
 dump(history/'PROCESS_SNAPSHOT.json',dict(utc=utc(),coordinators=coordinators,active_scientific_jobs=list(jobs.values()),scientific_children_not_stopped=True))
 pr=R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md';old=pr.read_bytes();text='''\n### Amendment 10 operational deadline extension (Qasim, 23 October 2026 16:49 +08)\n\nThe user relayed Qasim's approval to extend the Phase10 hard computation stop from 17:45 to 18:30 (+08) on 23 October 2026. Keep the same priority order: finish pooled training at seed42, then add seeds52 and62 where possible. The 45-minute individual-run limit, all model recipes, split/users/periods, sample fractions, class weights, checkpoint/threshold rules, metrics, bootstrap/Holm families, once-only evaluation, r5.2 TEST seal, pseudonyms and GPU-sharing limits are unchanged. At18:30 stop computation, retain finished work, mark unfinished NOT RUN (time) and end PHASE10_COMPLETE or PHASE10_PARTIAL.\n\nImplementation controls only: preserve prior clock/code-freeze ledgers; update the clock constant and deadline text; resume coordinator execution logs and cached P1 thresholds without repeating them; retain a single contrast writer. Suspend only this task's coordinators while their current scientific children finish, then restart them with the new clock. Do not interrupt or repeat a held-out prediction pass. No training loss, optimizer, data, model, selection or statistical method is changed.\n'''
 with pr.open('a',encoding='utf8',newline='\n') as h:h.write(text)
 prefix=pr.read_bytes();receipt=dict(utc=utc(),approved_local='2026-10-23T16:49:00+08:00',previous_deadline_local='2026-10-23T17:45:00+08:00',deadline_local='2026-10-23T18:30:00+08:00',previous_bytes=len(old),previous_sha256=hashlib.sha256(old).hexdigest(),hashed_bytes=len(prefix),sha256=hashlib.sha256(prefix).hexdigest(),scientific_methods_unchanged=True)
 with pr.open('a',encoding='utf8',newline='\n') as h:h.write('\nDeadline-extension SHA-256 receipt:\n```json\n'+json.dumps(receipt,indent=2)+'\n```\n')
 dump(receipt_path,receipt)
 changed=('common10.py','worker10.py','analysis_worker10.py','cutoff10.py','report10.py')
 for name in changed:shutil.copy2(CODE/name,history/name)
 for name in ('TRAINING_CODE_FROZEN.json','ANALYSIS_CODE_FROZEN.json'):
  shutil.copy2(OUT/name,history/name);shutil.copy2(OUT/name,OUT/(Path(name).stem+'_BEFORE_DEADLINE_EXTENSION.json'))
 if (OUT/'EXECUTION_LOG.json').exists():shutil.copy2(OUT/'EXECUTION_LOG.json',history/'EXECUTION_LOG.json')
 for name in ('common10.py','cutoff10.py','report10.py'):
  path=CODE/name;src=path.read_text(encoding='utf8');src=src.replace('17:45','18:30');path.write_text(src,encoding='utf8')
 path=CODE/'worker10.py';src=path.read_text();assert ' rows=[]\n' in src;src=src.replace(' rows=[]\n'," rows=read(OUT/'EXECUTION_LOG.json') if (OUT/'EXECUTION_LOG.json').exists() else []\n",1);src=src.replace("    run('p1_10.py',[s],f'p1_{s}')","    if not (OUT/f'P1_THRESHOLDS_{s}.json').exists():run('p1_10.py',[s],f'p1_{s}')");path.write_text(src,encoding='utf8')
 path=CODE/'analysis_worker10.py';src=path.read_text();src=src.replace("(P/'outcomes').mkdir(exist_ok=True);cycles=0","(P/'outcomes').mkdir(exist_ok=True);cycles=max([int(p.stem.rsplit('_',1)[1]) for p in (P/'logs').glob('metrics_scan_*.log')]+[0])");src=src.replace("  r=child('contrasts10.py',[],f'contrasts_{cycles}')\n  if r['status']!='ok':break\n",'');path.write_text(src,encoding='utf8')
 for name in ('TRAINING_CODE_FROZEN.json','ANALYSIS_CODE_FROZEN.json'):
  frozen=read(OUT/name);frozen['utc_operational_deadline_extension']=utc();frozen['prior_freeze_sha256']=sha(history/name);frozen['deadline_extension_receipt_sha256']=sha(receipt_path);frozen['code']={n:sha(CODE/n) for n in frozen['code']};dump(OUT/name,frozen)
 for path in CODE.glob('*.py'):compile(path.read_text(encoding='utf8'),str(path),'exec')
 dump(OUT/'DEADLINE_EXTENSION_CONTROL_CHANGE.json',dict(utc=utc(),history=str(history),before_code={n:sha(history/n) for n in changed},after_code={n:sha(CODE/n) for n in changed},current_scientific_jobs=list(jobs.values()),coordinators_suspended=coordinators,new_deadline_local=receipt['deadline_local'],scientific_children_not_stopped=True,hyperparameters_data_thresholds_statistics_unchanged=True))
 print('DEADLINE_EXTENDED_AND_COORDINATORS_SUSPENDED',json.dumps(list(jobs.values())),flush=True)
if __name__=='__main__':main()
