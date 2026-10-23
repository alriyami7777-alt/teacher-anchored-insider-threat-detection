"""Prepare development-only references and invoke the recorded Option C adapter once."""
from common import *
import numpy as np,subprocess
def prepare():
    import phase2_runtime as rt
    import torch
    from score import predict
    from torch.utils.data import DataLoader,TensorDataset
    from xgboost import XGBClassifier
    original=verify_original();assert (P4/'SCORING_COMPLETE.json').exists()
    original_script=EXPL/'holdout_explanation_scoring.py';expected=(EXPL/'HOLDOUT_EXPLANATION_SCRIPT_HASH.txt').read_text().split()[0]
    assert sha(original_script)==expected
    old=json.loads((EXPL/'CODE_HASHES.json').read_text())
    for n in ('phase3_engine.py','run_phase3.py','holdout_explanation_scoring.py'):assert sha(EXPL/n)==old[n]
    data=rt.data();tr=data['train'];va=data['validation'];device=setup_torch()
    med=np.array([np.median(tr['X'][:,:,j]) for j in range(13)],np.float32);baseline=np.broadcast_to(med,(20,13)).copy();xbase=np.median(tr['X40'],axis=0).astype(np.float32)
    sys.path.insert(0,str(EXPL));from phase3_engine import aggregate40
    assert np.array_equal(aggregate40(np.array(va['X'][:1024])),va['X40'][:1024])
    specs={(r['model'],r['seed']):r for r in original['models']};spreads={n:{} for n in ('TA2','XGBoost_40')}
    for seed in SEEDS:
        m=rt.load_model('TA2',seed,device);loader=DataLoader(TensorDataset(torch.from_numpy(va['X'])),batch_size=1024,shuffle=False,num_workers=0);z=rt.logits(m,loader,device);spreads['TA2'][str(seed)]=float(z.astype(np.float64).std());del m
        m=XGBClassifier();m.load_model(specs['XGBoost_40',seed]['checkpoint']);m.set_params(n_jobs=2);z=m.predict(va['X40'],output_margin=True);spreads['XGBoost_40'][str(seed)]=float(z.astype(np.float64).std());del m
    refs=dict(reference_population='phase2_non_holdout_train',spread_population='phase2_validation_non_holdout',shared_scaled_coordinates_across_seeds=True,holdout_X_uses_this_scaler_sha256=original['scaler_sha256'],TA2_baseline_sequence=baseline.tolist(),XGBoost_summary_medians=xbase.tolist(),validation_logit_sd=spreads,median_definition='median over all standardized DEVELOPMENT TRAIN window-day rows per raw feature, broadcast over 20 days; 40 summary medians over TRAIN windows')
    refpath=PRIVATE/'EXPLANATION_DEVELOPMENT_REFERENCES.json';dump(refpath,refs)
    cohort=PRIVATE/'HOLDOUT_COHORT.npz';receipt=json.loads((P4/'HOLDOUT_BUILD_RECEIPT.json').read_text());assert sha(cohort)==receipt['cohort_sha256']
    manifest=dict(release='r5.2',partition='HOLDOUT',scoring_authorised=True,evaluation_periods=['train','validation'],test_sealed=True,cohort=dict(path=str(cohort),sha256=sha(cohort),scaler_sha256=original['scaler_sha256']),references=dict(path=str(refpath),sha256=sha(refpath)),models={family:{str(seed):dict(path=specs[family,seed]['checkpoint'],sha256=specs[family,seed]['sha256'],training_population='phase2_non_holdout_train') for seed in SEEDS} for family in ('TA2','XGBoost_40')})
    mp=PRIVATE/'HOLDOUT_EXPLANATION_MANIFEST.json';dump(mp,manifest)
    record=dict(utc=utc(),original_script_sha256=expected,original_script_verified=True,adapted_script=str(CODE/'holdout_explanation_option_c.py'),adapted_script_sha256=sha(CODE/'holdout_explanation_option_c.py'),changes=['Use v2 manifest and PARITY_GATE_FIXED in place of obsolete Phase 2 report final marker','Use the isolated Phase 2 TA2 loader while retaining frozen tree-output and logit explanation calculations','Enforce explicit TRAIN + VALIDATION cohort and original one-pass scoring receipt','Correct the inherited validation-only figure title to HOLDOUT TRAIN + VALIDATION','Retain original explanation engine, sampling RNG, all 50 IG integration intervals, 200 random interventions, bootstrap and output logic'],manifest_sha256=sha(mp),numerical_engine_sha256=sha(EXPL/'phase3_engine.py'),runner_sha256=sha(EXPL/'run_phase3.py'),output=str(EXPL/'holdout'))
    dump(P4/'EXPLANATION_ADAPTER_RECEIPT.json',record)
    assert not (EXPL/'holdout').exists()
    with (PRIVATE/'HOLDOUT_EXPLANATION_CONSUMED.json').open('x') as f:json.dump(dict(utc=utc(),adapter_sha256=record['adapted_script_sha256'],manifest_sha256=sha(mp),no_reruns=True),f)
    status('EXPLANATION_RUNNING')
    return subprocess.call([sys.executable,'-B',str(CODE/'holdout_explanation_option_c.py'),'--manifest',str(mp),'--manifest-sha256',sha(mp),'--execute-authorised-holdout-scoring','--output',str(EXPL/'holdout')],cwd=CODE,creationflags=subprocess.CREATE_NO_WINDOW)
if __name__=='__main__':sys.exit(prepare())
