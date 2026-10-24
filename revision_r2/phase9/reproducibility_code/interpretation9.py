"""Display summaries of the complete frozen comparisons; no model or statistical selection."""
from common9 import *
def num(v):return 'unavailable' if v is None or not np.isfinite(float(v)) else f'{float(v):.5g}'
def label(n):return {'TA2':'TRACE','XGBoost_40':'XGBoost-40','L1':'attention–linear'}.get(n,n)
def mean(v,key):return float(np.mean([z[key] for z in v])) if v else None
def narrative(k,r):
 rows=r.get('contrasts',[]);primary=[z for z in rows if z.get('seed')=='mean' and z.get('metric')=='PR_AUC' and z.get('estimate') is not None];points=r.get('points',[]);out=[]
 if k in ('L1','L2'):
  pos=sum(z['estimate']>0 for z in primary);above=sum(z.get('ci95_low',-np.inf)>0 for z in primary);below=sum(z.get('ci95_high',np.inf)<0 for z in primary);verb='Target re-standardisation' if k=='L1' else 'Feature removal'
  out.append(f'{verb} raises the three-seed mean AP point estimate in {pos}/{len(primary)} release/model comparisons. The unadjusted AP-difference CIs are wholly above zero in {above}, wholly below zero in {below}, and otherwise include zero. The complete Holm family remains separate from this descriptive count.')
  for release in (('r5.1','r6.1','r6.2') if k=='L1' else RELEASES):
   q=[z for z in primary if z.get('release')==release];bits=[]
   for z in q:bits.append(f"{label(z['model'])} ΔAP {num(z['estimate'])} [{num(z['ci95_low'])}, {num(z['ci95_high'])}]")
   out.append(release+': '+('; '.join(bits) if bits else 'unavailable')+'.')
   if k=='L1':
    before=[z for z in points if z.get('release')==release and z.get('model')=='TA2' and z.get('side')=='reference'];after=[z for z in points if z.get('release')==release and z.get('model')=='TA2' and z.get('side')=='new'];out.append(f"TRACE absolute means for {release}: AP {num(mean(before,'PR_AUC'))} → {num(mean(after,'PR_AUC'))}; AP/prevalence {num(mean(before,'AP_over_prevalence'))} → {num(mean(after,'AP_over_prevalence'))}; top1% insider recall {num(mean(before,'top1_insider_recall'))} → {num(mean(after,'top1_insider_recall'))}.")
  if k=='L1':out.append('These results assess batch feature-moment adaptation. They do not isolate every semantic or class-conditional cause of transfer failure. The finite-bootstrap L1 Holm resolution limit is stated above and in the deviations.')
 if k=='L3':
  q=[z for z in rows if z.get('seed')=='mean' and z.get('model')=='TA2'];out.append('TRACE three-seed mean matched AUC by lead: '+('; '.join(f"{z['lead']} days: {num(z['estimate'])} [{num(z['ci95_low'])}, {num(z['ci95_high'])}], Holm p={num(z['p_Holm'])}" for z in q))+'. Exact-date eligibility, retrospective conditioning and the separate CI-based forecasting rule remain explicit.')
 if k=='L4':
  q=[z for z in rows if z.get('seed')=='mean' and z.get('stratum')=='all'];out.append('Across the saved explanation cohort, top-minus-random class-support loss (logit units) is '+('; '.join(f"m={z['k']}: {num(z.get('estimate'))} [{num(z.get('ci95_low'))}, {num(z.get('ci95_high'))}]" for z in q))+'. Positive values mean that the ranked flips remove more original class support than the matched random flips. This is the declared local routing intervention, with downstream feature computations fixed. For m=1 the flip loss is twice the neutralisation contribution used to rank routes, up to numerical clamping; its comparison is therefore algebraically coupled to the ranking criterion and cannot independently establish faithfulness.')
 if k=='L5':
  for n in ('TA2','F00','XGBoost_40'):
   q=[z for z in points if z.get('model')==n];out.append(label(n)+': '+('; '.join(f"{z['group']}-seed average AP {num(z['PR_AUC'])}, {z['insiders_detected']}/25 insiders detected, {z['noninsiders_flagged']}/475 non-insiders flagged" for z in q))+'.')
  out.append('The contrast table compares each averaged-score system with the arithmetic mean of its constituent single-seed metrics, retaining their respective validation-only thresholds.')
 if k=='L6':
  for base in ('fresh_abs_input_gradient','plain_abs_input','fully_randomized_IG'):
   q=[z['median_rho'] for z in points if z['baseline']==base and z.get('median_rho') is not None];out.append(f"{base}: per-seed median rank correlation spans {num(min(q))} to {num(max(q))}." if q else base+': unavailable.')
  out.append('Persistence or change is reported without a tuned sanity-test cutoff; input structure and inherited IG approximation errors limit a fidelity interpretation.')
 if k=='L7':
  for attack in ('uniform','source_targeted','TRACE_PGD','XGB_greedy'):
   q=[z for z in points if z.get('condition')==attack+':0.5'];bits=[]
   for n in ('TA2','XGBoost_40'):
    a=[z for z in q if z['model']==n];bits.append(f"{label(n)} {num(mean(a,'insiders_detected'))}/25 insiders, AP retention {num(mean(a,'AP_retention'))}")
   out.append(f'At the largest declared count budget (ε=0.50), {attack}: '+('; '.join(bits))+'. These are arithmetic seedwise metric means; all smaller budgets remain in the tables.')
  out.append('Presence indicators remain fixed under these count-box budgets. White-box and query-generated perturbations have different target models, and each cross-model contrast uses identical perturbed inputs.')
 if k=='L8':
  q=[z for z in primary if z.get('model') in ('TA2','XGBoost_40')];out.append(f"Poisoning lowers the clean AP point estimate in {sum(z['estimate']<0 for z in q)}/{len(q)} condition/model comparisons. Negative poisoned-minus-clean differences indicate degradation; all observed improvements also remain reported.")
  for n in ('TA2','XGBoost_40'):
   a=[z for z in points if z.get('model')==n and z.get('condition')=='backdoor01_triggered' and z.get('ASR_population')=='malicious_containing_insider_windows'];b=[z for z in points if z.get('model')==n and z.get('condition')=='backdoor01_triggered' and z.get('ASR_population')=='all_insider_windows'];out.append(f"{label(n)} backdoor: mean below-threshold rate on triggered malicious-containing windows {num(mean(a,'attack_success_rate'))}; the same poisoned model's clean rate is {num(mean(a,'clean_poisoned_model_below_threshold_rate'))}. The all-insider-window triggered rate is {num(mean(b,'attack_success_rate'))}, which includes benign activity.")
  out.append('ASR is a descriptive trigger response. The predeclared comparisons do not separately estimate a poison-by-trigger interaction against an unpoisoned triggered control.')
 return out
