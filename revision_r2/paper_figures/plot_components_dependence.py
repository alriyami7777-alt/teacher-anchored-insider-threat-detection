# Regenerate the component-contrast and dependence/end-of-day figures with reader-facing names.
import csv, numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9})
# Component contrasts on r5.2 validation (point estimate = difference of 3-seed means; 95% paired user-cluster CI, 2,000 replicates)
rows=[('TRACE − task-only control',0.007518,0.000345,0.018250),
      ('Route-only variant − task-only control',0.002172,-0.000571,0.005753),
      ('TRACE − attention–linear reference',0.003961,-0.001371,0.011356)]
fig,ax=plt.subplots(figsize=(6.6,2.6),dpi=300)
for i,(n,m,lo,hi) in enumerate(rows):
    y=len(rows)-1-i; c='#1f5fa8' if lo>0 else '#7a8597'
    ax.plot([lo,hi],[y,y],color=c,lw=1.6); ax.plot(m,y,'o',color=c,ms=6)
    ax.text(hi+0.0006,y,f'{m:+.4f} [{lo:+.4f}, {hi:+.4f}]',va='center',fontsize=7.5)
ax.axvline(0,color='#444',lw=0.8); ax.set_yticks(range(len(rows))); ax.set_yticklabels([r[0] for r in rows][::-1])
ax.set_xlim(-0.004,0.028); ax.set_xlabel('Difference in PR-AUC on CERT r5.2 validation (95% user-cluster CI)')
for s in ['top','right']: ax.spines[s].set_visible(False)
ax.grid(axis='x',alpha=.25); fig.tight_layout(); fig.savefig('fig_component_contrasts.pdf',bbox_inches='tight')
fig.savefig('fig_component_contrasts.png',bbox_inches='tight')
# Dependence-aware and end-of-day views (non-overlapping offsets)
def series(fn,model):
    R=[r for r in csv.DictReader(open(fn)) if r['model']==model]
    x=np.arange(20); y=np.array([np.mean([float(r['PR_AUC']) for r in R if int(r['offset'])==i]) if any(int(r['offset'])==i and r['PR_AUC'] not in ('','nan') for r in R) else np.nan for i in x])
    pos=np.array([float(next(r['n_pos'] for r in R if int(r['offset'])==i)) for i in x]); return x,y,pos
x,comp,_=series('f8_EDITOR029_PARTA_ALL_OFFSETS.csv','TA2'); _,ep,pos=series('f8_EDITOR029_ENDPOINT_ALL_OFFSETS.csv','EP_FINAL')
zero=x[pos==0]
fig,ax=plt.subplots(figsize=(7.2,3.9),dpi=300)
ax.plot(x,comp,'o-',color='#1f5fa8',lw=1.5,ms=4,label='TRACE, completed-window labels')
ax.plot(x,ep,'s-',color='#c56a1a',lw=1.5,ms=4,label='Teacher-guided model trained on end-of-day labels')
ax.axhline(0.942842,color='#1f5fa8',ls='--',lw=1,alpha=.7,label='TRACE, all overlapping windows (0.9428)')
ax.axhline(0.651844,color='#c56a1a',ls='-.',lw=1,alpha=.7,label='End-of-day model, all windows (0.6518)')
ax.scatter(zero,np.full(len(zero),.035),marker='x',color='#b2182b',s=40,label='No positive window: PR-AUC undefined')
ax.set(xlim=(-.5,19.5),ylim=(-.015,1.035),xticks=x,xlabel='Non-overlapping offset',ylabel='Mean PR-AUC (seeds 42, 52, 62)')
ax.grid(alpha=.2); [ax.spines[s].set_visible(False) for s in ['top','right']]
ax.legend(loc='upper center',bbox_to_anchor=(.5,-.17),ncol=2,frameon=False,fontsize=7.5)
fig.tight_layout(); fig.savefig('fig_dependence_endpoint.pdf',bbox_inches='tight'); fig.savefig('fig_dependence_endpoint.png',bbox_inches='tight')
print(np.round(comp,3), np.round(ep,3), zero)
