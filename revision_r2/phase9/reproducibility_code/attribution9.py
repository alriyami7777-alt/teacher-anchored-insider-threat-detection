from common9 import *
from scipy.stats import rankdata
from stats9 import counts,interval
def correlations(a,b):
 a=rankdata(a,axis=1);b=rankdata(b,axis=1);a-=a.mean(1,keepdims=True);b-=b.mean(1,keepdims=True);den=np.linalg.norm(a,axis=1)*np.linalg.norm(b,axis=1);return np.divide((a*b).sum(1),den,out=np.full(len(a),np.nan),where=den>0)
def main():
 import torch
 gate();dv=device();selection=np.array(read(EXPL/'HOLDOUT_SELECTION.json')['selected_bundle_row_indices']);x=np.load(P4P/'HOLDOUT_COHORT.npz')['X'][selection];m=holdmeta();u=m['cluster'][selection];f=read(P8/'private/Q4/seed42/all/FROZEN_BEFORE_EXPLANATION.json');sp=oldspec('TA2',42)|dict(checkpoint=str(P8/'private/Q4/seed42/all/randomized_state.pt'),sha256=f['checkpoint_sha256']);model=loadmodel(sp,dv)
 assert f['initialization_population']=='development TRAIN only';lock=consume('L6_fresh_input_gradient',fresh_state_sha256=f['fresh_initialization_state_sha256']);grad=[]
 with torch.backends.cudnn.flags(enabled=False):
  for lo in range(0,len(x),128):
   xx=torch.as_tensor(x[lo:lo+128],device=dv).requires_grad_(True);g=torch.autograd.grad(rt.student_forward(model,xx)['logit'].sum(),xx)[0];grad.append((xx*g).abs().sum(1).detach().cpu().numpy());time.sleep(.002)
 fresh=np.concatenate(grad);plain=np.abs(x).sum(1);rows=[];values={};w=counts(500)
 for s in SEEDS:
  orig=np.abs(np.load(EXPL/f'ig_seed{s}.npz')['ig'][:,-1].astype(float)).sum(1);randomized=np.abs(np.load(P8/f'private/Q4/seed{s}/all/explanations.npz')['ig'].astype(float)).sum(1)
  for label,b in (('fresh_abs_input_gradient',fresh),('plain_abs_input',plain),('fully_randomized_IG',randomized)):
   v=correlations(orig,b);values[f'{s}_{label}']=v;valid=np.isfinite(v);rep=[]
   for wr in w:
    a=np.repeat(v[valid],wr[u[valid]].astype(int));rep.append(np.median(a) if len(a) else np.nan)
   rows.append(dict(seed=s,baseline=label,windows=len(v),valid_windows=int(valid.sum()),constant_or_undefined_windows=int((~valid).sum()),median_rho=float(np.nanmedian(v)),Q1_rho=float(np.nanquantile(v,.25)),Q3_rho=float(np.nanquantile(v,.75)),descriptive_median_CI=interval(rep,np.nanmedian(v))))
 np.savez_compressed(PRIVATE/'L6_CORRELATIONS.npz',**values,fresh_abs_input_gradient=fresh);csv('L6_BASELINE_CORRELATIONS.csv',rows);dump(OUT/'L6_RESULTS.json',dict(utc=utc(),points=rows,Holm_family_size=0,inference='descriptive; no null tests',fresh_state_reused_from_phase8=True,fresh_state_sha256=f['fresh_initialization_state_sha256']))
if __name__=='__main__':main()
