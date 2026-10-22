# Fig: mean |IG| of the final logit per raw feature (summed over 20 days), malicious vs benign, mean of seeds 42/52/62; plus feature x tree heatmap (malicious).
import pandas as pd, numpy as np, matplotlib.pyplot as plt, sys
d=pd.read_csv(sys.argv[1]); out=sys.argv[2]
lab={'total_events':'Total events','logon_count':'Logon count','device_count':'Device count','file_count':'File count','email_count':'E-mail count','http_count':'HTTP count','active_duration_minutes':'Active duration','is_active_day':'Active day','has_logon_activity':'Logon (yes/no)','has_device_activity':'Device (yes/no)','has_file_activity':'File (yes/no)','has_email_activity':'E-mail (yes/no)','has_http_activity':'HTTP (yes/no)'}
f=d[d.target=='final_logit'].groupby(['stratum','feature']).mean_abs_ig_sum_days.mean().unstack(0)
f=f.sort_values('malicious')
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':7})
fig,(a,b)=plt.subplots(1,2,figsize=(7.1,2.9),dpi=300,gridspec_kw={'width_ratios':[1,1.35]})
y=np.arange(len(f)); h=0.38
a.barh(y+h/2,f['malicious'],h,color='#b23a3a',label='Malicious windows')
a.barh(y-h/2,f['benign'],h,color='#9aa0a8',label='Benign windows')
a.set_yticks(y); a.set_yticklabels([lab[k] for k in f.index]); a.set_xlabel('Mean |IG| of final logit (sum over 20 days)')
a.legend(frameon=False,loc='lower right',fontsize=6); [a.spines[s].set_visible(False) for s in ['top','right']]
a.set_title('(a) Feature attribution, final logit',fontsize=7.5,loc='left')
t=d[(d.stratum=='malicious')&(d.target.str.startswith('tree_'))].groupby(['feature','target']).mean_abs_ig_sum_days.mean().unstack()
t=t.loc[f.index[::-1]][[f'tree_{i}' for i in range(1,9)]]
im=b.imshow(t.values,aspect='auto',cmap='Reds')
b.set_yticks(range(len(t))); b.set_yticklabels([lab[k] for k in t.index]); b.set_xticks(range(8)); b.set_xticklabels([f'T{i}' for i in range(1,9)])
b.set_xlabel('ODST tree (T1–T4: layer 1; T5–T8: layer 2)'); b.set_title('(b) Per-tree attribution, malicious windows',fontsize=7.5,loc='left')
c=fig.colorbar(im,ax=b,fraction=0.04,pad=0.02); c.ax.tick_params(labelsize=6); c.set_label('Mean |IG|',fontsize=6.5)
fig.tight_layout(); fig.savefig(out,bbox_inches='tight')
