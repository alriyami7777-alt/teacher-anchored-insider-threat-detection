from pathlib import Path
from datetime import datetime,timezone
import sys,json,math,hashlib,csv,shutil,ast,re
ROOT=Path(r'C:\PhD\07_Projects\r2_holdout')
OUT=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision\holdout')
PRIVATE=OUT/'private';STAGE=Path(__file__).resolve().parent
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def sanitize(x):
    if isinstance(x,float) and not math.isfinite(x):return 'NaN' if math.isnan(x) else ('Infinity' if x>0 else '-Infinity')
    if isinstance(x,dict):return {k:sanitize(v) for k,v in x.items()}
    if isinstance(x,list):return [sanitize(v) for v in x]
    return x
def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def dump(p,x):Path(p).write_text(json.dumps(sanitize(x),indent=2,allow_nan=False),encoding='utf-8')
# Normalize estimator NaN default *metadata* to a JSON string sentinel. Model files
# and fitting parameters are unchanged. This makes receipts RFC-compliant JSON.
targets=[OUT/'PARITY_GATE.json',OUT/'CONFIGS_FROZEN.json',OUT/'MODELS_FROZEN.json']
targets.extend(PRIVATE.glob('checkpoints_parity_v2/*/seed*/result.json'))
for p in targets:dump(p,load(p))
gate=load(OUT/'PARITY_GATE.json')
gate['estimator_nonfinite_default_metadata']='The XGBoost missing-value default is recorded as the string NaN; actual estimator defaults and all fitted model files are unchanged.'
dump(OUT/'PARITY_GATE.json',gate)
log=OUT/'TRAINING_LOG.csv'
with log.open(newline='',encoding='utf-8') as f:r=csv.DictReader(f);fields=r.fieldnames;rows=list(r)
for row in rows:
    if row.get('config'):row['config']=json.dumps(sanitize(json.loads(row['config'])),sort_keys=True,allow_nan=False)
with log.open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
env=load(OUT/'ENVIRONMENT_PHASE2.json');env['tabular_after_parity']=gate['correction']['runtime_environment'];dump(OUT/'ENVIRONMENT_PHASE2.json',env)
# Install the rerun guard and keep the shared workspace implementation in sync.
shutil.copyfile(STAGE/'phase2_parity_audit.py',ROOT/'phase2_parity_audit.py')
shutil.copyfile(Path(__file__),ROOT/'phase2_parity_verify.py')
for name in ('phase2_runtime.py','phase2_score_later.py','phase2_data.py'):shutil.copyfile(ROOT/name,STAGE/name)
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
import phase2_runtime as rt
import numpy as np
assert gate['status']=='PARITY_GATE_FIXED' and gate['P4']['only_scaler_refit_differs']
assert not (PRIVATE/'HOLDOUT_SCORING_CONSUMED.json').exists() and not (PRIVATE/'scoring_once').exists()
old=load(OUT/'MODELS_FROZEN_v1.json');freeze=load(OUT/'MODELS_FROZEN.json')
assert sha(OUT/'MODELS_FROZEN_v1.json')==sha(PRIVATE/'parity_v1/MODELS_FROZEN.json')
assert freeze['holdout_scored'] is False and freeze['test_read'] is False
assert len(freeze['models'])==33 and freeze['requested_successful_runs']==27
old_models={(r['model'],r['seed']):r for r in old['models']}
unchanged=0
for r in freeze['models']:
    assert sha(r['checkpoint'])==r['sha256']
    if r['model'] not in ('RF_40','XGBoost_40'):
        assert r['sha256']==old_models[r['model'],r['seed']]['sha256'];unchanged+=1
assert unchanged==27
superseded=[r for r in rows if r['status']=='SUPERSEDED_PARITY']
corrected=[r for r in rows if r['model'] in ('RF_40','XGBoost_40') and r['status']=='ok']
assert len(superseded)==6 and len(corrected)==6
manifest=load(OUT/'DATA_MANIFEST.json')
feature_error={}
for split in ('train','validation'):
    x=np.load(PRIVATE/f'tensors/{split}_X.npy',mmap_mode='r');a=np.load(PRIVATE/f'tensors/{split}_X40.npy',mmap_mode='r')
    error=0.
    for lo in range(0,len(x),8192):
        reference,names=rt.aggregate_common13_windows(np.asarray(x[lo:lo+8192]));error=max(error,float(np.max(np.abs(reference-a[lo:lo+len(reference)]))))
    assert error==0.;feature_error[split]=error
    for name,digest in manifest['splits'][split]['files'].items():assert sha(PRIVATE/'tensors'/name)==digest
    assert manifest['splits'][split]['files'][f'{split}_X.npy']==load(PRIVATE/'parity_v1/DATA_MANIFEST.json')['splits'][split]['files'][f'{split}_X.npy']
for name in ('phase2_runtime.py','phase2_score_later.py','phase2_data.py','phase2_parity_audit.py'):ast.parse((ROOT/name).read_text(encoding='utf-8'))
scoring=(ROOT/'phase2_score_later.py').read_text(encoding='utf-8')
assert "assert parity['status'] in ('PARITY_GATE_PASS','PARITY_GATE_FIXED')" in scoring
assert 'tt.append(rt.aggregate_common13_windows(xx[-1])[0])' in scoring
assert scoring.index("assert parity['status']") < scoring.index("users=(private/'HOLDOUT_USERS.txt')")
assert (OUT/'CHATGPT_PHASE2_REPORT.md').read_text(encoding='utf-8').rstrip().endswith('PARITY_GATE_FIXED')
for p in OUT.iterdir():
    if p.is_file() and p.suffix.lower() in ('.md','.json','.csv'):
        assert not re.search(r'\b[A-Z]{3}\d{4}\b',p.read_text(encoding='utf-8-sig')), 'Potential public user ID'
verification={'utc':datetime.now(timezone.utc).isoformat(),'status':'PARITY_GATE_FIXED','source_environment_for_this_check':{'python':sys.version,'numpy':np.__version__},'canonical_feature_max_abs_difference_in_neural_runtime_environment':feature_error,'corrected_tabular_models':6,'superseded_rows':6,'unchanged_neural_and_prerequisite_checkpoint_hashes':unchanged,'all_checkpoint_and_tensor_hashes_verified':True,'v1_freeze_preserved_exactly':True,'mandatory_scoring_guard_verified_statically':True,'scoring_script_executed':False,'holdout_scored':False,'test_read':False,'public_user_id_scan_pass':True}
dump(OUT/'PARITY_GATE_VERIFICATION.json',verification)
freeze['implementation_files']=[{'path':str(p),'sha256':sha(p)} for p in ROOT.rglob('*.py') if '__pycache__' not in str(p)]
freeze['parity_gate_sha256']=sha(OUT/'PARITY_GATE.json');freeze['configs_frozen_sha256']=sha(OUT/'CONFIGS_FROZEN.json');freeze['environment_sha256']=sha(OUT/'ENVIRONMENT_PHASE2.json');freeze['parity_verification_sha256']=sha(OUT/'PARITY_GATE_VERIFICATION.json')
freeze['scoring_script']={'path':str(ROOT/'phase2_score_later.py'),'sha256':sha(ROOT/'phase2_score_later.py'),'executed':False}
dump(OUT/'MODELS_FROZEN.json',freeze)
for e in freeze['implementation_files']:assert sha(e['path'])==e['sha256']
def reject_constant(s):raise ValueError(s)
for p in (OUT/'PARITY_GATE.json',OUT/'MODELS_FROZEN.json',OUT/'CONFIGS_FROZEN.json'):json.loads(p.read_text(),parse_constant=reject_constant)
print(json.dumps(verification,indent=2))
