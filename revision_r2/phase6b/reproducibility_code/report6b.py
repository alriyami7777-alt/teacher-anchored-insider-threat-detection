from common6b import *
import pandas as pd
def fmt(v,d=5):
 if v is None:return '—'
 if isinstance(v,float) and not np.isfinite(v):return '—'
 return f'{v:.{d}f}' if isinstance(v,(float,np.floating)) else str(v)
def table(rows,columns):
 text=['| '+' | '.join(label for _,label in columns)+' |','| '+' | '.join('---' for _ in columns)+' |']
 for r in rows:text.append('| '+' | '.join(fmt(r.get(k)).replace('|','/').replace('\n',' ') for k,_ in columns)+' |')
 return '\n'.join(text)+'\n'
def figures(models,effects):
 os.environ['MPLCONFIGDIR']=str(PRIVATE/'matplotlib_cache');import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
 plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':300})
 d=pd.DataFrame(models);d=d[(d.view=='pooled_completed')&(d.seed.astype(str)!='mean_three')];e=pd.DataFrame(effects)
 a=d[(d.model.isin(['XGBoost-40','XGBoost-260','RF-40','RF-260','LightGBM-40','LightGBM-260','MLP-40','MLP-260']))&(d.condition=='original')];a.to_csv(OUT/'figure_a_40_vs_260.csv',index=False)
 fig,ax=plt.subplots(figsize=(8,4.4))
 for j,width in enumerate((40,260)):
  names=['XGBoost','RF','LightGBM','MLP'];means=[]
  for i,n in enumerate(names):
   g=a[a.model==f'{n}-{width}'];means.append(g.PR_AUC.mean());ax.scatter(np.full(len(g),i+(j-.5)*.34)+np.linspace(-.05,.05,len(g)),g.PR_AUC,s=20,color='#243d4d',zorder=4)
  ax.bar(np.arange(4)+(j-.5)*.34,means,width=.32,label=f'{width} inputs',color=('#b5c4cf','#6f8fa6')[j])
 ax.set(xticks=np.arange(4),xticklabels=names,ylabel='Average precision (PR-AUC)',xlabel='Frozen model recipe',title='H1–H2 · Summary versus flattened sequence inputs');ax.legend();fig.tight_layout();fig.savefig(OUT/'figure_a_40_vs_260.png',dpi=300);plt.close(fig)
 b=d[(d.model.isin(['TRACE','TRACE-orderfree']))&(d.condition=='original')];b.to_csv(OUT/'figure_b_orderfree.csv',index=False);fig,ax=plt.subplots(figsize=(6.5,4.4))
 for i,n in enumerate(('TRACE','TRACE-orderfree')):
  g=b[b.model==n];ax.bar(i,g.PR_AUC.mean(),color=('#6f8fa6','#b5c4cf')[i]);ax.scatter(i+np.linspace(-.08,.08,len(g)),g.PR_AUC,color='#243d4d',s=25,zorder=3)
 ax.set(xticks=[0,1],xticklabels=['Chronological TRACE','Order-free TRACE'],ylabel='Average precision (PR-AUC)',xlabel='TRAIN, VALIDATION and scoring order',title='H3 · Chronological information in training');fig.tight_layout();fig.savefig(OUT/'figure_b_orderfree.png',dpi=300);plt.close(fig)
 c=d[d.model.isin(['TRACE','XGBoost-260'])];c.to_csv(OUT/'figure_c_interventions.csv',index=False);fig,axes=plt.subplots(1,2,figsize=(12,4.5),sharey=True);conditions=['original','reversed','fixed_shuffle','recent1','recent5','recent10']
 for ax,n in zip(axes,('TRACE','XGBoost-260')):
  for i,cond in enumerate(conditions):
   g=c[(c.model==n)&(c.condition==cond)];ax.bar(i,g.PR_AUC.mean(),color='#b5c4cf');ax.scatter(i+np.linspace(-.08,.08,len(g)),g.PR_AUC,color='#243d4d',s=18,zorder=3)
  ax.set(xticks=np.arange(6),xticklabels=['Original','Reverse','Shuffle','Recent 1','Recent 5','Recent 10'],xlabel='Inference condition (days retained)',ylabel='Average precision (PR-AUC)',title=n);ax.tick_params(axis='x',rotation=35)
 fig.suptitle('H4 · Order and zero-input history interventions');fig.tight_layout();fig.savefig(OUT/'figure_c_interventions.png',dpi=300);plt.close(fig)
 names=['TRACE','TRACE-10','TRACE-30','XGBoost-40','XGBoost-40-10','XGBoost-40-30'];dd=d[(d.model.isin(names))&(d.condition=='original')];dd.to_csv(OUT/'figure_d_history_ranking_excess.csv',index=False);fig,ax=plt.subplots(figsize=(7.5,4.5))
 for family,color in [('TRACE','#243d4d'),('XGBoost-40','#a16b3b')]:
  means=[]
  for t in (10,20,30):
   n=family if t==20 else family+f'-{t}';g=dd[dd.model==n];means.append(g.ranking_excess.mean());ax.scatter(np.full(len(g),t)+np.linspace(-.25,.25,len(g)),g.ranking_excess,s=18,color=color)
  ax.plot([10,20,30],means,'o-',label=family,color=color)
 ax.set(xticks=[10,20,30],xlabel='Completed-window length (days)',ylabel='Ranking excess (PR-AUC / prevalence)',title='H5 · History length on each full unseen-user cohort');ax.legend();fig.tight_layout();fig.savefig(OUT/'figure_d_history_ranking_excess.png',dpi=300);plt.close(fig)
 ee=e[(e.sign=='class_supporting')&(e.stratum=='overall')&(e.metric=='normalized_change_gap_from_random')];ee.to_csv(OUT/'figure_e_three_level_explanation.csv',index=False);fig,axes=plt.subplots(1,3,figsize=(14,4.5))
 for ax,level in zip(axes,('temporal','feature','tree')):
  sub=ee[ee.level==level];ks=sorted(sub.k.unique())
  for j,s in enumerate(SEEDS):
   g=sub[sub.seed==s].sort_values('k');xx=np.arange(len(g))+(j-1)*.18;ax.vlines(xx,g.ci95_low,g.ci95_high,color=('#243d4d','#6f8fa6','#a16b3b')[j]);ax.scatter(xx,g.estimate,color=('#243d4d','#6f8fa6','#a16b3b')[j],s=25,label=f'Seed {s}')
  ax.axhline(0,color='#888888',ls='--',lw=.8);ax.set(xticks=np.arange(len(ks)),xticklabels=ks,xlabel='Masked/replaced items (k)',ylabel='Top − random signed-logit change / DEV SD',title=level.title()+(' · reused' if level=='feature' else ''));ax.legend(fontsize=8)
 fig.suptitle('H6 · Overall class-supporting effects · 95% paired user-cluster CIs');fig.tight_layout();fig.savefig(OUT/'figure_e_three_level_explanation.png',dpi=300);plt.close(fig)
def main():
 a=read(OUT/'H1_H5_RESULTS.json');e=read(OUT/'H6_RESULTS.json');train=read(OUT/'TRAINING_RESULTS_PHASE6B.json');reuse=read(OUT/'H5_REUSED_TRAINING.json');freeze=read(OUT/'MODELS_FROZEN_PHASE6B.json');amend=read(OUT/'AMENDMENT5_RECEIPT.json');scoring=read(OUT/'SCORING_COMPLETE.json');h6out=read(OUT/'H6_SCORING_OUTCOMES.json');models=a['models'];contrasts=a['contrasts'];effects=e['effects'];figures(models,effects)
 training=[]
 for r in train:training.append(dict(model=('order-free '+r['model']) if r['orderfree'] else r['model'],seed=r['seed'],status=r['status'],epochs=r.get('epochs'),best_epoch=r.get('best_epoch'),development_AP=r.get('development_AP',r.get('dev_validation_pr_auc')),seconds=r.get('wall_seconds'),threshold=r.get('threshold'),source='Phase 6B new training',checkpoint_sha256=r.get('sha256'),checkpoint=r.get('checkpoint')))
 for r in reuse:training.append(dict(model=r['model'],seed=r['seed'],status=r['status'],epochs=r.get('epochs'),best_epoch=r.get('best_epoch'),development_AP=r.get('dev_validation_pr_auc'),seconds=r.get('wall_seconds'),threshold=r['threshold'],source='Verified Phase 6 reuse',checkpoint_sha256=r['sha256'],checkpoint=r['checkpoint']))
 for t in (10,30):
  for name in ('AL_PRECURSOR','T-OPT'):
   for s in SEEDS:
    r=read(R2/f'phase6/private/training/r52_T{t}_F13/results/{name}_{s}.json');assert r['sha256']==sha(r['checkpoint']);training.append(dict(model=f'T{t} own {name}',seed=s,status=r['status'],epochs=r.get('epochs'),best_epoch=r.get('best_epoch'),development_AP=r.get('dev_validation_pr_auc'),seconds=r.get('wall_seconds'),threshold=r['threshold'],source='Phase 6 prerequisite reuse',checkpoint_sha256=r['sha256'],checkpoint=r['checkpoint']))
 csv('COMPLETE_TRAINING_LOG.csv',training)
 deviations=[
  'H5 reuses the already completed Phase 6 T10/T30 development-only training, including all own AL/T-OPT teachers. The construction, frozen scalers, population, recipes and checkpoint hashes were verified before target scoring; these models had not previously scored these 500 HOLDOUT users. No duplicate fitting was done.',
  'The Amendment 5 temporal drafting error was corrected and hash-receipted before scoring. The unchanged Phase 6 helper zeros invalid standardized INPUT timesteps, re-encodes the full-length sequence, and applies masked-softmax attention. It does not mask a precomputed hidden-state tensor.',
  'Feature H6 is reused without running IG or interventions again. It retains its pre-existing 200 random controls; temporal and tree use the requested 25. Identical inherited positive/negative feature estimates and CIs were checked from saved arrays.',
  'H4 earlier days are zeroed in standardized input space, as explicitly requested. This differs from the median-filled partial-history sensitivity analysis in Phase 6.',
  'H5 full-cohort ranking excess is AP/prevalence, as defined in this prompt. AP minus prevalence is separately labelled in the CSV and is never substituted for that ratio.',
  'H5 paired comparisons retain each history length’s own completed-window label on matching end-days; endpoints have the same daily label. Label disagreements and exact intersections are reported.',
  'For H6 trees, reference-centred contributions are intervened at the final canonical mean readout. Earlier-layer outputs are not propagated again through later layers. Positive/negative same-sign replacement and magnitude ranking impose directional and magnitude constraints by construction; this is a readout faithfulness check, not independent evidence of behavioural causality.',
  'The Holm family contains all planned seedwise and mean-seed AP/F1 contrasts across all five views (840 tests). The 95% CIs are unadjusted percentile intervals; adjusted p-values do not turn these into simultaneous confidence intervals.'
 ]
 failures=[dict(type='training',**{k:r.get(k) for k in ('model','seed','status','reason')}) for r in train if r['status']!='ok']+[dict(type='scoring',**r) for r in scoring['outcomes'] if r['state']!='COMPLETE']+[dict(type='explanation',**r) for r in h6out if r['status']!='ok']
 pooled=[r for r in models if r['view']=='pooled_completed' and r['seed']=='mean_three'];ins={(r['model'],r['condition'],r['seed']):r['detected_insiders'] for r in a['insider_recall']}
 def modeltable(names,conditions=('original',)):
  out=[]
  for r in pooled:
   if r['model'] not in names or r['condition'] not in conditions:continue
   out.append(r|dict(insiders_42_52_62='/'.join(str(ins.get((r['model'],r['condition'],s),'—')) for s in SEEDS)))
  return out
 mc=[('model','Model'),('condition','Condition'),('windows','Windows'),('positive_windows','Positive'),('prevalence','Prevalence'),('PR_AUC','Mean AP'),('F1','Mean F1'),('insiders_42_52_62','Detected /25 (42/52/62)')]
 lines=['# Phase 6B: representation value on 500 unseen users','',f'Completed {utc()}. TRACE = TA2/F11. Evaluation uses the frozen 500-user HOLDOUT cohort in TRAIN + VALIDATION periods only. r5.2 TEST remains sealed. All three seeds (42/52/62), all views and all outcomes are retained.','',
 '## Amendment 5 and scoring boundary','',f"Amendment 5 was appended before Phase 6B scoring, UTC {amend['utc']}. Its SHA-256 is `{amend['sha256']}` over {amend['hashed_bytes']} bytes before its receipt. The preserved prior prefix is {amend['previous_prefix_bytes']} bytes, SHA-256 `{amend['previous_prefix_sha256']}`. The pre-scoring temporal clarification SHA-256 is `5b932a5ec7fec60d8984dfa31a061a09563491204946140c05b4aafc6bd0c0f2`. The complete appended amendment, both receipts and the preserved prefix are in [the preregistration](../holdout/PREREGISTRATION_R2_HOLDOUT.md). [Machine-readable receipt](AMENDMENT5_RECEIPT.json).",'',
 'Fitting uses only the frozen 1,500 development users in TRAIN. Checkpoints and thresholds use their VALIDATION only. The 500 held-out users supply evaluation values and user-cluster resamples only. They never supply fitting, selection, scaling, references, logit spreads or thresholds. Original Phase 4 clean predictions are reused without another clean evaluation pass. New model/condition passes have exclusive receipts. H6 separately extracts the necessary explanation intermediates on the pre-existing frozen 2,344-window cohort.','',
 '## Training log','',f"New runs: {sum(r['status']=='ok' for r in train)}/{len(train)} successful. Reused H5 target models: {len(reuse)}; their 12 AL/T-OPT prerequisites are also logged. Every child has a 120-minute timeout. One GPU child runs at a time, with a 35% allocator cap, two numerical CPU threads and cooperative pauses. No other chat’s process is controlled. All checkpoints are hash-frozen in [MODELS_FROZEN_PHASE6B.json](MODELS_FROZEN_PHASE6B.json).",'',table(training,[('model','Model / role'),('seed','Seed'),('source','Training source'),('status','Status'),('epochs','Epochs'),('best_epoch','Selected epoch'),('development_AP','DEV VALID AP'),('seconds','Seconds'),('threshold','Frozen threshold')]),
 'Exact checkpoint paths and hashes appear in [COMPLETE_TRAINING_LOG.csv](COMPLETE_TRAINING_LOG.csv). The original Phase 4 checkpoints remain unchanged.','',
 '## H1: same tree model, two inputs','',table(modeltable(['XGBoost-40','XGBoost-260','RF-40','RF-260','LightGBM-40','LightGBM-260','TRACE']),mc),'![H1–H2 input representations](figure_a_40_vs_260.png)','[Figure a CSV](figure_a_40_vs_260.csv). Bars are arithmetic seed means; dots are individual seeds.','',
 '## H2: same MLP, two inputs','',table(modeltable(['MLP-260','MLP-40']),mc),'Only input width changes. The hidden layers, dropout, weighted BCE, Adam, batch size, clipping, early stopping and validation threshold rule follow Phase 4.','',
 '## H3: training-time order removal','',table(modeltable(['TRACE','TRACE-orderfree']),mc),'Per-window order is fixed by SeedSequence([42, original split row index]); the same function is used in TRAIN, VALIDATION and HOLDOUT. The order-free TRACE has its own independently trained precursors and teachers.','![Chronological and order-free TRACE](figure_b_orderfree.png)','[Figure b CSV](figure_b_orderfree.csv).','',
 '## H4: inference-time order and history interventions','',table(modeltable(['TRACE','XGBoost-260'],('original','reversed','fixed_shuffle','recent1','recent5','recent10')),mc),'The fixed shuffle is default_rng(2026).permutation(20). Recent-day conditions zero all earlier standardized input timesteps and retain the original model and threshold.','![Inference conditions](figure_c_interventions.png)','[Figure c CSV](figure_c_interventions.csv).','',
 '## H5: history length on unseen users','',table(modeltable(['TRACE','TRACE-10','TRACE-30','XGBoost-40','XGBoost-40-10','XGBoost-40-30']),mc+[('ranking_excess','Mean AP / prevalence')]),
 'The descriptive rows above use each full cohort. Paired contrasts below use exact one-to-one matches on (user pseudonym, evaluation period, end-date), restricted to each length’s own view. Completed-window labels retain their own span; endpoint labels are the shared final-day label. All 500 user clusters are sampled with the same multiplicities on both sides, including clusters without matching positive windows.','',table(a['matched_end_days'],[('contrast','Contrast'),('view','View'),('matched_windows','Matched windows'),('matched_users','Matched users'),('matched_label_disagreements','Different labels')]),'![Ranking excess by window length](figure_d_history_ranking_excess.png)','[Figure d CSV](figure_d_history_ranking_excess.csv). Ranking excess here means AP divided by prevalence.','',
 '## H6: three-level explanation effects','',
 'The exact Phase 4 selection contains all 1,172 malicious windows plus 1,172 sampled benign windows from 448 users; seed 20261022. Temporal k=1/3/5/10 uses the unchanged Phase 6 I4 full-length zero-input and masked-softmax helper. Feature k=1/3/5 reuses Phase 4 IG interventions. Tree k=1/2/3 replaces reference-centred tree outputs at the canonical mean readout with development TRAIN means. New temporal/tree controls use 25 draws; inherited feature controls use 200. Logit change is divided by the exact Phase 4 per-seed development VALIDATION logit population SD. Strictly positive signed changes pass directional accuracy. Insufficient same-sign items are excluded and counted, never padded.','',
 'The table reports class-supporting effects (positive for malicious, negative for benign). Each effect is top minus random. All positive/negative effects, eligibility counts, p-values and Holm corrections are in the three full level CSVs and the JSON. Each level is a separate Holm family; no cross-level multiplicity is pooled.','']
 eh=[]
 for r in effects:
  if r['sign']=='class_supporting' and r['metric']=='normalized_change_gap_from_random':
   accuracy=next(q for q in effects if all(q[k]==r[k] for k in ('level','seed','k','sign','stratum')) and q['metric']=='directional_accuracy_gap_from_random');eh.append(r|dict(effect_CI=f"{fmt(r['estimate'])} [{fmt(r['ci95_low'])}, {fmt(r['ci95_high'])}]",accuracy_CI=f"{fmt(accuracy['estimate'])} [{fmt(accuracy['ci95_low'])}, {fmt(accuracy['ci95_high'])}]"))
 lines += [table(eh,[('level','Level'),('seed','Seed'),('k','k'),('stratum','Stratum'),('n_eligible','Eligible'),('effect_CI','Normalized logit gap [95% CI]'),('accuracy_CI','Accuracy gap [95% CI]'),('raw_p','Raw p (logit)'),('Holm_p','Holm p (logit)')]),'![Three-level explanation effects](figure_e_three_level_explanation.png)','[Figure e CSV](figure_e_three_level_explanation.csv). Separate panels have labelled axes; intervals are unadjusted paired user-cluster 95% CIs. Tree effects are constrained by their additive readout and magnitude-ranked intervention, so their positive values cannot independently establish causal explanatory value.','',
 f"Level family sizes: {e['level_family_sizes']}. [Temporal full effects](H6_TEMPORAL_CONTRASTS_HOLM.csv); [feature full effects](H6_FEATURE_CONTRASTS_HOLM.csv); [tree full effects](H6_TREE_CONTRASTS_HOLM.csv). Inherited feature numerical parity was checked on {len(e['feature_reuse_numerical_parity'])} estimate/CI combinations. The same finite-bootstrap resolution limit applies here: the smallest possible first Holm step is about 0.072 for temporal and 0.162 for feature/tree. Consequently, these preregistered families also cannot attain adjusted p<0.05 with this add-one two-sided formula and 2,000 draws. CI directions remain exploratory, and comparability is not an equivalence finding.",'',
 '## Full H1–H5 contrast table and Holm correction','',
 'All 840 planned tests form one exploratory Holm family: 21 contrasts × 5 views × 2 metrics × (three seeds plus their arithmetic mean). Bootstrap: 2,000 paired user-cluster replicates, seed 42. The three-seed mean averages metrics, not probabilities. Raw p is twice the smaller sign-tail proportion with an add-one correction. CI decisions are above when the lower bound exceeds zero, below when the upper bound is below zero, otherwise comparable. Holm decisions additionally require adjusted p<0.05. Undefined no-positive replicates are omitted and their valid counts are reported. Missing planned outcomes remain in the family with p=1.','']
 lines += ['With 2,000 replicates and the preregistered add-one two-sided p-value, the smallest attainable raw p is 2/2001 (about 0.001). Across 840 tests, the smallest possible first Holm step is about 0.840, so this finite bootstrap cannot yield a Holm rejection in H1–H5. CI directions remain descriptive exploratory evidence. Adjusted comparability here must not be interpreted as statistical equivalence or proof of no effect. This resolution limit is reported without changing the frozen family or adding resamples after scoring.','']
 ct=[r|dict(CI=f"[{fmt(r.get('ci95_low'))}, {fmt(r.get('ci95_high'))}]") for r in contrasts]
 headline=[r for r in ct if r['view']=='pooled_completed' and r['metric']=='PR_AUC' and r['seed']=='mean_three']
 insert=lines.index('## Full H1–H5 contrast table and Holm correction');lines[insert:insert]=['## Paired representation results on pooled completed windows','',
  'These are the planned three-seed mean AP contrasts on the primary view; H5 uses the declared matched end-days. Above/below/comparable describes the unadjusted 95% CI. Formal adjusted decisions and the finite-bootstrap resolution limit are reported separately. Cross-model TRACE contrasts are contextual; the representation tests compare the same recipe under different inputs or interventions.','',
  table(headline,[('H','H'),('contrast','Contrast'),('estimate','Mean AP delta'),('CI','95% CI'),('CI_decision','CI direction'),('raw_p','Raw p'),('Holm_p','Holm p')]),'']
 lines+=[table(ct,[('H','H'),('contrast','Contrast'),('view','View'),('metric','Metric'),('seed','Seed'),('estimate','Delta'),('CI','95% CI'),('valid_bootstrap_replicates','Valid B'),('raw_p','Raw p'),('Holm_p','Holm p'),('CI_decision','CI decision'),('Holm_decision','Holm decision')]),'[Full-precision contrast CSV](H1_H5_FULL_CONTRASTS_HOLM.csv). [All model/condition/seed/view metrics](ALL_MODEL_VIEWS.csv). [Insider recall](INSIDER_RECALL.csv). Insider detections are counted at each frozen development threshold among the same 25 insiders; pseudonyms only appear in the detailed JSON.','',
 '## Skips, failures and deviations','']
 lines += ['No training, scoring or explanation run was skipped, failed or timed out.'] if not failures else [table(failures,[('type','Stage'),('model','Model'),('seed','Seed'),('status','Status'),('state','State'),('reason','Reason')])]
 amendment_text=(H/'PREREGISTRATION_R2_HOLDOUT.md').read_bytes()[amend['previous_prefix_bytes']:].decode('utf-8')
 insert=lines.index('## Training log');lines[insert:insert]=['### Complete frozen Amendment 5 record','',amendment_text,'']
 lines+=['']+['- '+x for x in deviations]+['','## Verification and files','',
 'The final audit verifies amendment prefix/receipts, frozen checkpoint hashes, prediction hashes and exclusive receipts, the 840-test family and separate H6 families, exact inherited feature parity, permitted period boundaries, pseudonym-only public identifiers, all five 300-dpi figures and paired CSVs, and the report completion marker. [Machine-readable results](PHASE6B_RESULTS.json). [Final audit](FINAL_AUDIT.json).','',
 'Scope: these exploratory results concern the specified CERT r5.2 unseen users and completed-window protocol. They do not open r5.2 TEST and do not establish performance outside this cohort.','', 'PHASE6B_COMPLETE']
 (OUT/'CHATGPT_PHASE6B_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 dump(OUT/'PHASE6B_RESULTS.json',dict(utc=utc(),complete=True,amendment5=amend,training_log=training,models=models,insider_recall=a['insider_recall'],H1_H5_contrasts=contrasts,H5_matched_end_days=a['matched_end_days'],H6=e,scoring_outcomes=scoring['outcomes'],H6_scoring_outcomes=h6out,failures=failures,deviations=deviations,r52_test_read=False,holdout_used_for_training_selection_scaling_thresholds=False,actual_final_code_sha256={p.name:sha(p) for p in CODE.glob('*.py')},figures={f.name:sha(f) for f in OUT.glob('figure_*')},report_sha256=sha(OUT/'CHATGPT_PHASE6B_REPORT.md')))
 status('REPORT_WRITTEN')
if __name__=='__main__':main()
