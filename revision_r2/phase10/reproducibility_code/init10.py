from pathlib import Path
import json,hashlib,datetime
import numpy as np
R2=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision');OUT=R2/'phase10';P=OUT/'private';B=Path(r'C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006c_bundle')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def dump(p,x):Path(p).write_text(json.dumps(x,indent=2),encoding='utf8')
OUT.mkdir(exist_ok=True);P.mkdir(exist_ok=True)
pr=R2/'holdout/PREREGISTRATION_R2_HOLDOUT.md';old=pr.read_bytes()
text='''
## Amendment 10: r6.2 cross-release tests (exploratory)

Approved by Qasim on 23 October 2026 at 15:25 (+08). Freeze before feature/statistical computation or training. Hard computational deadline 23 October 2026 17:45 (+08); each individual run has a 45-minute timeout. One GPU child, 35% allocator cap, two numerical CPU threads, cooperative pauses; no management of another chat's processes. No repository edits or pushes. Pseudonyms only in outputs.

Split: use official insider-status metadata solely for stratification. Sort r6.2 user identities within insider/non-insider strata, then one numpy default_rng(42), insider stratum first. Allocate 15 of 29 insiders and 1,985 of 3,971 non-insiders to HOLDOUT, 2,000 users in each arm. Shuffle each stratum, take its allocated prefix, and persist sorted pseudonyms (SHA256 identity first ten hex, prefixed U_) and private numeric indices; hash before opening features or window labels. Freeze nested adaptation samples with a separate default_rng(42), insider then non-insider development strata; 10%=200 and 25%=500 development users, half-up insider rounding, non-insider remainder, shared shuffled prefixes. Held-out identities/status never choose models or thresholds.

Chronology: exactly inherited cert_common13_pipeline.py rule nTRAIN=floor(0.80*nDays), nVALIDATION=floor(0.10*nDays), final remainder unused. Record dates from calendar metadata. Complete T=20 stride-one windows separately inside TRAIN and VALIDATION, never crossing boundaries. r6.2 held-out evaluation pools these two periods; terminal 10% unused. r5.2 uses only inherited TRAIN 2010-01-02--2011-02-18 and VALIDATION 2011-02-19--2011-04-10. r5.2 TEST sealed. Original 500 r5.2 HOLDOUT users are scored only for new pooled models, once per model/seed; original scores reused. New r6.2 HOLDOUT users are evaluation-only, once per model/condition; original zero-shot cached scores reused. No held-out fitting, stopping, selection, scaling, consensus references or thresholds.

Baseline: exact Phase4 r5.2 development-trained TRACE(TA2), task-only F00 and XGBoost-40 seeds 42/52/62 and cached Phase5 r6.2 scores, subset by frozen users and permissible completed-window indices. Phase5 storage scaler inverse is a fixed coordinate codec, not a newly fitted r6 scaler. Zero-shot uses inherited r5.2 development scaler and frozen thresholds.

Priority 1: refit only each original detector's max-F1 threshold using r6.2 development VALIDATION; models and scores unchanged. Contrast refit minus zero-shot for insiders detected and non-insiders flagged, for three models at each seed. Ranking measures identical and explicitly reused.

Priority 2: own r6.2 development TRAIN scaler, precursor, optimized teacher, F00, TRACE, XGBoost-40. Full frozen Phase4 training recipe, own TRAIN-label imbalance weights, clean r6.2 development VALIDATION AP checkpoint and max-F1 threshold. TRACE retains three matched teachers (42/52/62) and their equal mean logit consensus. Those prerequisite seeds are required for the first seed42 detector, not additional detector comparisons. Contrasts TRACE minus XGBoost-40, TRACE minus F00, within-release TRACE minus zero-shot TRACE.

Priority 3: TRACE starts from original r5.2 seed42 checkpoint, for nested 10% and 25% r6.2 development users. Fit each adaptation scaler only on its selected r6.2 TRAIN daily rows; use that common normalized representation for student and frozen r5.2 teachers. Frozen r5.2 matched route teacher and original three-teacher consensus on those TRAIN windows; TRACE loss BCE plus 0.5 logit consensus MSE plus 0.5 route loss. Divide each inherited optimizer parameter-group learning rate by ten, at most ten epochs, inherited patience four, clean same-selected-users VALIDATION AP selection and max-F1 threshold. XGBoost-40 retrains on original r5.2 development TRAIN plus same selected r6.2 TRAIN, own pooled TRAIN daily scaler and pooled development VALIDATION threshold. Contrasts adapted minus corresponding zero-shot at each fraction/model; TRACE minus XGBoost-40 at each fraction. Optional seeds52/62 use corresponding original student/matched teacher if all tests seed42 complete.

Priority 4: pooled original r5.2 development and all r6.2 development TRAIN, own pooled TRAIN daily scaler. Full same precursor/three optimized teachers/F00/TRACE/XGBoost recipe, pooled development VALIDATION selection/threshold. Evaluate each new detector once on each held-out release. On r6.2: pooled minus within-release and pooled minus zero-shot, per TRACE/F00/XGBoost. On r5.2: pooled minus original same model, per TRACE/F00/XGBoost.

Metrics: window average precision (PR-AUC), AP divided by window prevalence, insiders detected on at least one malicious-window alert, non-insiders flagged by any window, and share of insiders captured in top ceil(0.01*N) users ranked by max window score (pseudonym ascending ties). Official insider status defines denominators; disclose official insiders without positive completed windows. AP/operational positive labels max daily malicious label, score>=threshold. All metrics, counts, denominators and thresholds retained. Seed means are arithmetic metric means, never probability ensembles.

Inference: 2,000 paired whole-user cluster bootstrap replicates, default_rng(42), same user multiplicities on both sides and seeds within each release; paired percentile 95% CI, exclude and count undefined no-positive replicates. Top1 bootstrap conditions on observed selected set, with user multiplicity reweighting; report this limitation. AP includes tied score groups exactly. Two-sided raw p=min(1,2*min((1+n(delta<=0))/(Bvalid+1),(1+n(delta>=0))/(Bvalid+1))). Holm within each priority across ALL listed contrasts/endpoints and seeds42/52/62 plus mean: P1 3*2*4=24; P2 3*5*4=60; P3 6*5*4=120; P4 9*5*4=180. Missing contrasts retain p=1 and NOT RUN; no family shrinkage. CI direction above/below only if excludes0; Holm direction only adjusted p<.05. All exploratory; no causal, equivalence or general transfer guarantee. P1 ranking unchanged, no AP test. No separate baseline-null tests.

Priority/time: seed42 P1 then P2 then both P3 fractions then P4. Only after every test completes once add detector seeds52 then62 in same priority order. Outcomes never govern stopping. At deadline kill only owned current computation child, retain logs/checkpoints, mark unfinished NOT RUN (time), finalize report from completed results and PHASE10_PARTIAL. Any missing planned seed/test/interval also yields PARTIAL. No scientific computation after17:45; reporting and integrity bookkeeping only. One 300-dpi summary AP figure with >=12pt fonts and adjacent CSV. Preserve exact training/selection/scoring receipts, source/code hashes, all deviations and failures, report and PHASE10_RESULTS.json.
'''
if b'## Amendment 10:' not in old:
 with pr.open('ab') as f:f.write(text.encode())
 prefix=pr.read_bytes();receipt=dict(utc=now(),approved_local='2026-10-23T15:25:00+08:00',sha256=hashlib.sha256(prefix).hexdigest(),hashed_bytes=len(prefix),previous_bytes=len(old),previous_sha256=hashlib.sha256(old).hexdigest(),deadline_local='2026-10-23T17:45:00+08:00')
 with pr.open('a',encoding='utf8',newline='\n') as f:f.write('\n### Amendment 10 pre-computation SHA-256 receipt\n\n```json\n'+json.dumps(receipt,indent=2)+'\n```\n')
 dump(OUT/'AMENDMENT10_RECEIPT.json',receipt)
else:receipt=json.loads((OUT/'AMENDMENT10_RECEIPT.json').read_text())
assert not (OUT/'R62_SPLIT_RECEIPT.json').exists()
clar='''\n### Amendment 10 pre-split schema clarification\n\nMetadata-only initial check found official_insider_flags has five mapped users, not the 29 label-positive users requested. No split, feature processing, model scoring or training had occurred. Use per-user ANY completed_window_labels positive (via window_index) solely as insider stratification metadata, matching prior Phase9 reported 29 label-positive users. Persist this derived status vector and hash; never use held-out labels for training/selection/scaling/thresholds. Operational insider denominators likewise use frozen 29-user status; disclose insiders without eligible positive evaluation windows. All other split/decision rules unchanged. This replaces the incorrect official-status assumption in the initial amendment; both versions retained.\n'''
with pr.open('a',encoding='utf8',newline='\n') as f:f.write(clar)
prefix=pr.read_bytes();cr=dict(utc=now(),hashed_bytes=len(prefix),sha256=hashlib.sha256(prefix).hexdigest(),previous_bytes=len(old),previous_sha256=hashlib.sha256(old).hexdigest(),reason='official flag coverage five versus requested 29 label-positive users',feature_processing_or_training_started=False)
with pr.open('a',encoding='utf8',newline='\n') as f:f.write('\nClarification SHA-256 receipt:\n```json\n'+json.dumps(cr,indent=2)+'\n```\n')
dump(OUT/'AMENDMENT10_CLARIFICATION_RECEIPT.json',cr)
# Only split/calendar metadata opened here. No features, scores, labels or training.
ids=np.load(B/'user_ids.npy');dates=np.load(B/'calendar_dates.npy');wi=np.load(B/'window_index.npy',mmap_mode='r');wy=np.load(B/'completed_window_labels.npy',mmap_mode='r');flags=np.bincount(wi[:,0],weights=wy,minlength=4000)>0;assert len(ids)==4000 and flags.sum()==29;np.save(P/'INSIDER_STATUS.npy',flags)
rng=np.random.default_rng(42);held=[]
for flag,k in [(1,15),(0,1985)]:
 ix=np.flatnonzero(flags==flag);ix=ix[np.argsort(ids[ix])];rng.shuffle(ix);held.extend(ix[:k].tolist())
held=np.array(sorted(held));dev=np.setdiff1d(np.arange(4000),held);assert len(dev)==2000
pseudo=lambda i:'U_'+hashlib.sha256(str(ids[i]).encode()).hexdigest()[:10]
for name,ix in [('HOLDOUT',held),('DEVELOPMENT',dev)]:
 (OUT/f'R62_{name}_PSEUDONYMS.txt').write_text('\n'.join(sorted(map(pseudo,ix)))+'\n',encoding='utf8');np.save(P/f'{name}_indices.npy',ix)
rng=np.random.default_rng(42);samples={10:[],25:[]}
for flag in (1,0):
 ix=dev[flags[dev]==flag];ix=ix[np.argsort(ids[ix])];rng.shuffle(ix)
 for frac in (10,25):
  ni=int(np.floor(np.sum(flags[dev])*(frac/100)+.5));k=ni if flag else int(2000*frac/100)-ni;samples[frac].extend(ix[:k].tolist())
for frac,ix in samples.items():np.save(P/f'ADAPT{frac}_indices.npy',np.array(sorted(ix)))
n=len(dates);nt=int(.8*n);nv=int(.1*n)
split=dict(utc=now(),rng='numpy.default_rng(42), sorted identity strata, insider first',users=4000,development_users=2000,heldout_users=2000,development_insiders=int(flags[dev].sum()),heldout_insiders=int(flags[held].sum()),pseudonym_rule='U_ + SHA256(identity)[:10]',heldout_list_sha256=sha(OUT/'R62_HOLDOUT_PSEUDONYMS.txt'),development_list_sha256=sha(OUT/'R62_DEVELOPMENT_PSEUDONYMS.txt'),index_hashes={p.name:sha(p) for p in P.glob('*_indices.npy')},TRAIN=[str(dates[0]),str(dates[nt-1])],VALIDATION=[str(dates[nt]),str(dates[nt+nv-1])],unused_final_segment=[str(dates[nt+nv]),str(dates[-1])],n_days=n,n_train_days=nt,n_validation_days=nv,adaptation={str(k):dict(users=len(v),insiders=int(flags[v].sum())) for k,v in samples.items()},metadata_hashes={s:sha(B/s) for s in ('user_ids.npy','official_insider_flags.npy','calendar_dates.npy')},features_or_labels_opened=False)
dump(OUT/'R62_SPLIT_RECEIPT.json',split);digest=sha(OUT/'R62_SPLIT_RECEIPT.json');(OUT/'R62_SPLIT_RECEIPT.sha256').write_text(digest+'  R62_SPLIT_RECEIPT.json\n',encoding='utf8')
dump(OUT/'PREREQUISITES_FROZEN.json',dict(utc=now(),amendment_sha256=receipt['sha256'],split_receipt_sha256=digest,preregistration_after_receipt_sha256=sha(pr),split_before_any_feature_score_label_computation=True))
print(json.dumps(dict(amendment=receipt,split=split),indent=2))
