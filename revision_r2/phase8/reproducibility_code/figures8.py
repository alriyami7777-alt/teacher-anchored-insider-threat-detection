from common8 import *
os.environ['MPLCONFIGDIR']=str(PRIVATE/'matplotlib_cache')
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.text import Text
plt.rcParams.update({'font.size':12,'axes.labelsize':12,'axes.titlesize':14,'xtick.labelsize':12,'ytick.labelsize':12,'legend.fontsize':12,'figure.titlesize':16,'axes.spines.top':False,'axes.spines.right':False})
COLORS=['#243d4d','#a16b3b','#6f8fa6'];receipts=[]
def save(fig,stem,rows,caption):
 fig.text(.5,.012,caption,ha='center',fontsize=12);fig.canvas.draw();fonts=[t.get_fontsize() for t in fig.findobj(Text) if t.get_text()];assert min(fonts)>=12;fig.savefig(OUT/f'{stem}.png',dpi=300);csv(f'{stem}.csv',rows);receipts.append(dict(stem=stem,png_sha256=sha(OUT/f'{stem}.png'),CSV_sha256=sha(OUT/f'{stem}.csv'),dpi=300,minimum_font_pt=min(fonts),size_inches=fig.get_size_inches()));plt.close(fig)
def main():
 if (OUT/'Q1_RESULTS.json').exists():
  r=read(OUT/'Q1_RESULTS.json');d=pd.DataFrame(r['per_seed_all_views']);d=d[d.view=='pooled_completed'];fig,axes=plt.subplots(1,2,figsize=(16,7));names=['TA2','F00','XGBoost_40']
  for name,color,label in zip(names,COLORS,['TRACE','F00','XGBoost-40']):
   g=d[d.model==name].sort_values('seed');axes[0].plot(g.seed,g.PR_AUC,color=color,lw=1,label=label)
   for seed,marker in [(OLD,'o'),(NEW,'s')]:
    z=g[g.seed.isin(seed)];axes[0].scatter(z.seed,z.PR_AUC,color=color,marker=marker,s=50)
  axes[0].set(title='(a) Frozen per-seed AP',xlabel='Model seed (circles: original; squares: new)',ylabel='Average precision (PR-AUC)',xticks=ALL);axes[0].legend()
  contrasts=[z for z in r['contrasts'] if z['contrast']=='TRACE minus F00' and z['status']=='ok'];ys=np.arange(len(contrasts))
  for j,z in enumerate(contrasts):axes[1].plot([z['ci95_low'],z['ci95_high']],[j,j],color='#243d4d');axes[1].scatter(z['estimate'],j,color='#243d4d',s=30)
  axes[1].axvline(0,color='#888888',ls='--');axes[1].set(yticks=ys,yticklabels=[str(z['seed']) for z in contrasts],xlabel='AP difference (paired 95% user-cluster CI)',ylabel='Seed or fixed seed group',title='(b) TRACE minus task-only F00');axes[1].invert_yaxis();fig.tight_layout(rect=[0,.07,1,1]);save(fig,'figure_Q1_more_seeds',[z|dict(panel='per_seed') for z in d.to_dict('records')]+[z|dict(panel='contrast') for z in r['contrasts']],'500 unseen users · 2,000 paired user replicates · all outcomes and unadjusted CIs retained')
 if (OUT/'Q2_RESULTS.json').exists():
  r=read(OUT/'Q2_RESULTS.json');d=pd.DataFrame(r['curves']);fig,axes=plt.subplots(2,3,figsize=(18,11));groups=[('TA2',20,'TRACE, 20 days'),('F00',20,'F00, 20 days'),('uniTA2',20,'Unidirectional TRACE'),('L1',20,'Attention-linear L1'),('TA2',30,'TRACE, 30 days')]
  for ax,(name,length,title) in zip(axes.flat,groups):
   for color,seed in zip(COLORS,OLD):
    g=d[(d.model==name)&(d.length==length)&(d.seed==seed)].sort_values('day')
    if not len(g):continue
    ax.plot(g.day,g.normalized_mean,color=color,label=f'Seed {seed}');ax.fill_between(g.day,g.normalized_P5,g.normalized_P95,color=color,alpha=.10)
   ax.set(title=title,xlabel='Input timestep',ylabel='|logit gradient| / mean final-day magnitude');ax.legend();ax.grid(alpha=.15)
  fig.delaxes(axes.flat[-1]);fig.tight_layout(rect=[0,.07,1,1]);save(fig,'figure_Q2_gradient_by_day',r['curves'],'Development VALIDATION only · all positives plus equal sampled negatives · bands: window 5–95% range')
 if (OUT/'Q3_RESULTS.json').exists():
  r=read(OUT/'Q3_RESULTS.json');fig,axes=plt.subplots(2,1,figsize=(16,10));data=[]
  for ax,name in zip(axes,('TA2','F00')):
   rows=[z for z in r['leaf_occupancy'] if z['model']==name and z['seed']==42];mat=np.full((8,16),np.nan)
   for z in rows:mat[z['tree']-1,z['leaf']]=z['occupancy_share']
   im=ax.imshow(mat,cmap='Blues',vmin=0,vmax=1,aspect='auto');ax.set(title=f'{"TRACE" if name=="TA2" else "F00"} · seed 42',xlabel='Highest-probability leaf index',ylabel='Tree (layer order)',xticks=np.arange(16),yticks=np.arange(8),yticklabels=np.arange(1,9))
   for j in range(8):
    for k in range(16):
     if np.isfinite(mat[j,k]):ax.text(k,j,f'{100*mat[j,k]:.0f}',ha='center',va='center',fontsize=12,color='white' if mat[j,k]>.5 else '#243d4d')
   fig.colorbar(im,ax=ax,label='Argmax occupancy share');data.extend(rows)
  fig.tight_layout(rect=[0,.07,1,1]);save(fig,'figure_Q3_leaf_occupancy',data,'All permitted HOLDOUT windows · rounded integer percentages (CSV: full precision) · ties use lowest leaf index')
 if (OUT/'Q4_RESULTS.json').exists():
  r=read(OUT/'Q4_RESULTS.json');d=pd.DataFrame(r['correlations']);d=d[d.seed.astype(str)!='pooled_three_seed_windows_descriptive'];fig,axes=plt.subplots(2,2,figsize=(16,11));stages=['head','head_attention','all'];titles={'IG_signed_features':'Signed IG feature ranks','IG_absolute_feature_shares':'Absolute IG feature ranks','attention':'Attention ranks','tree_centred_contributions':'Reference-centred tree ranks'}
  for ax,(component,title) in zip(axes.flat,titles.items()):
   for j,(color,seed) in enumerate(zip(COLORS,OLD)):
    g=d[(d.component==component)&(d.seed==seed)].set_index('stage').reindex(stages);x=np.arange(3)+(j-1)*.12;ax.errorbar(x,g.median_rho,yerr=[g.median_rho-g.Q1_rho,g.Q3_rho-g.median_rho],fmt='o-',capsize=3,color=color,label=f'Seed {seed}')
   ax.axhline(0,color='#888888',ls=':');ax.set(title=title,xticks=range(3),xticklabels=['Head','Head + attention','All layers'],xlabel='Progressive parameter randomisation',ylabel='Spearman ρ: median and IQR',ylim=(-1.05,1.05));ax.legend()
  fig.tight_layout(rect=[0,.07,1,1]);save(fig,'figure_Q4_randomization',r['correlations'],'Same saved 2,344 windows · fixed randomisation seed 42 · head-only attention persistence is an expected control')
 if (OUT/'Q5_RESULTS.json').exists():
  r=read(OUT/'Q5_RESULTS.json');flags=r['flags'];fig,axes=plt.subplots(1,2,figsize=(16,6.5));labels=[z['release'].replace('_',' ') for z in flags]
  for ax,col,title in zip(axes,('max_absolute_standardized_feature_shift','max_PSI'),('Maximum absolute feature mean shift','Maximum feature PSI')):
   vals=[z[col] for z in flags];ax.barh(labels,vals,color=['#a16b3b' if z['flagged'] else '#6f8fa6' for z in flags]);ax.axvline(.25,color='#243d4d',ls='--',label='Frozen cutoff 0.25');ax.set(title=title,xlabel='Dimensionless shift statistic',ylabel='Frozen input cohort');ax.legend()
   for j,v in enumerate(vals):ax.text(max(v+.02*max(vals),.25+.03*max(vals)) if v<=.25 else v+.02*max(vals),j,f'{v:.3f}',va='center',fontsize=12)
   ax.set_xlim(0,max(max(vals)*1.22,.35))
  fig.tight_layout(rect=[0,.07,1,1]);save(fig,'figure_Q5_label_free_monitor',flags,'No target labels in monitor · reference: 1,500 r5.2 development users TRAIN · flag if either statistic > 0.25')
 dump(OUT/'FIGURE_RECEIPTS.json',dict(utc=utc(),figures=receipts));status('FIGURES_COMPLETE',figures=len(receipts))
if __name__=='__main__':main()
