from common9 import *
def main():
 gate();rows=[]
 for c in CONFIGS:
  for n in ('AL_PRECURSOR','T-OPT','TA2','XGBoost_40'):
   for s in SEEDS:
    p=PRIVATE/f'training/{c}/results/{n}_{s}.json';key=f'train_{c}_{n}_{s}'
    if p.exists():r=read(p)
    else:
     needed=[] if n in ('AL_PRECURSOR','XGBoost_40') else [PRIVATE/f'training/{c}/results/AL_PRECURSOR_{s}.json'] if n=='T-OPT' else [PRIVATE/f'training/{c}/results/T-OPT_{k}.json' for k in SEEDS]
     if not all(v.exists() for v in needed):r=dict(condition=c,model=n,seed=s,status='SKIPPED',reason='Missing condition-specific prerequisite')
     else:
      status('TRAINING',condition=c,model=n,seed=s);o=child('train9.py',['--config',c,'--model',n,'--seed',s],key);r=read(p) if o['status']=='ok' and p.exists() else dict(condition=c,model=n,seed=s,status=o['status'],reason=o)
    rows.append(r);dump(OUT/'TRAINING_OUTCOMES.json',rows)
 dump(OUT/'TRAINING_COMPLETE.json',dict(utc=utc(),planned=60,successful=sum(r['status']=='ok' for r in rows),outcomes=rows));status('TRAINING_FINISHED',successful=sum(r['status']=='ok' for r in rows))
if __name__=='__main__':main()
