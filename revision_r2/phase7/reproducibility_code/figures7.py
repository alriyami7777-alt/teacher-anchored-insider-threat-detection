from common7 import *
os.environ['MPLCONFIGDIR']=str(PRIVATE/'matplotlib_cache')
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.text import Text
plt.rcParams.update({'font.size':12,'axes.labelsize':12,'axes.titlesize':14,'xtick.labelsize':12,'ytick.labelsize':12,'legend.fontsize':12,'figure.titlesize':16,'axes.spines.top':False,'axes.spines.right':False})
COLORS={'TRACE':'#243d4d','XGBoost-40':'#a16b3b','F00':'#8d8d8d','L1':'#6f8fa6','LightGBM-40':'#527060','Transformer':'#9b7d8d','Rank-average':'#527060'}
receipts=[]
def save(fig,stem,data,caption):
 fig.text(.5,.012,caption,ha='center',fontsize=12);fig.canvas.draw();sizes=[t.get_fontsize() for t in fig.findobj(Text) if t.get_text()];assert sizes and min(sizes)>=12
 fig.savefig(OUT/f'{stem}.png',dpi=300);csv(f'{stem}.csv',data);receipts.append(dict(stem=stem,dpi=300,minimum_font_pt=min(sizes),size_inches=fig.get_size_inches(),png_sha256=sha(OUT/f'{stem}.png'),CSV_sha256=sha(OUT/f'{stem}.csv')));plt.close(fig)
def main():
 a=read(OUT/'CASE_ATTRIBUTION_RESULTS.json');op=read(OUT/'OPERATIONAL_RESULTS.json');co=read(OUT/'COMBINATION_SENSITIVITY_RESULTS.json');m,o=metadata()
 for case in a['cases']:
  user=case['user'];ui=int(np.flatnonzero(o['user']==user)[0]);d=pd.read_csv(OUT/'P1_ALL_CASE_WINDOW_SCORES.csv');d=d[d.user==user];fig,axes=plt.subplots(3,1,figsize=(16,10),sharex=True)
  for ax,s in zip(axes,SEEDS):
   g=d[d.seed==s];t=spec('TRACE',s)['threshold']
   for part,gg in g.groupby('partition'):ax.plot(pd.to_datetime(gg.end_date),gg.score,color=COLORS['TRACE'],lw=1.2,label='Saved TRACE score' if part=='train' else None)
   ax.axhline(t,color='#a16b3b',ls='--',lw=1.6,label=f'Frozen threshold {t:.2f}')
   for j,day in enumerate(o['calendar'][o['daily_y'][ui]==1]):ax.axvspan(pd.Timestamp(day),pd.Timestamp(day)+pd.Timedelta(days=1),color='#b15e5e',alpha=.25,label='Malicious day' if j==0 else None)
   ax.set(ylabel='Probability score',title=f'{user} · scenario {case["scenario"]} · TRACE seed {s}',ylim=(0,1));ax.grid(alpha=.15);ax.legend(loc='upper right',ncol=3)
  axes[-1].set_xlabel('Window end date');fig.tight_layout(rect=[0,.055,1,1]);save(fig,f'figure_P1_timeline_{user}',d,'CERT r5.2 HOLDOUT · permitted TRAIN + VALIDATION · gaps are unscorable period starts')
  fig,axes=plt.subplots(3,3,figsize=(18,13));combined=[]
  for row,s in enumerate(SEEDS):
   att=[r for r in a['attention'] if r['user']==user and r['seed']==s];ig=sorted([r for r in a['IG_features'] if r['user']==user and r['seed']==s],key=lambda r:r['absolute_rank'])[:6];tr=[r for r in a['tree_contributions'] if r['user']==user and r['seed']==s]
   axes[row,0].bar([r['timestep'] for r in att],[r['attention'] for r in att],color=['#b15e5e' if r['malicious_day'] else '#6f8fa6' for r in att]);axes[row,0].set(title=f'Seed {s}: attention',xlabel='Timestep (red = malicious day)',ylabel='Attention weight',xticks=[1,5,10,15,20])
   axes[row,1].barh([r['feature'].replace('_',' ') for r in ig][::-1],[r['absolute_IG_share'] for r in ig][::-1],color='#6f8fa6');axes[row,1].set(title=f'Seed {s}: top six IG shares',xlabel='Absolute IG / total absolute IG',ylabel='Daily feature')
   axes[row,2].bar([r['tree'] for r in tr],[r['reference_centred_logit_contribution'] for r in tr],color=['#243d4d' if r['top_three'] else '#b5c4cf' for r in tr]);axes[row,2].axhline(0,color='#888888',lw=.7);axes[row,2].set(title=f'Seed {s}: tree contributions',xlabel='Tree index (dark = top three)',ylabel='Logit difference / 8',xticks=range(1,9))
   combined.extend([r|dict(component='attention') for r in att]+[r|dict(component='IG') for r in a['IG_features'] if r['user']==user and r['seed']==s]+[r|dict(component='tree') for r in tr])
  fig.suptitle(f'{user}: highest-scoring malicious window per seed');fig.tight_layout(rect=[0,.065,1,.96]);save(fig,f'figure_P1_explanations_{user}',combined,'Saved Phase 4/6B explanations · IG approximation errors are reported; attribution is descriptive')
 fig,axes=plt.subplots(1,2,figsize=(15,6.5));x=np.arange(3)
 for j,n in enumerate(('TRACE','XGBoost-40')):
  vals=[next(r['noninsiders_flagged'] for r in op['P2_counts'] if r['model']==n and r['seed']==s) for s in SEEDS];axes[0].bar(x+(j-.5)*.35,vals,.33,color=COLORS[n],label=n)
 axes[0].set(xticks=x,xticklabels=SEEDS,xlabel='Frozen model seed',ylabel='Non-insiders ever flagged / 475',title='(a) Full-cohort false-alarm users');axes[0].legend()
 attrib=pd.DataFrame(a['P2_attribution']);attrib=attrib[attrib.level=='source'];src=list(SOURCE_GROUPS);yy=np.arange(len(src))
 for j,(group,label,color) in enumerate([('false_alarm_noninsider','False alarms: 3/5/5 windows','#a16b3b'),('true_positive','True positives: 968/969/973','#243d4d')]):
  vals=[attrib[(attrib.group==group)&(attrib.name==k)].mean_absolute_IG_share.mean() for k in src];axes[1].barh(yy+(j-.5)*.35,vals,.33,color=color,label=label)
 axes[1].set(yticks=yy,yticklabels=src,xlabel='Absolute IG share (mean of seed means)',ylabel='Source group',title='(b) Saved-cohort attribution coverage');axes[1].legend(loc='lower right');fig.tight_layout(rect=[0,.07,1,1]);save(fig,'figure_P2_false_alarms',[r|dict(panel='counts') for r in op['P2_counts']]+[r|dict(panel='attribution') for r in a['P2_attribution'] if r['level']=='source'],'Full-cohort counts; sampled false-alarm IG coverage below 0.8% · no population attribution claim')
 b=pd.DataFrame(op['P4_budget_results']);fig,axes=plt.subplots(1,2,figsize=(15,6.5));styles=['-','--',':','-.','--',':']
 for n,ls in zip(NAMES.values(),styles):
  g=b[b.model==n].groupby('budget').mean(numeric_only=True)
  for ax,col in zip(axes,('insiders_caught','user_day_precision')):ax.plot(g.index,g[col],marker='o',lw=1.8,label=n,color=COLORS[n],ls=ls)
 axes[0].set(title='(a) Insiders caught',xlabel='Daily user alert budget B',ylabel='Insiders caught / 25 (seed mean)',xticks=[1,2,5,10],ylim=(0,26));axes[1].set(title='(b) Completed-window user-day precision',xlabel='Daily user alert budget B',ylabel='Positive user-day alerts / all alerts',xticks=[1,2,5,10],ylim=(0,1));axes[1].legend(ncol=2);fig.tight_layout(rect=[0,.07,1,1]);save(fig,'figure_P4_daily_budget',b,'426 scorable days · workload per seed = 426 × B · scores and daily policy fixed before bootstrap')
 fig,axes=plt.subplots(1,2,figsize=(13,6));d=pd.DataFrame(co['P5_metrics']);d=d[d.seed.astype(str)!='mean_three'];names=['TRACE','XGBoost-40','Rank-average']
 for ax,metric,label in zip(axes,['PR_AUC','F1'],['Average precision (PR-AUC)','F1 at frozen development threshold']):
  for j,n in enumerate(names):g=d[d.model==n];ax.bar(j,g[metric].mean(),color=COLORS[n],alpha=.6);ax.scatter(j+np.linspace(-.1,.1,3),g[metric],color=COLORS[n],s=30)
  ax.set(xticks=range(3),xticklabels=names,ylabel=label,xlabel='Frozen rule / model',ylim=(0,1))
 axes[0].set_title('(a) Ranking');axes[1].set_title('(b) Operating-point performance');fig.tight_layout(rect=[0,.08,1,1]);save(fig,'figure_P5_rank_average',co['P5_metrics'],'One predeclared combination · bars: seed means · dots: 42/52/62 · HOLDOUT ranks are split-relative')
 fig,axes=plt.subplots(1,3,figsize=(17,6.5),sharey=True);d=pd.DataFrame(co['P6_metrics']);rules=['original_max_F1','recall_ge_0.90','precision_ge_0.50'];markers=['o','s','^'];labels=['Original max-F1','Recall ≥ 0.90','Precision ≥ 0.50']
 for ax,n in zip(axes,('TRACE','XGBoost-40','L1')):
  for rule,marker,label in zip(rules,markers,labels):g=d[(d.model==n)&(d.rule==rule)];ax.scatter(g.noninsiders_flagged,g.insiders_detected,marker=marker,s=80,label=label,color=COLORS[n],alpha=.8)
  ax.set(title=n,xlabel='Non-insiders ever flagged / 475',ylabel='Insiders detected / 25',ylim=(18,25.5));ax.grid(alpha=.15)
 axes[-1].legend(loc='lower right');fig.tight_layout(rect=[0,.07,1,1]);save(fig,'figure_P6_threshold_rules',d,'Each point is one seed · threshold rules applied unchanged from development VALIDATION')
 dump(OUT/'FIGURE_RECEIPTS.json',dict(utc=utc(),figures=receipts));status('FIGURES_COMPLETE',figures=len(receipts),minimum_font_pt=min(r['minimum_font_pt'] for r in receipts))
if __name__=='__main__':main()
