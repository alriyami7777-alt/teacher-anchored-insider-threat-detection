"""Verify every active v2 frozen input hash without touching any TEST data."""
from common import *
def verify_all(output='FULL_FROZEN_INPUT_VERIFICATION.json'):
    f=verify_original();checks=[]
    def checked(p,h):
        actual=sha(p);assert actual==h,'Frozen hash mismatch: '+str(p);checks.append(dict(path=str(p),sha256=actual))
    for e in f['implementation_files']:checked(e['path'],e['sha256'])
    checked(f['scoring_script']['path'],f['scoring_script']['sha256'])
    for e in f['models']:checked(e['checkpoint'],e['sha256'])
    pairs=[('DATA_MANIFEST.json','data_manifest_sha256'),('CONFIGS_FROZEN.json','configs_frozen_sha256'),('PARITY_GATE.json','parity_gate_sha256'),('ENVIRONMENT_PHASE2.json','environment_sha256'),('PARITY_GATE_VERIFICATION.json','parity_verification_sha256'),('MODELS_FROZEN_v1.json','supersedes_freeze_sha256')]
    for n,k in pairs:checked(OUT/n,f[k])
    for n,k in [('DEVELOPMENT_DAILY_SCALER.json','scaler_sha256'),('HOLDOUT_USERS.txt','holdout_list_sha256'),('DEVELOPMENT_USERS.txt','development_list_sha256')]:checked(OUT/'private'/n,f[k])
    checked(OUT.parent/'CHATGPT_PHASE1_REPORT.md',f['phase1_gate']['phase1_report_sha256'])
    data=json.loads((OUT/'DATA_MANIFEST.json').read_text())
    for name,spec in data['splits'].items():
        assert name in ('train','validation')
        for n,h in spec['files'].items():
            assert n.startswith(name+'_') and '/' not in n and '\\' not in n;checked(OUT/'private/tensors'/n,h)
    record=dict(utc=utc(),active_v2_hashes_verified=True,development_tensor_hashes_verified=True,checks=checks,test_data_opened=False,original_freeze_sha256=sha(OUT/'MODELS_FROZEN.json'))
    dump(P4/output,record);return record
if __name__=='__main__':print('Verified',len(verify_all()['checks']),'frozen inputs')
