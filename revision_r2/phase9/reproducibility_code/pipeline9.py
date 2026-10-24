from common9 import *
from stats9 import holm
def run_infer(mode,r,n,s,c=None):
 key=f'{mode}_{r}_{n}_{s}'+(f'_{c}' if c else '');done=PRIVATE/f'complete/{key}.json'
 if done.exists():return dict(key=key,status='ok',reused_completed_receipt=True)
 if (PRIVATE/f'consumed/{key}.json').exists():return dict(key=key,status='FAILED',reason='Incomplete consumed condition; not repeated')
 args=['--mode',mode,'--release',r,'--model',n,'--seed',s]+(['--config',c] if c else []);return child('infer9.py',args,key)
def merge(L,parts,size):
 data=[read(p) for p in parts if p.exists()];points=[z for d in data for z in d['points']];rows=[z for d in data for z in d['contrasts']]
 # Preserve planned denominators, including explicit unavailable rows if any bounded child failed.
 while len(rows)<size:rows.append(dict(status='unavailable_missing_child',planned_row=len(rows)+1,p_unadjusted=1))
 holm(rows,L,size);csv(f'{L}_METRICS.csv',points);csv(f'{L}_CONTRASTS.csv',rows);dump(OUT/f'{L}_RESULTS.json',dict(utc=utc(),points=points,contrasts=rows,Holm_family_size=size,parts=[str(p) for p in parts],available_parts=len(data),planned_parts=len(parts)))
def main():
 gate();outcomes=[]
 while not (OUT/'TRAINING_COMPLETE.json').exists():time.sleep(5)
 frozen=OUT/'ANALYSIS_CODE_FROZEN.json';assert frozen.exists();assert read(OUT/'DEVELOPMENT_NUMERICAL_VERIFICATION.json')['all_checks_passed'];dump(OUT/'MODELS_FROZEN_PHASE9.json',dict(utc=utc(),models=[z for z in read(OUT/'TRAINING_OUTCOMES.json') if z['status']=='ok'],original_models=[oldspec(n,s) for n in MODELS for s in SEEDS],analysis_code_sha256=sha(frozen)))
 for d in ('complete','frozen'):(PRIVATE/d).mkdir(exist_ok=True)
 # Frozen-model transfer baselines missing from earlier phases: all r6.1 except cached TRACE.
 for n in ('F00','L1','XGBoost_40'):
  for s in SEEDS:outcomes.append(run_infer('zero','r6.1',n,s))
 for r in ('r5.1','r6.1','r6.2'):
  for n in MODELS:
   for s in SEEDS:outcomes.append(run_infer('restandard',r,n,s))
  outcomes.append(child('transfer_analysis9.py',['--test','L1','--release',r],f'L1_analysis_{r}'));dump(OUT/'PIPELINE_OUTCOMES.json',outcomes)
 merge('L1',[OUT/f'L1_{r}_RESULTS.json' for r in ('r5.1','r6.1','r6.2')],144)
 for r in RELEASES:
  for n in ('TA2','XGBoost_40'):
   for s in SEEDS:
    if (PRIVATE/f'training/reduced/results/{n}_{s}.json').exists():outcomes.append(run_infer('new',r,n,s,'reduced'))
  outcomes.append(child('transfer_analysis9.py',['--test','L2','--release',r],f'L2_analysis_{r}'));dump(OUT/'PIPELINE_OUTCOMES.json',outcomes)
 merge('L2',[OUT/f'L2_{r}_RESULTS.json' for r in RELEASES],96)
 for script in ('lead9.py','routes9.py','ensemble9.py','attribution9.py'):
  result={'lead9.py':'L3','routes9.py':'L4','ensemble9.py':'L5','attribution9.py':'L6'}[script]
  if not (OUT/f'{result}_RESULTS.json').exists():outcomes.append(child(script,[],result))
  dump(OUT/'PIPELINE_OUTCOMES.json',outcomes)
 for attack in ('uniform','source_targeted','TRACE_PGD','XGB_greedy'):
  for eps in (.1,.25,.5):
   for s in SEEDS:
    key=f'L7_{attack}_{eps:.2f}_{s}'
    if (PRIVATE/f'complete/{key}.json').exists():continue
    if (PRIVATE/f'consumed/{key}.json').exists():outcomes.append(dict(key=key,status='FAILED',reason='Incomplete consumed attack; no repeat'));continue
    outcomes.append(child('attacks9.py',['--seed',s,'--epsilon',eps,'--attack',attack],key))
   outcomes.append(child('robust_analysis9.py',['--test','L7','--condition',f'{attack}:{eps}'],f'L7_analysis_{attack}_{eps}'));dump(OUT/'PIPELINE_OUTCOMES.json',outcomes)
 merge('L7',[OUT/f'L7_{a}_{e}_RESULTS.json' for a in ('uniform','source_targeted','TRACE_PGD','XGB_greedy') for e in (.1,.25,.5)],96)
 for c in CONFIGS[1:]:
  for n in ('TA2','XGBoost_40'):
   for s in SEEDS:
    if not (PRIVATE/f'training/{c}/results/{n}_{s}.json').exists():continue
    outcomes.append(run_infer('new','r5.2_HOLDOUT',n,s,c))
    if c=='backdoor01':outcomes.append(run_infer('trigger','r5.2_HOLDOUT',n,s,c))
  outcomes.append(child('robust_analysis9.py',['--test','L8','--condition',c],f'L8_analysis_{c}'));dump(OUT/'PIPELINE_OUTCOMES.json',outcomes)
 merge('L8',[OUT/f'L8_{c}_RESULTS.json' for c in CONFIGS[1:]],96);dump(OUT/'ANALYSES_COMPLETE.json',dict(utc=utc(),outcomes=outcomes));status('ANALYSES_COMPLETE',failures=sum(z['status']!='ok' for z in outcomes))
if __name__=='__main__':main()
