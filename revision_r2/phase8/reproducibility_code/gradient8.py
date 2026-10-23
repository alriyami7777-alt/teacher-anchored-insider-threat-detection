from common8 import *
import argparse,subprocess
def one(name,seed,length):
 import torch
 from editor011_confirmation.models import live_odst_forward
 gate();dv=device()
 if length==30:
  root=R2/'phase6/private';s=read(root/f'training/r52_T30_F13/results/TA2_{seed}.json');data=root/'data/r52_T30_F13'
 else:s=oldspec(name,seed);data=HP/'tensors'
 model=loadmodel(s,dv)
 for p in model.parameters():p.requires_grad_(False)
 X=np.load(data/'validation_X.npy',mmap_mode='r');y=np.load(data/'validation_y.npy');pos=np.flatnonzero(y==1);neg=np.random.default_rng(42).choice(np.flatnonzero(y==0),len(pos),replace=False);take=np.sort(np.r_[pos,neg]);dest=PRIVATE/f'Q2/{name}_{seed}_T{length}';dest.mkdir(parents=True,exist_ok=True);np.save(dest/'development_selection.npy',take)
 mags=[];components=[]
 with torch.backends.cudnn.flags(enabled=False):
  for lo in range(0,len(take),64):
   ids=take[lo:lo+64];xb=torch.as_tensor(np.array(X[ids]),device=dv).requires_grad_(True);context,enc=model.encode_attention_h(xb);hidden=enc['hidden_states'];logit=model.linear_head(context).squeeze(-1) if name=='L1' else live_odst_forward(model.node_head,context)['logit'];grad=torch.autograd.grad(logit.sum(),(xb,hidden,context));mags.append(grad[0].detach().abs().mean(-1).cpu().numpy())
   for component,g in zip(('input','LSTM_output','attention_context'),grad):
    v=g.detach().cpu().numpy().reshape(len(ids),-1)
    for j,k in enumerate(ids):components.append(dict(model=name,seed=seed,length=length,development_row=int(k),positive=bool(y[k]),component=component,L2_norm=float(np.linalg.norm(v[j])),mean_absolute_gradient=float(np.abs(v[j]).mean()),zero_elements=int((v[j]==0).sum()),elements=v.shape[1],exact_zero_fraction=float((v[j]==0).mean())))
   time.sleep(.002)
 raw=np.concatenate(mags).astype(float);den=float(raw[:,-1].mean());norm=raw/den if den else np.full_like(raw,np.nan);curves=[]
 for j in range(length):curves.append(dict(model=name,seed=seed,length=length,day=j+1,windows=len(take),positive_windows=len(pos),final_day_mean_denominator=den,raw_mean=float(raw[:,j].mean()),raw_P5=float(np.quantile(raw[:,j],.05)),raw_P95=float(np.quantile(raw[:,j],.95)),normalized_mean=float(np.mean(norm[:,j])),normalized_P5=float(np.quantile(norm[:,j],.05)),normalized_P95=float(np.quantile(norm[:,j],.95))))
 np.savez_compressed(dest/'gradient_magnitudes.npz',raw=raw,normalized=norm);dump(dest/'RESULT.json',dict(utc=utc(),model=name,seed=seed,length=length,checkpoint_sha256=s['sha256'],selection_sha256=sha(dest/'development_selection.npy'),selection_rng=42,development_only=True,normalization_defined=den>0,curves=curves,components=components));print('Q2_COMPLETE',name,seed,length,flush=True)
def main():
 outcomes=[]
 for length,names in [(20,('TA2','F00','uniTA2','L1')),(30,('TA2',))]:
  for name in names:
   for s in OLD:
    dest=PRIVATE/f'Q2/{name}_{s}_T{length}';result=dest/'RESULT.json'
    if length==30 and not (R2/f'phase6/private/training/r52_T30_F13/results/TA2_{s}.json').exists():outcomes.append(dict(model=name,seed=s,length=length,status='SKIPPED',reason='30-day checkpoint unavailable'));continue
    if not result.exists():
     status('Q2_GRADIENTS',model=name,seed=s,length=length)
     with (PRIVATE/f'logs/Q2_{name}_{s}_T{length}.log').open('w',encoding='utf-8') as h:
      p=subprocess.Popen([str(PYTHON),'-X','utf8','-B',str(CODE/'gradient8.py'),'--model',name,'--seed',str(s),'--length',str(length)],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
      try:rc=p.wait(timeout=7200)
      except subprocess.TimeoutExpired:p.kill();p.wait();rc='TIMEOUT'
    else:rc=0
    outcomes.append(read(result)|dict(status='ok') if rc==0 and result.exists() else dict(model=name,seed=s,length=length,status='TIMEOUT' if rc=='TIMEOUT' else 'FAILED',reason=f'Exit {rc}'))
    dump(OUT/'Q2_OUTCOMES.json',outcomes)
 curves=[z for r in outcomes if r['status']=='ok' for z in r['curves']];components=[z for r in outcomes if r['status']=='ok' for z in r['components']];summ=[]
 for key,g in pd.DataFrame(components).groupby(['model','seed','length','component']):summ.append(dict(zip(('model','seed','length','component'),key))|dict(windows=len(g),mean_L2=float(g.L2_norm.mean()),median_L2=float(g.L2_norm.median()),P5_L2=float(g.L2_norm.quantile(.05)),P95_L2=float(g.L2_norm.quantile(.95)),mean_absolute_gradient=float(g.mean_absolute_gradient.mean()),exact_zero_fraction=float(g.zero_elements.sum()/g.elements.sum())))
 csv('Q2_GRADIENT_BY_DAY.csv',curves);csv('Q2_COMPONENT_GRADIENTS.csv',components);csv('Q2_COMPONENT_SUMMARY.csv',summ);dump(OUT/'Q2_RESULTS.json',dict(utc=utc(),outcomes=[{k:v for k,v in r.items() if k not in ('components','curves')} for r in outcomes],curves=curves,component_summary=summ,development_only=True));status('Q2_COMPLETE',successful=sum(r['status']=='ok' for r in outcomes))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--model');p.add_argument('--seed',type=int);p.add_argument('--length',type=int);a=p.parse_args();one(a.model,a.seed,a.length) if a.model else main()
