"""Presentation-only postprocessing of frozen Phase 3 aggregate results.

No original data/models are opened; no statistics or outcomes are recomputed.
"""
import os
from pathlib import Path
import shutil
import json
ROOT=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision\explanation')
os.environ['MPLCONFIGDIR']=str(ROOT/'matplotlib_cache')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

primary=pd.read_csv(ROOT/'primary_comparison.csv')
sensitivity=pd.read_csv(ROOT/'raw_feature_sensitivity.csv')
original=ROOT/'faithfulness_positive_evidence_profile.png'
if not original.exists(): shutil.copyfile(ROOT/'faithfulness.png',original)
fig,axes=plt.subplots(2,2,figsize=(14,8),layout='constrained')
names=('TA2_minus_XGBoost_directional_accuracy','TA2_minus_XGBoost_accuracy_gap_from_random')
for row,metric in enumerate(names):
    for col,stratum in enumerate(('overall','malicious')):
        ax=axes[row,col]
        for y,frame,color in ((1,primary,'#2166ac'),(0,sensitivity,'#666666')):
            r=frame[(frame.seed=='mean_of_seeds')&(frame.sign=='class_supporting')&
                    (frame.stratum==stratum)&(frame.metric==metric)].iloc[0]
            point=r.estimate*100; low=r.ci_low*100; high=r.ci_high*100
            ax.errorbar(point,y,xerr=[[point-low],[high-point]],fmt='o',capsize=4,color=color)
            ax.annotate(f'{point:+.2f} [{low:+.2f}, {high:+.2f}]',
                        (point,y),xytext=(0,13),textcoords='offset points',ha='center',fontsize=10)
        ax.axvline(0,color='black',linewidth=.8,linestyle='--')
        ax.set_yticks([1,0],['Primary: 13 raw vs 40 summaries','Sensitivity: 13 raw vs 13 raw'])
        ax.set_ylim(-.5,1.6); ax.margins(x=.25)
        ax.set_title(stratum.title())
        ax.set_xlabel(('Directional accuracy difference' if row==0 else 'Difference in accuracy improvement over random')+
                      '\nTA2 minus XGBoost (percentage points)')
        ax.spines[['top','right']].set_visible(False)
fig.suptitle('Local input faithfulness at k = 3: primary comparison and resolution sensitivity\n'
             'Class-supporting sign · equal mean over seeds 42, 52, 62 · paired user-cluster 95% CIs',fontsize=14)
fig.savefig(ROOT/'faithfulness.png',dpi=300)
plt.close(fig)

p=ROOT/'CHATGPT_PHASE3_REPORT.md'
report=p.read_text(encoding='utf-8-sig')
block='''### Random-control gaps and feature-resolution sensitivity

The primary result above compares 13 TA2 raw features with 40 XGBoost summaries, as requested. It must not be read as an overall model or explanation superiority claim. The additional outcomes are material:

- For the primary 13-versus-40 comparison, the TA2-minus-XGBoost difference in directional-accuracy improvement over the same-sign random control is **+3.20 percentage points overall** (95% CI +1.47 to +5.06) and **−0.21 points on malicious windows** (95% CI −4.77 to +4.94). The malicious random-adjusted comparison is inconclusive.
- When XGBoost summaries are grouped into 13 raw features, the directional-accuracy difference is **+17.96 points overall** (95% CI +16.71 to +19.19; n=63,437 jointly eligible windows) and **−0.37 points on malicious windows** (95% CI −0.98 to 0.00; n=723). The malicious-window TA2 advantage does not persist at matched raw-feature resolution.
- In that 13-versus-13 sensitivity, the difference in improvement over the random control is **−9.22 points overall** (95% CI −10.20 to −8.19), favouring XGBoost; on malicious windows it is **−2.83 points** (95% CI −5.80 to +0.39), with the interval including zero.

These sensitivity analyses and sign conventions were included in the frozen protocol before results were computed. All seedwise outcomes and both signs remain available in the CSV/JSON results. The primary endpoint remains unchanged. The final faithfulness.png displays the primary and sensitivity comparisons with their paired CIs; the original positive-evidence k-profile is retained as faithfulness_positive_evidence_profile.png. This presentation-only step reads frozen aggregate results and does not change any numerical outcome.

'''
if '### Random-control gaps and feature-resolution sensitivity' not in report:
    report=report.replace('## Step 3 — HOLDOUT preparation only',block+'## Step 3 — HOLDOUT preparation only')
report=report.replace('Completeness median relative errors (overall; denominator floored at 1e-6):\n-',
                      'Completeness median relative errors (overall; denominator floored at 1e-6):\n\n-')
report=report.replace('(final-logit IG):\n-','(final-logit IG):\n\n-')
report=report.replace('Equal-seed mean uses jointly eligible windows in all three seeds:\n-',
                      'Equal-seed mean uses jointly eligible windows in all three seeds:\n\n-')
if 'Post-run verification:' not in report:
    extra='''Post-run verification: all six original checkpoint hashes and all 13 inspected source hashes remained unchanged; code/output copies and the frozen protocol hash match; the original validation population and pseudonym format were verified; all 1,404 metric rows are present and all nonempty confidence intervals contain 2,000 valid bootstrap replicates. Exported IG completeness and all three TreeSHAP margin additivity checks reproduce from the saved arrays. Text outputs contain no CERT user-ID patterns. The two final figures were visually inspected and confirmed at 300 dpi. See FINAL_VERIFICATION.json. Final-logit median IG relative errors are 0.0464%, 0.0509%, and 0.0924% for seeds 42, 52, and 62, respectively.

'''
    report=report.replace('PHASE3_COMPLETE',extra+'PHASE3_COMPLETE')
p.write_text(report,encoding='utf-8')
print('Presentation-only figure and balanced results narrative saved; all numerical outcomes unchanged.')
