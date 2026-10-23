from common8 import *
import ast
def main():
 import torch
 from sklearn.metrics import roc_auc_score
 from scipy.stats import spearmanr
 from editor011_confirmation.models import live_odst_forward
 from q3_routes8 import bootstrap_auc
 from randomization8 import final_ig,correlations
 gate();torch.set_num_threads(2);checks={};details={}
 for p in CODE.glob('*.py'):ast.parse(p.read_text())
 checks['all_scripts_parse']=True;dv=torch.device('cpu');X=np.array(np.load(HP/'tensors/validation_X.npy',mmap_mode='r')[:2]);model=loadmodel(oldspec('TA2',42),dv)
 for p in model.parameters():p.requires_grad_(False)
 x=torch.as_tensor(X).requires_grad_(True);context,enc=model.encode_attention_h(x);logit=live_odst_forward(model.node_head,context)['logit'];grads=torch.autograd.grad(logit.sum(),(x,enc['hidden_states'],context));checks['input_hidden_context_gradients_connected']=all(torch.isfinite(g).all().item() and g.abs().sum().item()>0 for g in grads)
 yy=np.array([1,0,1,0,0,1]);pp=np.array([.9,.9,.6,.4,.4,.1]);uu=np.array([0,1,0,1,2,2]);cc=np.array([[1,1,1],[2,0,1],[0,1,2]]);checks['weighted_tied_AUC_matches_sklearn']=bool(np.allclose(bootstrap_auc(yy,pp,uu,cc),[roc_auc_score(yy,pp,sample_weight=c[uu]) for c in cc]))
 a=np.array([[1,1,3,4],[0,0,0,0],[1,2,3,4]],float);b=np.array([[1,2,2,4],[1,2,3,4],[4,3,2,1]],float);rho=correlations(a,b);checks['Spearman_ties_and_constant_vectors']=np.isclose(rho[0],spearmanr(a[0],b[0]).statistic) and np.isnan(rho[1]) and np.isclose(rho[2],-1.)
 sys.path.insert(0,str(R2/'explanation'));from phase3_engine import integrated_gradients
 class Forward:
  device=dv
  def __call__(self,x):
   out=rt.student_forward(model,x);return torch.cat((out['tree_outputs'],out['logit'][:,None]),1)
 baseline=np.array(read(P4P/'EXPLANATION_DEVELOPMENT_REFERENCES.json')['TA2_baseline_sequence'],np.float32);full=integrated_gradients(Forward(),X,baseline);simple=final_ig(model,X,baseline,dv);err=float(np.max(np.abs(full[0][:,-1]-simple[0])));details['IG_final_only_vs_original_engine_max_abs_error']=err;checks['exact_final_logit_IG_algorithm']=err<1e-5
 train=np.array(np.load(HP/'tensors/train_X.npy',mmap_mode='r')[:16]);values=[]
 with torch.inference_mode():
  for seed in OLD:values.append(rt.student_forward(loadmodel(oldspec('T-OPT',seed),dv),torch.as_tensor(train))['logit'].numpy())
 cache=np.load(HP/'teacher_cache/bi_train_ensemble_logits.npy')[:16];error=float(np.max(np.abs(np.mean(values,0)-cache)));details['original_consensus_cache_development_CPU_parity_max_error']=error;checks['consensus_cache_is_original_three_teachers']=error<5e-4
 f=read(OUT/'Q5_INPUT_MONITOR_FROZEN.json');checks['Q5_all_52_unlabelled_feature_rows']=len(f['features'])==52 and not f['target_labels_read'];checks['Q5_histogram_mass_and_flags']=all(sum(r['reference_bin_counts'])==r['reference_daily_rows'] and sum(r['target_bin_counts'])==r['target_daily_rows'] for r in f['features']) and all(r['flagged']==(r['max_absolute_standardized_feature_shift']>.25 or r['max_PSI']>.25) for r in f['flags'])
 result=dict(utc=utc(),all_checks_passed=all(checks.values()),checks=checks,details=details,development_only=True,device='CPU');dump(OUT/'DEVELOPMENT_NUMERICAL_VERIFICATION.json',result);assert result['all_checks_passed'],checks;print('DEVELOPMENT_NUMERICAL_VERIFICATION_PASS',len(checks),flush=True)
if __name__=='__main__':main()
