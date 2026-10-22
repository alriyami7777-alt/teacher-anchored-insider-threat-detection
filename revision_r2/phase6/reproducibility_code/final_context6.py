"""Final interpretation context from already-saved labels/intervals; no model evaluation."""
from common6 import *
import shutil
def main():
 y=np.load(PRIVATE/'data/r42_T20_F13/test_y.npy')
 with np.load(PRIVATE/'data/r42_T20_F13/test_metadata.npz') as z:users=z['user']
 assert not set(users)&excluded()
 t=read(OUT/'T_RESULTS.json');valid=sorted(set(r['valid_bootstrap_replicates'] for r in t['r42_test_CIs'] if r['metric']=='PR_AUC'))
 context=dict(utc=utc(),release='r4.2',partition='TEST',users=len(set(users)),positive_users=len(set(users[y==1])),positive_windows=int(y.sum()),windows=len(y),AP_valid_bootstrap_replicates=valid,attempted_replicates=2000,bootstrap_seed=42,AP_rule='Draws with no positive windows omitted',ratio_zero_denominator_rule='F1, precision and recall use zero_division=0',new_model_evaluation=False)
 dump(OUT/'POSTSCORING_COHORT_CONTEXT.json',context)
 p=OUT/'CHATGPT_PHASE6_REPORT.md';text=p.read_text(encoding='utf-8');marker='## Part T3: r4.2 independent TEST\n\n';assert text.count(marker)==1
 para=f"The saved TEST cohort has {len(y):,} windows from {len(set(users)):,} users, including {int(y.sum())} positive windows from only {len(set(users[y==1]))} positive users. This small positive-cluster count limits generalisation. AP contrasts retain {', '.join(map(str,valid))} of 2000 bootstrap draws, omitting draws with no positive windows; F1, precision and recall use zero-division=0 when a denominator is zero. All bootstrap draw/valid counts remain in the tables. [Post-scoring cohort context](POSTSCORING_COHORT_CONTEXT.json).\n\n"
 text=text.replace(marker,marker+para);p.write_text(text,encoding='utf-8',newline='\n')
 q=read(OUT/'EDITORIAL_QA_RECEIPT.json');q['report_after_sha256']=sha(p);q['changes'].append('Added positive-user count and exact bootstrap validity/zero-denominator conventions from saved TEST labels and intervals');q['postscoring_context_sha256']=sha(OUT/'POSTSCORING_COHORT_CONTEXT.json');q['visual_QA']=dict(all_eight_figures_inspected=True,attention_legend_clear=True,all_actual_k_ticks_visible=True,axis_labels_and_titles_unclipped=True)
 for n,h in q['numerical_input_hashes'].items():assert sha(OUT/n)==h
 q['final_context_script_sha256']=sha(__file__);dump(OUT/'EDITORIAL_QA_RECEIPT.json',q);shutil.copyfile(__file__,OUT/'reproducibility_code/final_context6.py')
 print(json.dumps(context,indent=2))
if __name__=='__main__':main()
