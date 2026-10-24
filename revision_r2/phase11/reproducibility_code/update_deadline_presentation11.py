from pathlib import Path
import ast
code=Path(__file__).resolve().parent
def replace(text,old,new):
 assert text.count(old)==1,(old,text.count(old))
 return text.replace(old,new)

p=code/'report11.py';text=p.read_text()
text=replace(text,"safety_stop_local='2026-10-24T08:00:00+08:00'","safety_stop_local=None")
text=replace(text,'The overnight update supersedes22:40: safety stop **08:00 (+08), 24 October2026**,90-minute run timeout.','The24October2026 05:53 (+08) update removes the overall time limit: every condition and seed42/52/62 is to finish. Each individual run retains a90-minute timeout.')
text=replace(text,'Only exact owned Phase11 processes are subject to the90-minute timeout/08:00 stop.','Only exact owned Phase11 processes are subject to the90-minute per-run timeout. There is no overall deadline.')
text=replace(text,'the safety clock is checked on every guard call and the independent90-minute/08:00 monitor is unchanged.','the clock was checked on every guard call under the schedule then in force. The later authorised schedule update removes the overall stop while preserving the independent90-minute timeout.')
needle=" computational_outcomes=[read(p) for p in sorted((P/'outcomes').glob('*.json'))]"
addition=""" if (OUT/'NO_OVERALL_LIMIT_RECEIPT.json').exists():
  schedule=read(OUT/'NO_OVERALL_LIMIT_RECEIPT.json');result['authorised_schedule_update']=schedule;result['schedule_transition']=read(OUT/'NO_LIMIT_TRANSITION_READY.json');lines += ['## Authorised removal of the overall time limit','',f'Qasim removed the08:00 safety stop at05:53 (+08),24October2026. Every condition and seed proceeds in the original priority order; each run retains its90-minute timeout. The [schedule receipt](NO_OVERALL_LIMIT_RECEIPT.json), prefix SHA-256 `{schedule["sha256"]}`, binds the updated prompt and the exact deadline-only common-code changes. Current scientific children finished naturally and their actual exit codes were adopted once; only exact owned coordinators were refreshed. No training, evaluation or analysis method changed and no held-out condition was rescored. [Transition receipt](NO_LIMIT_TRANSITION_READY.json).','', '````text',(R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md').read_bytes()[schedule['previous_bytes']:schedule['hashed_bytes']].decode('utf8'),'````','']
"""
text=replace(text,needle,addition+needle)
ast.parse(text);p.write_text(text,encoding='utf8')

p=code/'audit11.py';text=p.read_text()
common="(P/'control_history/no_overall_limit/common11.py' if (OUT/'NO_OVERALL_LIMIT_RECEIPT.json').exists() else CODE/'common11.py')"
text=replace(text,"oldcommon[:start]+newgate+oldcommon[end:]==(CODE/'common11.py').read_text()",'oldcommon[:start]+newgate+oldcommon[end:]=='+common+'.read_text()')
text=replace(text,"sha(CODE/'common11.py')==g['new_common_sha256']",'sha('+common+")==g['new_common_sha256']")
needle=" if not interim:checks['every_reported_script_hash_matches_final_source']"
addition=""" if (OUT/'NO_OVERALL_LIMIT_RECEIPT.json').exists():
  schedule=read(OUT/'NO_OVERALL_LIMIT_RECEIPT.json');history=P/'control_history/no_overall_limit';old=(history/'common11.py').read_text();updated=old.replace("DEADLINE=datetime.fromisoformat('2026-10-24T08:00:00+08:00').timestamp()","DEADLINE=float('inf')").replace("'Safety stop 08:00 +08 24Oct2026'","'Phase 11 overall deadline removed by Qasim 24Oct05:53+08'").replace("safety_stop_local='24Oct08:00+08'","safety_stop_local=None");oldtf=read(history/'TRAINING_CODE_FROZEN.json');transition=read(OUT/'NO_LIMIT_TRANSITION_READY.json');checks['authorised_no_overall_limit_changes_only_schedule_preserves_90min']=hashlib.sha256(pr[:schedule['hashed_bytes']]).hexdigest()==schedule['sha256'] and hashlib.sha256(pr[:schedule['previous_bytes']]).hexdigest()==schedule['previous_sha256'] and sha(history/'common11.py')==schedule['old_common_sha256'] and sha(CODE/'common11.py')==schedule['new_common_sha256'] and updated==(CODE/'common11.py').read_text() and all(sha(CODE/name)==value for name,value in oldtf['code'].items() if name!='common11.py') and sha(OUT/'ANALYSIS_CODE_FROZEN.json')==sha(history/'ANALYSIS_CODE_FROZEN.json') and schedule['per_run_limit_seconds']==RUN_LIMIT==5400 and schedule['overall_time_limit'] is None and r['safety_stop_local'] is None and transition['all_current_children_exit_zero'] and transition['no_rescoring'] and sha(R2/'CHATGPT_PHASE11_PROMPT.md')==schedule['prompt_sha256']
"""
text=replace(text,needle,addition+needle)
text=replace(text,"checks['all_target_scoring_before_0800_safety_limit']=all(datetime.fromisoformat(z['utc']).timestamp()<DEADLINE for z in receipts)","checks['target_scoring_follows_authorised_schedule']=all(datetime.fromisoformat(z['utc'])>datetime.fromisoformat(fold['utc']) for z in receipts) and ((OUT/'NO_OVERALL_LIMIT_RECEIPT.json').exists() or all(datetime.fromisoformat(z['utc']).timestamp()<DEADLINE for z in receipts))")
ast.parse(text);p.write_text(text,encoding='utf8')
print('PRESENTATION_AND_SCHEDULE_AUDIT_UPDATED; no scientific changes')
