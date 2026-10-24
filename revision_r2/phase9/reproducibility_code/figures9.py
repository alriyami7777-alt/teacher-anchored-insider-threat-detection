from common9 import *
os.environ['MPLCONFIGDIR']=str(PRIVATE/'matplotlib_cache')
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams.update({'font.size':12,'axes.titlesize':14,'axes.labelsize':12,'xtick.labelsize':12,'ytick.labelsize':12,'legend.fontsize':12,'figure.titlesize':16})
figures=[]
def model_label(n):return {'TA2':'TRACE','XGBoost_40':'XGBoost-40','L1':'Attention–linear'}.get(n,n)
def group_label(n):return {'three':'3 seeds','eight':'8 seeds'}.get(n,n)
def metric_label(n):return {'PR_AUC':'PR-AUC','insiders_detected':'Insiders detected','noninsiders_flagged':'Non-insiders flagged'}.get(n,n)
def condition_label(n):return {'flip01':'Label flip 1%','flip05':'Label flip 5%','flip10':'Label flip 10%','backdoor01':'Backdoor 1%'}.get(n,n)
def save(fig,stem,data,note):
 from matplotlib.text import Text
 fig.text(.5,.012,note,ha='center',va='bottom',fontsize=12);fig.canvas.draw();minimum=min(t.get_fontsize() for t in fig.findobj(Text) if t.get_text());assert minimum>=12;size=fig.get_size_inches().tolist();fig.savefig(OUT/f'{stem}.png',dpi=300);plt.close(fig);pd.DataFrame(data).to_csv(OUT/f'{stem}.csv',index=False);figures.append(dict(stem=stem,png_sha256=sha(OUT/f'{stem}.png'),CSV_sha256=sha(OUT/f'{stem}.csv'),dpi=300,minimum_font_pt=minimum,size_inches=size))
def forest(L,stem,title):
 d=pd.DataFrame(read(OUT/f'{L}_RESULTS.json')['contrasts']);d=d[(d.seed=='mean')&(d.metric=='PR_AUC')].copy();fig,ax=plt.subplots(figsize=(15,max(6,.5*len(d)+2)));yy=np.arange(len(d));ax.hlines(yy,d.ci95_low,d.ci95_high,color='#36596c');ax.scatter(d.estimate,yy,c='#36596c');ax.axvline(0,c='#888888',ls='--');ax.set_yticks(yy,[r.release.replace('_',' ')+' · '+model_label(r.model) for r in d.itertuples()]);ax.invert_yaxis();ax.set(xlabel='AP difference (arithmetic three-seed metric mean; 95% user-cluster CI)',title=title);fig.tight_layout(rect=[0,.06,1,.98]);save(fig,stem,d,'Exploratory, unadjusted CIs · Holm decisions for all endpoints are in the contrast CSV')
def main():
 forest('L1','figure_L1_restandardisation','L1: target-only unlabelled re-standardisation minus frozen zero-shot')
 forest('L2','figure_L2_drop_features','L2: removal of email count minus the full feature set')
 d=pd.DataFrame(read(OUT/'L3_RESULTS.json')['contrasts']);d=d[d.seed=='mean'];fig,ax=plt.subplots(figsize=(13,6))
 for n,g in d.groupby('model'):
  g=g.sort_values('lead');ax.plot(g.lead,g.estimate,'o-',label=model_label(n));ax.fill_between(g.lead,g.ci95_low,g.ci95_high,alpha=.15)
 ax.axhline(.5,c='#888888',ls='--');ax.set(xlabel='Calendar days before first malicious day',ylabel='Date-matched AUC',xticks=[1,3,5,7],title='L3: pre-event insider windows versus same-date non-insiders');ax.legend();fig.tight_layout(rect=[0,.08,1,1]);save(fig,'figure_L3_lead_time',d,'Exact eligible completed windows only · bands are 95% user-cluster CIs, not simultaneous intervals')
 d=pd.DataFrame(read(OUT/'L4_RESULTS.json')['contrasts']);d=d[d.seed=='mean'];fig,axes=plt.subplots(2,4,figsize=(19,10));strata=('all','malicious','benign','TP','FN','FP','TN')
 for ax,st in zip(axes.flat,strata):
  g=d[d.stratum==st].sort_values('k');ax.errorbar(g.k,g.estimate,yerr=np.array([g.estimate-g.ci95_low,g.ci95_high-g.estimate]),fmt='o-',color='#36596c');ax.axhline(0,c='#888888',ls='--');ax.set(title=st,xlabel='Number of routing flips',ylabel='Top minus random support loss',xticks=[1,2,3])
 axes.flat[-1].axis('off');fig.tight_layout(rect=[0,.06,1,.98]);save(fig,'figure_L4_route_interventions',d,'Three-seed means · 95% user-cluster CIs · downstream features fixed · 25 tree-matched random controls')
 d=pd.DataFrame(read(OUT/'L5_RESULTS.json')['contrasts']);fig,axes=plt.subplots(1,3,figsize=(19,6))
 for ax,metric in zip(axes,('PR_AUC','insiders_detected','noninsiders_flagged')):
  g=d[d.metric==metric];yy=np.arange(len(g));ax.hlines(yy,g.ci95_low,g.ci95_high);ax.scatter(g.estimate,yy);ax.axvline(0,c='#888888',ls='--');ax.set_yticks(yy,[model_label(r.model)+' · '+group_label(r.group) for r in g.itertuples()]);ax.set(title=metric_label(metric),xlabel='Averaged minus mean single-seed metric')
 fig.tight_layout(rect=[0,.09,1,1]);save(fig,'figure_L5_seed_averaging',d,'Ensemble thresholds fixed on clean development VALIDATION · 95% user-cluster CIs')
 d=pd.DataFrame(read(OUT/'L6_RESULTS.json')['points']).drop(columns=['descriptive_median_CI'],errors='ignore');fig,ax=plt.subplots(figsize=(15,6));labels=list(d.baseline.unique());xx=np.arange(3)
 for i,s in enumerate(SEEDS):
  g=d[d.seed==s].set_index('baseline').loc[labels];ax.errorbar(xx+(i-1)*.12,g.median_rho,yerr=np.array([g.median_rho-g.Q1_rho,g.Q3_rho-g.median_rho]),fmt='o',label=f'Seed {s}')
 ax.set(xticks=xx,xticklabels=['Fresh |input × gradient|','Plain |input|','Fully randomized IG'],ylabel='Spearman correlation with trained absolute IG ranking',title='L6: input structure and attribution magnitude ranks',ylim=(-1.05,1.05));ax.legend(loc='lower left');fig.tight_layout(rect=[0,.08,1,1]);save(fig,'figure_L6_attribution_baselines',d,'Error bars are window Q1–Q3 (IQR), not confidence intervals · no pass cutoff')
 d=pd.DataFrame(read(OUT/'L7_RESULTS.json')['points']);clean=d[d.PR_AUC.notna()].copy();clean['attack']=clean.condition.str.split(':').str[0];clean['epsilon']=clean.condition.str.split(':').str[1].astype(float);g=clean.groupby(['attack','epsilon','model'])[['AP_retention','insiders_detected','median_malicious_score_drop']].mean().reset_index();fig,axes=plt.subplots(2,4,figsize=(21,11))
 for j,a in enumerate(('uniform','source_targeted','TRACE_PGD','XGB_greedy')):
  for n,z in g[g.attack==a].groupby('model'):
   z=z.sort_values('epsilon');axes[0,j].plot(z.epsilon,z.AP_retention,'o-',label=model_label(n));axes[1,j].plot(z.epsilon,z.insiders_detected,'o-',label=model_label(n))
  axes[0,j].set(title={'uniform':'Uniform','source_targeted':'Source-targeted','TRACE_PGD':'TRACE PGD','XGB_greedy':'XGBoost greedy'}[a],xlabel='Epsilon',ylabel='Attacked AP / clean AP');axes[1,j].set(xlabel='Epsilon',ylabel='Insiders still detected / 25',ylim=(0,26))
 handles,labels=axes[0,0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',bbox_to_anchor=(.5,.037),ncol=2);fig.tight_layout(rect=[0,.10,1,1]);save(fig,'figure_L7_evasion',g,'Arithmetic three-seed metric means · matched perturbations across models · Holm contrasts in L7_CONTRASTS.csv')
 d=pd.DataFrame(read(OUT/'L8_RESULTS.json')['contrasts']);d=d[(d.seed=='mean')&(d.model.isin(['TA2','XGBoost_40']))];fig,axes=plt.subplots(1,2,figsize=(18,7))
 for ax,metric in zip(axes,('PR_AUC','insiders_detected')):
  g=d[d.metric==metric];yy=np.arange(len(g));ax.hlines(yy,g.ci95_low,g.ci95_high);ax.scatter(g.estimate,yy);ax.axvline(0,c='#888888',ls='--');ax.set_yticks(yy,[condition_label(r.condition)+' · '+model_label(r.model) for r in g.itertuples()]);ax.set(title=metric_label(metric),xlabel='Poisoned minus clean metric')
 fig.tight_layout(rect=[0,.08,1,1]);save(fig,'figure_L8_poisoning',d,'Actual whole-insider contamination may overshoot nominal rates · clean VALIDATION, 95% user-cluster CIs')
 dump(OUT/'FIGURE_RECEIPTS.json',dict(utc=utc(),figures=figures));print('EIGHT_FIGURES_WRITTEN',flush=True)
if __name__=='__main__':main()
