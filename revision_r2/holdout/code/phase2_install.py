from pathlib import Path
import hashlib,json,shutil,ast,sys,datetime,os
ROOT=Path(r'C:\PhD\07_Projects\r2_holdout')
OUT=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision\holdout')
STAGE=Path(__file__).resolve().parent
FEAS=Path(r'C:\PhD\07_Projects\cert-r42-feasibility\scripts')
files=['phase2_runtime.py','phase2_worker.py','phase2_score_later.py','phase2_data.py','phase2_prepare.py','phase2_inspect.py','phase2_install.py']
for name in files:
    ast.parse((STAGE/name).read_text(encoding='utf-8-sig'),filename=name)
    shutil.copyfile(STAGE/name,ROOT/name)
expected={'prototype_v3_node/architecture.py':'9867b0c266f3b735d138e2d8d53f0d3f5c5c644e25302c10c25e2f4677560abd','prototype_v3_node/odst.py':'95764ce80a7c80529108d8d6b72f6bd06896c39d065f7e475c12dce8421417bb','models/sequence_ensemble.py':'43f16bce9c09305c7578d319dadf4c23c6c18cbe70fd7dcc1fda0114c86d6475'}
sources=[]
for rel,digest in expected.items():
    content=(FEAS/rel).read_bytes()
    assert hashlib.sha256(content).hexdigest()==digest, 'Producing-source hash mismatch'
    target=ROOT/'producing_model'/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
    init=target.parent/'__init__.py'
    if not init.exists():init.write_text('')
    sources.append({'source':str(FEAS/rel),'copied_to':str(target),'sha256':digest})
(ROOT/'PRODUCING_MODEL_SOURCES.json').write_text(json.dumps(sources,indent=2))
# CPU-only checks: no CUDA availability query, GPU work, training, or data inference.
os.environ['PYTHONDONTWRITEBYTECODE']='1'
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
import phase2_runtime as rt
import torch,numpy as np
from editor012_rescue.losses import route_consistency_loss,et1_ensemble_logit_mse
checks=[]
for uni in (False,True):
    m=rt.build('odst',uni);m.eval();x=torch.linspace(-1.,1.,3*20*13).reshape(3,20,13)
    with torch.no_grad():
        z,_=m.encode_attention_h(x)
        a=rt.student_forward(m,x)['logit'];b=m.node_head(z)[0]
    assert z.shape==(3,128) and a.shape==(3,) and torch.allclose(a,b,atol=1e-6,rtol=1e-6)
    assert m.lstm.bidirectional is (not uni)
    assert m.lstm.hidden_size==(128 if uni else 64)
    m.apply_frozen_node_trainability()
    assert not any(p.requires_grad for p in m.lstm.parameters())
    assert not any(p.requires_grad for p in m.attention.parameters())
    rt.build_teacher_optimizer(m)
    rt.enable_student(m);opt=rt.build_student_optimizer(m)
    assert [g['lr'] for g in opt.param_groups]==[3e-5,3e-5,1e-3]
    checks.append({'uni':uni,'representation_shape':[3,128],'live_routing_matches_producing_node':True,'optimizer_groups_match':True})
s=torch.tensor([-.7,.3,1.2],requires_grad=True);t=torch.tensor([.1,-.2,1.1])
assert torch.equal(et1_ensemble_logit_mse(s,t),((s-t)**2).mean())
p=torch.tensor([.2,.7]);q=torch.tensor([.4,.6],requires_grad=True);eps=1e-6
expected_loss=(p*torch.log((p+eps)/(q+eps))+(1-p)*torch.log((1-p+eps)/(1-q+eps))).mean()
assert torch.equal(route_consistency_loss(q,p),expected_loss)
manifest=json.loads((OUT/'DATA_MANIFEST.json').read_text())
assert manifest['sanity_mismatches']==0
bundle=rt.data()
configs={f'{name}/seed{seed}':rt.recipe(name,seed,bundle) for name in ('AL_PRECURSOR','T-OPT','F00','TA2','XGBoost_40','RF_40','L1','F10','uniAL_PRECURSOR','uniT-OPT','uniTA2') for seed in rt.SEEDS}
(OUT/'CONFIGS_FROZEN.json').write_text(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'configs':configs},indent=2))
import importlib.metadata as metadata
versions={name:metadata.version(name) for name in ('numpy','pandas','pyarrow','torch','scikit-learn','xgboost','joblib')}
(OUT/'ENVIRONMENT_PHASE2.json').write_text(json.dumps({'python':sys.version,'executable':sys.executable,'packages':versions},indent=2))
dev=set((OUT/'private/DEVELOPMENT_USERS.txt').read_text().splitlines());ho=set((OUT/'private/HOLDOUT_USERS.txt').read_text().splitlines())
assert len(dev)==1500 and len(ho)==500 and not dev&ho
for split in ('train','validation'):
    d=OUT/'private/tensors'
    with np.load(d/f'{split}_metadata.npz',allow_pickle=False) as z:
        assert set(z['user'])==dev and not set(z['user'])&ho
    for name,digest in manifest['splits'][split]['files'].items():assert rt.sha(d/name)==digest
assert rt.sha(ROOT/'PREREGISTRATION_BASELINE.md') in (OUT/'PREREGISTRATION_R2_HOLDOUT.md').read_text()
record={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'CPU_only':True,'synthetic_model_checks':checks,'loss_equation_parity':True,'development_user_exclusion_verified':True,'tensor_hashes_verified':True,'pre_split_preregistration_hash_verified':True,'producing_source_hashes_verified':True,'scoring_script_executed':False,'scoring_script_sha256':rt.sha(ROOT/'phase2_score_later.py')}
record['configs_frozen_sha256']=rt.sha(OUT/'CONFIGS_FROZEN.json')
(OUT/'PREFLIGHT_CHECKS.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record,indent=2))
