"""Presentation-only final QA. Never loads a dataset or model or recomputes statistics."""
from common6 import *
import pandas as pd,shutil
def main():
 report=OUT/'CHATGPT_PHASE6_REPORT.md';png=OUT/'I4_ATTENTION_EFFECT_CIS.png';archive=PRIVATE/'qa_preimages'
 assert not archive.exists();archive.mkdir()
 for p in (report,png,OUT/'FINAL_VERIFICATION.json'):shutil.copyfile(p,archive/p.name)
 numerical={p.name:sha(p) for p in OUT.iterdir() if p.suffix=='.csv' or p.name in ('PHASE6_RESULTS.json','I_RESULTS.json','T_RESULTS.json','TRAINING_RESULTS_PHASE6.json')}
 before_report=sha(report);before_png=sha(png);i=read(OUT/'I_RESULTS.json');t=read(OUT/'T_RESULTS.json')
 text=report.read_text(encoding='utf-8')
 text=text.replace('All configuration parameters, epoch histories, checkpoint hashes and durations are in','For XGBoost and RF, `epochs` and `best_epoch` record the fixed boosting-round/tree counts (300 and 200 respectively); they are not neural epochs or a checkpoint search. Neural rows record actual epochs and validation-selected best epochs.\n\nAll configuration parameters, epoch histories, checkpoint hashes and durations are in',1)
 old='No model training, inference or required comparison was skipped. The preparation compatibility fixes and cohort restrictions are disclosed above.'
 new='All 57 scheduled training runs and all scoring runs on the permitted cohorts succeeded; no run failed or timed out. The full historical all-user validation and 613-positive multi-day cohorts were not evaluated because they include prohibited HOLDOUT users. The allowed development-only cohorts and the actual r5.2 attention case protocol were used as disclosed above. No separate Phase 5B was run.'
 assert text.count(old)==1;text=text.replace(old,new)
 def summary_ci(row):return f"{row['estimate']:+.6f} [{row['ci95_low']:.6f}, {row['ci95_high']:.6f}]"
 order=[next(r for r in i['order_history_CIs'] if r['seed']=='mean_three' and r['metric']=='PR_AUC' and r['comparison'].startswith('TRACE '+c+' ')) for c in ('T1','T2')]
 same=next(r for r in i['same_information_CIs'] if r['seed']=='mean_three' and r['metric']=='PR_AUC' and r['comparison']=='TRACE minus XGBoost-260')
 six=next(r for r in t['feature_CIs'] if r['seed']=='mean_three' and r['comparison']=='r52_T20_F6 TRACE minus matched development 13-feature')
 twenty_nine=next(r for r in t['feature_CIs'] if r['seed']=='mean_three' and r['comparison']=='r52_T20_F29 TRACE minus matched development 13-feature')
 test=next(r for r in t['r42_test_CIs'] if r['seed']=='mean_available_seeds' and r['metric']=='PR_AUC' and r['comparison']=='TRACE minus XGBoost_40')
 mean_trace=np.mean([r['PR_AUC'] for r in t['r42_test'] if r['model']=='TRACE'])
 observations=f"""## Main observations

On development-only r5.2 VALIDATION, reversing or shuffling TRACE inputs lowered mean-seed AP: reversed minus original {summary_ci(order[0])}; fixed shuffle minus original {summary_ci(order[1])}. Brackets give paired user-cluster 95% intervals. Partial-history results and all seedwise outcomes appear below.

With identical 20 × 13 information, TRACE minus XGBoost-260 mean AP was {summary_ci(same)}. TRACE versus attention–linear AP has an interval spanning zero; this does not establish equivalence.

Against the matched development-only 13-feature TRACE, the 6-feature AP difference was {summary_ci(six)} and the 29-feature difference was {summary_ci(twenty_nine)}. The 29-feature comparison with the original all-user checkpoint uses a different training population and is separately tabulated; it should not replace the matched comparison.

On the single r4.2 TEST evaluation, TRACE mean AP was {mean_trace:.6f}, while XGBoost-40 and RF-40 each had mean AP 1.000000. TRACE minus XGBoost-40 AP was {summary_ci(test)}. The complete F1, precision, recall and paired intervals are retained below. These outcomes were not used to alter any model, threshold or configuration.

"""
 assert text.count('## Training log')==1;text=text.replace('## Training log',observations+'## Training log',1)
 evidence='Additional integrity receipts: [frozen-baseline row alignment](FROZEN_BASELINE_ROW_ALIGNMENT_VERIFIED.json), [r4.2 TRAIN/VALIDATION label parity](R42_TRAIN_VALIDATION_LABEL_PARITY.json), [F29 cache provenance](F29_CACHE_PROVENANCE_VERIFIED.json), [development reference checkpoint hashes](DEVELOPMENT_REFERENCE_MODELS_VERIFIED.json), and [CPU model/mask preflight parity](CPU_PREFLIGHT_PARITY.json). Reproducibility scripts are in `reproducibility_code/`. Final presentation QA is recorded in [EDITORIAL_QA_RECEIPT.json](EDITORIAL_QA_RECEIPT.json).\n\n'
 assert text.endswith('PHASE6_COMPLETE\n');text=text[:-len('PHASE6_COMPLETE\n')]+evidence+'PHASE6_COMPLETE\n';report.write_text(text,encoding='utf-8',newline='\n')
 # Plot exactly the saved intervals; move the legend outside both panels.
 os.environ['MPLCONFIGDIR']=str(PRIVATE/'matplotlib_cache');import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
 d=pd.read_csv(OUT/'I4_ATTENTION_EFFECT_CIS_data.csv');fig,axes=plt.subplots(1,2,figsize=(10,5.1))
 for ax,kind in zip(axes,['delete','retain']):
  for seed in SEEDS:
   a=d[(d.seed==seed)&(d.intervention==kind)].sort_values('k');ax.errorbar(a.k,a.estimate,yerr=np.maximum(0,np.array([a.estimate-a.ci95_low,a.ci95_high-a.estimate])),marker='o',capsize=3,label=f'Seed {seed}')
  ax.axhline(0,color='0.5',lw=1);ax.set_xticks([1,3,5,10]);ax.set(xlabel='Number of timesteps k',ylabel='Top − matched random confidence gap',title='Deletion' if kind=='delete' else 'Retention / sufficiency gap');ax.grid(alpha=.2)
 handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=3,frameon=False);fig.tight_layout(rect=(0,.08,1,1));fig.savefig(png,dpi=300);plt.close(fig)
 for n,h in numerical.items():assert sha(OUT/n)==h,'Numerical result changed during presentation QA'
 dest=OUT/'reproducibility_code/editorial_qa6.py';shutil.copyfile(__file__,dest)
 dump(OUT/'EDITORIAL_QA_RECEIPT.json',dict(utc=utc(),changes=['Clarified full-cohort exclusions and zero failed/timed-out runs','Clarified tree/boosting-round counts in epoch columns','Added observations derived only from saved result tables and linked integrity receipts','Moved attention CI legend outside panels and used the actual k ticks'],report_before_sha256=before_report,report_after_sha256=sha(report),attention_figure_before_sha256=before_png,attention_figure_after_sha256=sha(png),all_numerical_inputs_unchanged=True,numerical_input_hashes=numerical,training_and_inference_repeated=False,script_sha256=sha(__file__)))
 print('Presentation QA complete; numerical results unchanged',flush=True)
if __name__=='__main__':main()
