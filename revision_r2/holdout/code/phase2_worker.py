"""Unattended orchestration. No GPU import/use until the five-minute Phase 1 gate passes."""
from pathlib import Path
from datetime import datetime,timezone
import json,os,sys,time,hashlib,subprocess,csv,traceback
ROOT=Path(r'C:\PhD\07_Projects\r2_holdout')
OUT=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision\holdout')
PRIVATE=OUT/'private'
PYTHON=sys.executable
SEEDS=(42,52,62)
ORDER=[(m,s) for m in ('T-OPT','F00','TA2','XGBoost_40','RF_40','L1','F10','uniT-OPT','uniTA2') for s in SEEDS]
def utc():return datetime.now(timezone.utc).isoformat()
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def dump(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,indent=2),encoding='utf-8');os.replace(tmp,p)
def gate_open():
    p=OUT.parent/'CHATGPT_PHASE1_REPORT.md'
    return p.is_file() and p.read_text(encoding='utf-8-sig').rstrip().endswith('PHASE1_COMPLETE')
class Worker:
    def __init__(self):
        self.started=utc();self.results=[];self.skipped=[];self.current=None;self.phase='initializing';self.gate_receipt=None
        self.configs=json.loads((OUT/'CONFIGS_FROZEN.json').read_text())['configs']
    def status(self):
        dump(OUT/'PHASE2_STATUS.json',{'utc':utc(),'started_utc':self.started,'pid':os.getpid(),'phase':self.phase,'current':self.current,'successful_runs':len(self.results),'requested_successful_runs':sum('PRECURSOR' not in r['model'] for r in self.results),'requested_total_runs':27,'skipped':self.skipped,'phase1_gate':self.gate_receipt,'holdout_scored':False,'test_read':False})
    def report(self,finished=False):
        manifest=json.loads((OUT/'DATA_MANIFEST.json').read_text())
        lines=['# Phase 2: user-disjoint holdout retraining','',f'Started UTC: {self.started}',f'Updated UTC: {utc()}',f'Status: {self.phase}','',
        '## Step 0 — preregistration and user split','',
        'Preregistration was written and SHA-256 frozen before split materialization. The pre-split bytes are preserved in the isolated code folder. One NumPy default_rng(20261022) shuffled sorted insider and then non-insider strata. No rounding adjustment was needed.',
        'HOLDOUT: 500 users (25 insider, 475 non-insider). DEVELOPMENT: 1,500 users (74 insider, 1,426 non-insider). Public receipts contain counts and list hashes; all user IDs are private.',
        'Insider strata were obtained from the 99 nonempty per-user r5.2 answer-file names; no answer activity payload or TEST day was read. The prior producing preparation manifest records successful malicious-event matching for these sources.',
        '','## Step 1 — CPU data rebuild','',
        'DEVELOPMENT TRAIN: 591,000 windows, 3,040 positives. DEVELOPMENT VALIDATION: 48,000 windows, 473 positives. Each window is 20 × 13; 40 raw window summaries use the producing numeric and binary aggregations.',
        'HOLDOUT label counts only: TRAIN 197,000 windows / 917 positives; VALIDATION 16,000 windows / 255 positives. These were read from label/identity members of the existing allowed TRAIN/VALIDATION archives; the X members were not opened.',
        f'Scaler fit on 619,500 DEVELOPMENT TRAIN user-days only. Primary neural w+ = {manifest["pos_weight"]}. Rebuilt window counts and labels match the original development subset exactly; mismatches: {manifest["sanity_mismatches"]}. CPU preparation: {manifest["cpu_seconds"]:.2f} seconds.',
        'Daily-table scanning used development-user and date predicates (2010-01-02 through 2011-04-10); no TEST row was returned or materialized. No holdout feature windows were built.',
        '','## Step 2 — frozen training recipes and execution','',
        'All training runs wait for CHATGPT_PHASE1_REPORT.md to end with PHASE1_COMPLETE. Gate checks occur every 300 seconds. Each failed run receives at most one identical-config retry; dependent items are skipped if the required development checkpoint is unavailable.',
        'The producing T-OPT recipe freezes an attention-linear encoder. Therefore three development-only attention-linear prerequisite models are trained first (and three analogous uni-LSTM prerequisites later), using their original frozen recipe: Adam 0.001, ratio class weight multiplier 1.0, ReduceLROnPlateau factor 0.5/patience 2/min_lr 1e-5, maximum 15 epochs/patience 4. Historical all-user checkpoints are never used.',
        'T-OPT and student recipes retain the producing ODST-046 constructor and initialization; max 15 epochs, patience 4, batch 1024, clip 1.0, primary neural class weight 0.25 × N-/N+. Student encoder/attention learning rates 3e-5 and head learning rate 1e-3. TA2 is task + 0.5 equal-weight three-teacher logit MSE + 0.5 matched-teacher route KL. F00 starts from its matched development T-OPT and uses task loss only. F10 omits route KL. L1 starts with the matched T-OPT encoder and a fresh zero-initialized linear head, plus ensemble logit MSE.',
        'RF_40 retains balanced_subsample; XGBoost_40 retains scale_pos_weight=N-/N+ from development TRAIN, as their producing recipes require. The daily scaler does not alter their raw-feature summary definition. The exploratory uni intervention uses one direction, hidden size 128 and representation dimension 128, with its own development-only teachers.',
        'No hyperparameter search is performed. Validation probabilities, checkpoint selection and maximum-F1 thresholds use DEVELOPMENT VALIDATION only. Every run, config, attempt, epochs, best epoch, development AP, duration and device is recorded in TRAINING_LOG.csv; detailed logs/checkpoints remain private.',
        'Requested run order: T-OPT ×3; F00 ×3; TA2 ×3; XGBoost_40 ×3; RF_40 ×3; L1 ×3; F10 ×3; uni T-OPT ×3; uniTA2 ×3. Necessary precursor training occurs immediately before its T-OPT stage.',
        '',f'Completed requested runs: {sum("PRECURSOR" not in r["model"] for r in self.results)}/27. Completed prerequisite runs: {sum("PRECURSOR" in r["model"] for r in self.results)}.',
        '', 'Skipped or failed items: '+(json.dumps(self.skipped) if self.skipped else 'none to date.'),
        '', 'Recipe deviations: none intended beyond development-user restriction, development scaler refit and the explicitly preregistered uni architecture intervention. Prerequisite models preserve their original class-weight/scheduler recipe. Diagnostic-only training passes are omitted without changing optimization equations.',
        '', '## Step 3 — model and future-scoring freeze','',
        'The future one-pass scoring script is written and hashed, with frozen runtime dependencies. It is never executed by this worker. It requires a recorded supervisor disclosure before later scoring, verifies the frozen hashes, consumes an exclusive one-pass sentinel, and uses the frozen development thresholds without recalibration. Primary view: HOLDOUT VALIDATION + TEST completed windows; secondary offset-0 de-overlap and endpoint-label views. Paired user-cluster bootstrap uses 2,000 replicates, seed 42, 95% percentile intervals and the preregistered decision rules.',
        'No holdout scoring, prediction or performance metric is computed tonight. No TEST tensor is opened. No r5.1, r6.1 or r6.2 data is used. No existing teacher-anchored repository or worktree is changed, and nothing is pushed.',
        '', 'Models freeze: '+('written to MODELS_FROZEN.json; consult its completeness and skipped items.' if finished else 'pending training completion.'),
        '', '## Evidence','', 'PREREGISTRATION_R2_HOLDOUT.md; SPLIT_RECEIPT.json; DATA_MANIFEST.json; TRAINING_LOG.csv; PHASE2_STATUS.json; MODELS_FROZEN.json (at finish). All IDs, tensors, source-level tracebacks and checkpoints are under private/.', '']
        if finished:lines.append('PHASE2_COMPLETE_MODELS_FROZEN_NOT_SCORED')
        (OUT/'CHATGPT_PHASE2_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    def wait_gate(self):
        self.phase='waiting_for_phase1';self.current=None
        while not gate_open():
            self.status();self.report();time.sleep(300)
        p=OUT.parent/'CHATGPT_PHASE1_REPORT.md'
        self.gate_receipt={'observed_utc':utc(),'phase1_report_sha256':sha(p),'marker':'PHASE1_COMPLETE'}
        dump(OUT/'PHASE1_GATE_RECEIPT.json',self.gate_receipt)
    def available(self,m,s):return any(r['model']==m and r['seed']==s for r in self.results)
    def dependencies(self,m,s):
        if m in ('T-OPT','uniT-OPT'):return [(('uni' if m.startswith('uni') else '')+'AL_PRECURSOR',s)]
        if m in ('F00','TA2','F10','L1'):return [('T-OPT',s)] if m=='F00' else [('T-OPT',ss) for ss in SEEDS]
        if m=='uniTA2':return [('uniT-OPT',ss) for ss in SEEDS]
        return []
    def log(self,row):
        path=OUT/'TRAINING_LOG.csv';exists=path.exists()
        fields=['utc','model','seed','attempt','status','config','epochs','best_epoch','dev_validation_pr_auc','wall_seconds','gpu','checkpoint_sha256','detail']
        with path.open('a',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=fields)
            if not exists:w.writeheader()
            w.writerow({k:row.get(k,'') for k in fields})
    def run(self,m,s):
        missing=[f'{dm}/seed{ds}' for dm,ds in self.dependencies(m,s) if not self.available(dm,ds)]
        if missing:
            skip={'model':m,'seed':s,'reason':'missing development-only dependencies: '+', '.join(missing)};self.skipped.append(skip)
            self.log({'utc':utc(),'model':m,'seed':s,'status':'skipped','detail':skip['reason']});self.status();self.report();return
        self.phase='training';self.current={'model':m,'seed':s}
        for attempt in (1,2):
            if not gate_open():self.wait_gate()
            self.phase='training'
            self.current={'model':m,'seed':s,'attempt':attempt};self.status();self.report()
            result=PRIVATE/'results'/f'{m}_seed{s}_attempt{attempt}.json';result.parent.mkdir(parents=True,exist_ok=True)
            log=PRIVATE/'run_logs'/f'{m}_seed{s}_attempt{attempt}.log';log.parent.mkdir(parents=True,exist_ok=True)
            t0=time.perf_counter()
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1')
            with log.open('w',encoding='utf-8') as handle:
                proc=subprocess.Popen([PYTHON,str(ROOT/'phase2_runtime.py'),'--model',m,'--seed',str(s),'--result',str(result)],cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
                while proc.poll() is None:self.status();time.sleep(30)
            elapsed=time.perf_counter()-t0
            if proc.returncode==0 and result.exists():
                r=json.loads(result.read_text());assert r['status']=='ok' and sha(r['checkpoint'])==r['sha256']
                self.results.append(r)
                self.log({'utc':utc(),'model':m,'seed':s,'attempt':attempt,'status':'ok','config':json.dumps(r['config'],sort_keys=True),'epochs':r['epochs'],'best_epoch':r['best_epoch'],'dev_validation_pr_auc':r['dev_validation_pr_auc'],'wall_seconds':r['wall_seconds'],'gpu':r['gpu'],'checkpoint_sha256':r['sha256']})
                self.status();self.report();return
            # Tracebacks stay private; record the exact config via the run's progress file if available.
            progress=PRIVATE/'progress'/f'{m}_{s}.json'
            config=self.configs[f'{m}/seed{s}']
            self.log({'utc':utc(),'model':m,'seed':s,'attempt':attempt,'status':'failed','config':json.dumps(config,sort_keys=True),'wall_seconds':elapsed,'detail':f'exit {proc.returncode}; full traceback in private run log'})
        self.skipped.append({'model':m,'seed':s,'reason':'failed twice with identical config; see private run logs'});self.status();self.report()
    def finish(self):
        script=ROOT/'phase2_score_later.py'
        implementation=[p for p in ROOT.rglob('*.py') if '__pycache__' not in str(p)]
        requested=sum('PRECURSOR' not in r['model'] for r in self.results)
        payload={'utc':utc(),'training_finished':True,'all_requested_models_succeeded':requested==27,'requested_successful_runs':requested,'requested_total_runs':27,'holdout_scored':False,'test_read':False,'models':[{k:v for k,v in r.items() if k!='history'} for r in self.results],'skipped':self.skipped,'scoring_script':{'path':str(script),'sha256':sha(script),'executed':False},'implementation_files':[{'path':str(p),'sha256':sha(p)} for p in implementation],'data_manifest_sha256':sha(OUT/'DATA_MANIFEST.json'),'scaler_sha256':sha(PRIVATE/'DEVELOPMENT_DAILY_SCALER.json'),'holdout_list_sha256':sha(PRIVATE/'HOLDOUT_USERS.txt'),'development_list_sha256':sha(PRIVATE/'DEVELOPMENT_USERS.txt'),'phase1_gate':self.gate_receipt}
        dump(OUT/'MODELS_FROZEN.json',payload)
        self.phase='finished_models_frozen_not_scored';self.current=None;self.status();self.report(finished=True)
    def main(self):
        with (PRIVATE/'WORKER_STARTED.json').open('x',encoding='utf-8') as f:json.dump({'utc':self.started,'pid':os.getpid()},f)
        assert (OUT/'DATA_MANIFEST.json').exists()
        self.status();self.report();self.wait_gate()
        # Complete development-only prerequisites before their frozen teacher stage.
        for m,s in ORDER:
            if m in ('T-OPT','uniT-OPT') and s==42:
                precursor=('uni' if m.startswith('uni') else '')+'AL_PRECURSOR'
                for ps in SEEDS:self.run(precursor,ps)
            self.run(m,s)
        self.finish()

if __name__=='__main__':
    worker=Worker()
    try:worker.main()
    except BaseException:
        (PRIVATE/'WORKER_FATAL.log').write_text(traceback.format_exc(),encoding='utf-8')
        worker.phase='fatal_error_see_private_log';worker.status();worker.report();raise
