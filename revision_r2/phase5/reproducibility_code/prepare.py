from p5common import *
def main():
    import ast,torch,zipfile
    PRIVATE.mkdir(parents=True,exist_ok=True)
    assert not (OUT/'MODELS_AND_METHODS_FROZEN_PHASE5.json').exists()
    a=json.loads((OUT/'AMENDMENT3_RECEIPT.json').read_text(encoding='utf-8'));pr=(R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md').read_bytes();assert hashlib.sha256(pr[:a['previous_bytes']]).hexdigest()==a['previous_sha256'];assert hashlib.sha256(pr[a['previous_bytes']:a['previous_bytes']+a['section_bytes']]).hexdigest()==a['sha256']
    p4f=json.loads((P4/'MODELS_FROZEN_PHASE4.json').read_text(encoding='utf-8'));assert a['previous_sha256']==p4f['preregistration_sha256']
    p4.verify_original()
    for n,h in p4f['files'].items():assert sha(ROOT/'phase4'/n)==h
    dev=[dict(model=s['model'],seed=s['seed'],checkpoint=s['checkpoint'],sha256=s['sha256'],threshold=s['threshold'],block='development') for s in p4f['models']]
    rev=REPO/'review';deps={}
    def read(p):deps[str(p)]=sha(p);return json.loads(p.read_text(encoding='utf-8'))
    thresholds=read(rev/'editor023_positive_architecture_value/EDITOR023_FROZEN_THRESHOLDS.json')
    records=read(rev/'editor023_positive_architecture_value/EDITOR023_CHECKPOINT_PARITY.json')['records']
    original=[]
    for r in records:
        if r['model'] not in ('TA2','C2-OPT','F10','L1'):continue
        original.append(dict(model='F00' if r['model']=='C2-OPT' else r['model'],seed=r['seed'],checkpoint=r['path'],sha256=r['expected_sha256'],threshold=thresholds[r['model']][str(r['seed'])],block='original'))
    allow=read(rev/'editor006a_preinference_freeze/EDITOR006A_MODEL_ALLOWLIST.json')
    for r in allow['artefacts']:
        if r['family'] in ('XGBoost_40','RF_40'):
            original.append(dict(model=r['family'],seed=r['seed'],checkpoint=r['path'],sha256=r['expected_sha256'],threshold=r['threshold'],block='original'))
    assert len(original)==18 and len(dev)==51
    scal=read(rev/'editor006a_preinference_freeze/EDITOR006A_SCALER.json');dsc=read(HPRIVATE/'DEVELOPMENT_DAILY_SCALER.json')
    assert deps[str(rev/'editor006a_preinference_freeze/EDITOR006A_SCALER.json')]=='6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488'
    bundles={}
    for release,dirname,mp in [('r5.1','teacher_anchored_r51_editor007b_bundle',rev/'editor007b_r51_secondary_stress/EDITOR007B_R51_BUNDLE_MANIFEST.json'),('r6.2','teacher_anchored_r62_editor006c_bundle',rev/'editor006c_r62_input_bundle/EDITOR006C_FINAL_RELEASE_MANIFEST.json')]:
        man=read(mp);folder=Path(r'C:\PhD\06_Datasets\derived')/dirname
        for c in man['component_files']:
            path=folder/c['filename'];assert sha(path)==c['sha256'];deps[str(path)]=c['sha256']
        bundles[release]=dict(folder=str(folder),manifest=str(mp),manifest_sha256=sha(mp),windows=996000 if release=='r5.1' else 1988000,official_incidents=4 if release=='r5.1' else 5)
    r61dir=R61/'outputs/editor024_r61_final_confirmation/bundle'
    old=read(R61/'review/editor024_r61_final_confirmation/EDITOR024_SHA256_MANIFEST.json')
    mp=R61/'review/editor024_r61_final_confirmation/EDITOR024_R61_INPUT_MANIFEST.json';meta=read(mp);expected=old[mp.relative_to(R61).as_posix()];expected=expected['sha256'] if isinstance(expected,dict) else expected;assert sha(mp)==expected
    for n in ('scaled_dense_daily.npy','calendar_dates.npy'):
        p=r61dir/n;deps[str(p)]=sha(p)
    bundles['r6.1']=dict(folder=str(r61dir),feature_shift_only=True,historical_bundle_byte_hashes_available=False,current_bytes_frozen_before_phase5_analysis=True,scaler_sha256=meta['scaler_hash'])
    for name in ('objective3_missing_source_robustness.py','objective3_perturbations.py','objective3_locked_common.py'):
        path=REPO/'src'/name;deps[str(path)]=sha(path)
    for name in ('input_bundle.py','safety.py','__init__.py'):
        path=REPO/'src/editor006b_harness'/name;deps[str(path)]=sha(path)
    hist=rev/'editor007d_cross_version_synthesis/EDITOR007D_MODEL_PORTABILITY.csv';deps[str(hist)]=sha(hist)
    deps[str(P4/'MODELS_FROZEN_PHASE4.json')]=sha(P4/'MODELS_FROZEN_PHASE4.json');deps[str(P4PRIVATE/'HOLDOUT_COHORT.npz')]=sha(P4PRIVATE/'HOLDOUT_COHORT.npz')
    done=read(P4/'SCORING_COMPLETE.json')
    for n,h in done['prediction_hashes'].items():
        p=P4PRIVATE/'scores'/n;assert sha(p)==h;deps[str(p)]=h
    for p in (P4PRIVATE/'bootstrap').glob('pooled_completed_*.npy'):deps[str(p)]=sha(p)
    for p in (P4/'HOLDOUT_RESULTS.csv',P4/'HOLDOUT_CONTRASTS.csv',P4PRIVATE/'BOOTSTRAP_USER_MULTIPLICITIES.npy',R2/'explanation/integrated_gradients_features.csv',R2/'explanation/holdout/integrated_gradients_features.csv',OUT/'AMENDMENT3_RECEIPT.json'):deps[str(p)]=sha(p)
    for s in original+dev:assert sha(s['checkpoint'])==s['sha256']
    # Validate loaders on DEVELOPMENT data only, never a target evaluation.
    vp=Path(r'C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_validation.npz');assert sha(vp)=='5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c'
    with np.load(vp,allow_pickle=False) as z:x=np.asarray(z['X'][:16],np.float32)
    dv=torch.device('cpu');torch.set_num_threads(2)
    tests=[]
    for s in original:
        p=predict_array(s,x,dv);saved=Path(s['checkpoint']).parent/'val_logits.npy';error=None
        if saved.exists():
            ref=rt.probs(np.load(saved)[:len(x)].ravel());error=float(np.max(np.abs(ref-p)));assert error<5e-4
        tests.append(dict(model=s['model'],seed=s['seed'],finite=bool(np.isfinite(p).all()),development_original_validation_parity_max_abs_error=error))
    methods=dict(exploratory=True,no_training=True,r52_test_sealed=True,bootstrap_replicates=2000,bootstrap_seed=42,source_levels=[0,.25,.5,.75,1],noise_levels=[0,.025,.05,.075,.1,.15,.2],perturbation_seed=101,source_partial_rule='linear interpolation between clean and raw-zero fully ablated standardized tensors; manuscript Section III-K',source_full_rule='inverse scale using development-only frozen scaler, zero source count/presence, recompute total and activity and zero duration only if inactive, rescale',noise_rule='authoritative gaussian_noise_continuous with SHA-derived paired RNG per level; continuous indices 0:7; bounded elementwise relative noise with floor zero; binary indices 7:13 unchanged; severity zero reuses clean saved scores',AURC='trapezoidal integral of AP(severity)/AP(clean), divided by maximum severity; source aggregate is arithmetic mean over five source AURCs',operational=dict(positive_window_detection=True,delay='first positive-window alert end-date minus first malicious day in allowed TRAIN+VALIDATION; no TEST first-day lookup',episodes='consecutive or same alert decision days per user; malicious-day containment uses actual daily labels',episode_rate_denominators=['all 232000 allowed calendar user-days','213000 scorable decision user-days'],top_k_label='endpoint malicious day primary; completed-window label also reported',unobserved_days='first 19 days of each period not scorable and marked unavailable'),ranking=dict(budgets=[.01,.05],budget_count='ceil(N*budget); stable score-descending row order for ties',recall_FPR=[.001,.01],FPR_rule='largest attainable ROC TPR at or below specified FPR, without target threshold recalibration'),calibration=dict(fits=2,TRACE='one common positive temperature fitted once on pooled three-seed DEVELOPMENT VALIDATION logits; shared unchanged across seeds',XGBoost_40='one common unpenalized Platt logistic map fitted once on pooled three-seed DEVELOPMENT VALIDATION logit scores; shared unchanged across seeds',ECE='15 equal-width bins over [0,1]',temperature_parameterization='log T; numerical bounds [-10,10] for stable scalar NLL minimization'),Holm=dict(family='all 12 Phase 4 pooled secondary contrasts',alpha=.05,p_values='two-sided bootstrap sign-tail probability with add-one correction: 2*min((1+n(delta<=0))/(B+1),(1+n(delta>=0))/(B+1)), capped at 1; exploratory approximate p-values'),power='normal approximation from observed paired bootstrap CI width; report 95% half-width and two-sided alpha .05 80%-power MDE; not a guarantee',resources='two CPU threads; at most 35% per-process GPU memory; 1 ms cooperative pause per neural batch; no other processes managed',incident_bootstrap='historical harness defines user bootstrap and notes 1:1 official insider/incident correspondence, not an independent incident-only bootstrap')
    methods['transfer_scalers']='Original block uses stored r5.2-all-user TRAIN z-space directly. Development block uses its own frozen DEVELOPMENT TRAIN scaler via float64 inverse of stored original z-space and forward transform; no target fitting. Float32 source-bundle quantization is retained and disclosed.'
    methods['r61_provenance']='Historical input-manifest hash verified; r6.1 derived bundle has no historical byte hashes in EDITOR024 SHA manifest, so its current bytes are hashed and frozen before feature-only analysis.'
    for p in CODE.glob('*.py'):ast.parse(p.read_text(encoding='utf-8'))
    f=dict(utc=utc(),amendment_sha256=a['sha256'],models=dict(original=original,development=dev),bundles=bundles,scalers=dict(original=scal,development=dsc),methods=methods,dependencies=deps,code_hashes={p.name:sha(p) for p in CODE.glob('*.py')},original_loader_preflight=tests,historical_file=str(hist))
    dump(OUT/'MODELS_AND_METHODS_FROZEN_PHASE5.json',f);status('PHASE5_FROZEN',original_model_seeds=18,development_model_seeds=51)
if __name__=='__main__':main()
