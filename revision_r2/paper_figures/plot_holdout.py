# Figure: unseen-user (500 held-out CERT r5.2 users) PR-AUC, 3-seed mean with seed dots.
import pandas as pd, matplotlib.pyplot as plt, sys
r=pd.read_csv(sys.argv[1]); out=sys.argv[2]
p=r[(r.view=='pooled_completed')]
name={'TA2':'TRACE (ours)','F10':'Guidance-only variant','F00':'Task-only control','T-OPT':'Optimised teacher',
'L1':'Attention–linear reference','uniTA2':'Unidirectional TRACE','uniT-OPT':'Unidirectional teacher','XGBoost_40':'XGBoost-40',
'LightGBM_40':'LightGBM-40','RF_40':'RF-40','BiLSTM_noAttn':'Bi-LSTM (no attention)','BiGRU_Attn':'Bi-GRU + attention',
'TCN':'TCN','Transformer':'Transformer encoder','MLP':'MLP (260 inputs)','LSTM_AE':'LSTM autoencoder','IsolationForest':'Isolation Forest'}
fam={'TA2':'ours','F10':'abl','F00':'abl','T-OPT':'abl','uniTA2':'abl','uniT-OPT':'abl','XGBoost_40':'tree','LightGBM_40':'tree','RF_40':'tree',
'L1':'nn','BiLSTM_noAttn':'nn','BiGRU_Attn':'nn','TCN':'nn','Transformer':'nn','MLP':'nn','LSTM_AE':'un','IsolationForest':'un'}
col={'ours':'#1f5fa8','abl':'#8fb3dc','nn':'#9aa0a8','tree':'#c98a2b','un':'#c9ccd1'}
mean=p[p.seed=='mean'].set_index('model').AP.sort_values()
seeds=p[p.seed!='mean']
prev=p.prevalence.iloc[0]
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':8})
fig,ax=plt.subplots(figsize=(3.5,4.3),dpi=300)
for i,(m,v) in enumerate(mean.items()):
    ax.barh(i,v,color=col[fam[m]],height=0.7,edgecolor='none')
    s=seeds[seeds.model==m].AP.values
    ax.scatter(s,[i]*len(s),s=6,color='#222',zorder=3,linewidths=0)
    ax.text(max(v,s.max())+0.012,i,f'{v:.3f}',va='center',fontsize=6.5,fontweight='bold' if m=='TA2' else 'normal')
ax.set_yticks(range(len(mean))); ax.set_yticklabels([name[m] for m in mean.index],fontsize=7)
for t,m in zip(ax.get_yticklabels(),mean.index):
    if m=='TA2': t.set_fontweight('bold')
ax.axvline(prev,color='#b23a3a',lw=0.7,ls='--'); ax.text(prev+0.01,-1.1,f'prevalence {prev:.4f}',color='#b23a3a',fontsize=6)
ax.set_xlim(0,0.95); ax.set_ylim(-1.6,len(mean)-0.4); ax.set_xlabel('PR-AUC on 500 unseen users (3-seed mean; dots = seeds)',fontsize=7)
for s in ['top','right']: ax.spines[s].set_visible(False)
ax.grid(axis='x',color='#e5e5e5',lw=0.5); ax.set_axisbelow(True)
fig.tight_layout(); fig.savefig(out,bbox_inches='tight')
