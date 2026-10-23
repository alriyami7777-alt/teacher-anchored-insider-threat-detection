from common6c import *
def main():
 pr=(H/'PREREGISTRATION_R2_HOLDOUT.md').read_bytes();assert hashlib.sha256(pr[:31207]).hexdigest()=='ba085b9000da3e4e55078dc0deac94976fe1fd9b7ecaa272682e012e6755dbee';assert hashlib.sha256(pr[:42986]).hexdigest()=='e09c661f1c20d3e4032b4f3a07783081479b8e833a590854e332878653f2ebc8'
 assert read(B6/'FINAL_AUDIT.json')['all_checks_passed'];assert (B6/'CHATGPT_PHASE6B_REPORT.md').read_text(encoding='utf-8').rstrip().endswith('PHASE6B_COMPLETE')
 PRIVATE.mkdir(parents=True,exist_ok=True);(PRIVATE/'logs').mkdir(exist_ok=True)
 dump(OUT/'AMENDMENT6_RECEIPT.json',dict(utc='2026-10-22T13:00:31.0983447Z',sha256='e09c661f1c20d3e4032b4f3a07783081479b8e833a590854e332878653f2ebc8',hashed_bytes=42986,previous_bytes=31207,previous_sha256='ba085b9000da3e4e55078dc0deac94976fe1fd9b7ecaa272682e012e6755dbee',preregistration_final_sha256=sha(H/'PREREGISTRATION_R2_HOLDOUT.md'),before_scoring=True))
 # Development-only augmentation checks against the unchanged Phase 5 helpers.
 bundle=rt.data();x=np.array(bundle['train']['X'][:1024]);original=x.copy();a,stats=augment(x,np.random.default_rng(np.random.SeedSequence([42,42,0])),scaler());aa,stats2=augment(x,np.random.default_rng(np.random.SeedSequence([42,42,0])),scaler());assert np.array_equal(a,aa) and np.array_equal(x,original);assert a.shape==x.shape
 frozen=read(P5/'MODELS_AND_METHODS_FROZEN_PHASE5.json')
 for p,h in frozen['dependencies'].items():assert sha(p)==h
 dump(OUT/'DEVELOPMENT_VERIFICATION.json',dict(utc=utc(),augmentation_deterministic=True,input_unmutated=True,shape_preserved=True,sample_stats=stats,source_dropout_probability=.3,noise_probability=.3,noise_levels=NOISE,scaler_sha256=sha(HP/'DEVELOPMENT_DAILY_SCALER.json'),Phase5_helper_hashes={n:sha(REPO/'src'/n) for n in ('objective3_missing_source_robustness.py','objective3_perturbations.py')},r52_test_read=False,holdout_values_used=False))
 status('PREPARATION_COMPLETE')
if __name__=='__main__':main()
