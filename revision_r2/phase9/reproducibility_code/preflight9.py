from common9 import *
import ast
from stats9 import selfcheck
from attacks9 import rebuild,tensor_rebuild
from routes9 import response
def main():
 import torch
 checks={}
 for p in CODE.glob('*.py'):ast.parse(p.read_text())
 checks['all_code_parses']=True;checks['weighted_AP_ties_and_original_aggregation']=selfcheck()
 rng=np.random.default_rng(42);x=rng.normal(size=(16,20,13)).astype(np.float32);keep=read(OUT/'L2_FEATURES_FROZEN.json')['indices'];full,names=aggregate(x);sub,subnames=aggregate(x[:,:,keep],keep);assert np.array_equal(sub,full[:,[i for i,n in enumerate(names) if not n.startswith('email_count_')]]);checks['reduced_aggregation_exact_retained_columns']=True
 raw=np.abs(rng.normal(size=(4,20,13)));raw[:,:,0]=raw[:,:,1:6].sum(-1);mask=rng.random((4,20))>.5;c=raw[:,:,1:6]*.75;a=rebuild(raw,c,mask);b=tensor_rebuild(torch.tensor(raw),torch.tensor(c),torch.tensor(mask));assert np.allclose(a,b.numpy());assert np.array_equal(a[~mask],raw[~mask]);checks['attacker_derived_features_numpy_torch_parity']=True
 # CPU model route formula and differentiable attacker on development inputs only; no concurrent GPU allocation.
 model=loadmodel(oldspec('TA2',42),torch.device('cpu'));dev=np.load(HP/'tensors/validation_X.npy',mmap_mode='r');xx=torch.tensor(np.array(dev[:4]),requires_grad=True);out=rt.student_forward(model,xx);leaf=np.concatenate([l.leaf_responses.detach().numpy()[:,:,0] for l in model.node_head.layers]);a=response(out['choices'].detach().numpy(),leaf);assert np.max(abs(a-out['tree_outputs'].detach().numpy()))<2e-5;checks['route_reconstruction_development_parity']=True
 s=scaler()['development'];mu=torch.tensor(s['mean'],dtype=torch.float32);sd=torch.tensor(s['scale'],dtype=torch.float32);rr=xx.detach()*sd+mu;cc=rr[:,:,1:6].clamp_min(0).detach().requires_grad_(True);mm=torch.ones((4,20),dtype=torch.bool);z=(tensor_rebuild(rr,cc,mm)-mu)/sd;g=torch.autograd.grad(rt.student_forward(model,z)['logit'].sum(),cc)[0];assert torch.isfinite(g).all() and g.abs().sum()>0;checks['PGD_count_gradient_connected_development_only']=True
 checks['all_clean_validation_labels_unchanged']=all(np.array_equal(np.load(PRIVATE/f'data/{c}/validation_y.npy'),np.load(HP/'tensors/validation_y.npy')) for c in CONFIGS)
 checks['frozen_feature_rule_only_email']=read(OUT/'L2_FEATURES_FROZEN.json')['dropped']==['email_count']
 checks['target_restandardisation_no_labels']=all(not z['labels_read'] for z in read(OUT/'L1_TARGET_SCALERS_FROZEN.json')['releases'].values())
 dump(OUT/'DEVELOPMENT_NUMERICAL_VERIFICATION.json',dict(utc=utc(),all_checks_passed=all(checks.values()),checks=checks));assert all(checks.values());print('DEVELOPMENT_SELFCHECK_COMPLETE',checks,flush=True)
if __name__=='__main__':main()
