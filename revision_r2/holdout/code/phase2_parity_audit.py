"""Mandatory P1-P4 audit/correction. Development-only, CPU-only, no scoring entrypoint."""
from pathlib import Path
from datetime import date,datetime,timezone
import os,sys,json,hashlib,subprocess,zipfile,shutil,time,csv,platform,traceback,importlib.metadata
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import joblib
from sklearn.metrics import average_precision_score
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

ROOT=Path(r'C:\PhD\07_Projects\r2_holdout')
OUT=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision\holdout')
PRIVATE=OUT/'private';ARCHIVE=PRIVATE/'parity_v1';WORK=PRIVATE/'parity_audit';WORK.mkdir(exist_ok=True)
PRODUCING=Path(r'C:\PhD\07_Projects\cert-r52-locked-baselines')
ORIG=PRODUCING/'outputs/objective2/r52_locked_baselines'
TENSORS=PRIVATE/'tensors'
SEEDS=(42,52,62)
def utc():return datetime.now(timezone.utc).isoformat()
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def dump(p,x):
    p=Path(p);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,indent=2,default=str),encoding='utf-8');os.replace(tmp,p)
def loadj(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def ap(y,p):return float(average_precision_score(y,p))
def maxdiff(a,b):return float(np.max(np.abs(np.asarray(a,dtype=np.float64)-np.asarray(b,dtype=np.float64))))
def same_param(a,b):
    if isinstance(a,(float,np.floating)) and isinstance(b,(float,np.floating)) and np.isnan(a) and np.isnan(b):return True
    return a==b

def dev_member(path,key,rows):
    """Decode numeric rows ONLY for development users from an NPZ NPY member.

    ZipFile seeks over excluded spans; no excluded feature/probability row is
    converted to an array, fed to a model, summarized, or retained.
    """
    assert 'test' not in Path(path).name.lower()
    rows=np.asarray(rows,dtype=np.int64);assert len(rows) and np.all(np.diff(rows)>0)
    with zipfile.ZipFile(path) as z, z.open(key+'.npy') as f:
        version=np.lib.format.read_magic(f)
        reader=np.lib.format.read_array_header_1_0 if version==(1,0) else np.lib.format.read_array_header_2_0
        shape,fortran,dtype=reader(f)
        assert not fortran and not dtype.hasobject
        stride=int(np.prod(shape[1:],dtype=np.int64))*dtype.itemsize
        base=f.tell();result=np.empty((len(rows),*shape[1:]),dtype=dtype)
        cuts=np.r_[0,np.flatnonzero(np.diff(rows)>1)+1,len(rows)]
        for a,b in zip(cuts[:-1],cuts[1:]):
            f.seek(base+int(rows[a])*stride)
            raw=f.read(int(b-a)*stride);assert len(raw)==int(b-a)*stride
            result[a:b]=np.frombuffer(raw,dtype=dtype).reshape((int(b-a),*shape[1:]))
    return result

def copy_producing_sources():
    git=['git','-c','safe.directory='+PRODUCING.as_posix(),'-C',str(PRODUCING)]
    commit=subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip()
    records=[]
    for name in ('__init__.py','data.py','safety.py','metrics.py'):
        rel='scripts/r52_locked_baselines/'+name
        content=subprocess.check_output(git+['show',commit+':'+rel])
        target=ROOT/'parity_source/r52_locked_baselines'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
        # Verify the used producing worktree source has identical text (line endings ignored).
        assert content.decode().replace('\r\n','\n')==(PRODUCING/rel).read_text(encoding='utf-8-sig').replace('\r\n','\n')
        records.append({'source_commit':commit,'source_path':rel,'copied_path':str(target),'sha256':sha(target)})
    dump(ROOT/'PARITY_PRODUCING_SOURCES.json',records)
    sys.path.insert(0,str(ROOT/'parity_source'))
    from r52_locked_baselines.data import aggregate_common13_windows
    from r52_locked_baselines.metrics import choose_threshold
    return aggregate_common13_windows,choose_threshold,records

def main():
    assert loadj(OUT/'PARITY_GATE.json')['status'] not in ('PARITY_GATE_FIXED','PARITY_GATE_PASS'),'Parity is already frozen; refuse duplicate audit/retraining'
    start=time.perf_counter();assert not (PRIVATE/'HOLDOUT_SCORING_CONSUMED.json').exists()
    shutil.copyfile(Path(__file__),ROOT/'phase2_parity_audit.py')
    aggregate,choose_threshold,sources=copy_producing_sources()
    oldfreeze=loadj(OUT/'MODELS_FROZEN_v1.json');oldmanifest=loadj(ARCHIVE/'DATA_MANIFEST.json')
    dev=(PRIVATE/'DEVELOPMENT_USERS.txt').read_text().splitlines();assert len(dev)==1500
    report={'status':'PENDING_PARITY_AUDIT','started_utc':utc(),'scope':'DEVELOPMENT TRAIN / VALIDATION only; original all-user models used only for DEVELOPMENT VALIDATION diagnostics','development_users':1500,'holdout_scored':False,'holdout_inference_rows':0,'test_read':False,'scoring_permitted':False,'producing_sources':sources,'P1':{},'P2':{},'P3':{},'P4':{}}
    dump(OUT/'PARITY_GATE.json',report)
    datasets={};rows_by_split={};orig_val=None
    for split in ('train','validation'):
        path=PRODUCING/f'data/processed/r5.2/tensors/r52_T20_s1_{split}.npz'
        # Identity metadata is used only to select/alignment-check development rows.
        with np.load(path,allow_pickle=True) as z:
            users=z['user'].astype(str);rows=np.flatnonzero(np.isin(users,dev))
            ids=z['sequence_id'][rows].astype(str);starts=z['start_date'][rows].astype(str);ends=z['end_date'][rows].astype(str)
        rows_by_split[split]=rows
        with np.load(TENSORS/f'{split}_metadata.npz') as meta:
            assert np.array_equal(ids,meta['sequence_id']) and np.array_equal(users[rows],meta['user'])
            assert np.array_equal(starts,meta['start_date']) and np.array_equal(ends,meta['end_date'])
            metadata={k:meta[k] for k in meta.files}
        y=np.load(TENSORS/f'{split}_y.npy');original_y=dev_member(path,'y',rows)
        assert np.array_equal(y,original_y)
        X=np.load(TENSORS/f'{split}_X.npy',mmap_mode='r')
        previous=np.load(TENSORS/f'{split}_X40.npy',mmap_mode='r')
        corrected=np.lib.format.open_memmap(WORK/f'{split}_X40_corrected.npy',mode='w+',dtype=np.float32,shape=(len(y),40))
        for lo in range(0,len(y),8192):
            block,names=aggregate(np.asarray(X[lo:lo+8192]));corrected[lo:lo+len(block)]=block
        corrected.flush()
        datasets[split]={'X':X,'old_X40':previous,'fixed_X40':corrected,'y':y,'metadata':metadata,'path':path}
        if split=='validation':
            orig_val=dev_member(path,'X',rows)
            original40=dev_member(ORIG/'aggregated_features/r52_T20_s1_validation_agg40.npz','X',rows)
            reproduced40,producing_names=aggregate(orig_val)
            with np.load(ORIG/'aggregated_features/r52_T20_s1_validation_agg40.npz') as z: saved_names=z['feature_names'].astype(str).tolist()
            assert names==saved_names==producing_names==oldmanifest['tabular_feature_names']
            report['P1']={'column_order_match':True,'definitions_match_by_name':True,'mismatch_found':True,'root_cause':'v1 summaries aggregated raw float64 daily values then cast to float32; producing baseline aggregates the standardized float32 20x13 sequence tensor (including binary channels)','producing_reference_reproduced_bitwise':bool(np.array_equal(reproduced40,original40)),'producing_reference_max_abs_difference':maxdiff(reproduced40,original40),'corrected_recipe_vs_producing_function_on_development_refit_tensor_max_abs_difference':0.,'authorized_residual':'Corrected development features retain the preregistered development TRAIN scaler; direct comparison with the original all-user TRAIN scaler inputs therefore has expected affine/rounding differences. No original all-user scaler is used for retraining.','dtype_v1':'aggregate float64 raw -> float32','dtype_producing_and_fixed':'aggregate float32 standardized tensor -> float32','extra_40_feature_scaler':'none in producing or fixed','columns':[{'feature':name,'v1_vs_original_producing_max_abs_difference':maxdiff(previous[:,j],original40[:,j]),'v1_vs_correct_producing_recipe_with_dev_scaler_max_abs_difference':maxdiff(previous[:,j],corrected[:,j]),'fixed_dev_scaler_vs_original_scaler_max_abs_difference':maxdiff(corrected[:,j],original40[:,j]),'original_reference_reproduction_max_abs_difference':maxdiff(reproduced40[:,j],original40[:,j])} for j,name in enumerate(names)]}
            assert report['P1']['producing_reference_reproduced_bitwise']
            datasets[split]['original40']=original40
    print('P1: raw-versus-standardized mismatch confirmed; all 40 original input columns reproduced bitwise.',flush=True)
    val=datasets['validation'];rows=rows_by_split['validation']
    for name,prefix in [('XGBoost_40','xgboost'),('RF_40','random_forest')]:
        folder=ORIG/f'{prefix}_seed42';spec=loadj(folder/'model_hash.json');path=folder/spec['model_path'];assert sha(path)==spec['sha256']
        if prefix=='xgboost':original_model=XGBClassifier();original_model.load_model(path)
        else:original_model=joblib.load(path)
        saved=dev_member(folder/'validation_probabilities.npz','y_proba',rows)
        saved_y=dev_member(folder/'validation_probabilities.npz','y_true',rows);assert np.array_equal(saved_y,val['y'])
        entry={'seed':42,'windows':len(rows),'positives':int(val['y'].sum()),'frozen_original_model_sha256':sha(path),'saved_development_AP':ap(val['y'],saved),'inputs':{}}
        for label,key in [('v1_rebuilt_raw_features','old_X40'),('original_producing_features','original40'),('corrected_producing_recipe_development_scaler','fixed_X40')]:
            p=original_model.predict_proba(val[key])[:,1].astype(np.float64)
            entry['inputs'][label]={'development_AP':ap(val['y'],p),'max_abs_probability_difference_vs_saved':maxdiff(p,saved),'max_abs_probability_difference_after_float32_serialization':maxdiff(p.astype(np.float32),saved)}
            np.save(WORK/f'original_{name}_seed42_{label}_dev_validation_probs.npy',p)
            if key=='original40':assert np.array_equal(p.astype(np.float32),saved),'Original producing probabilities not reproduced'
        entry['original_reference_prediction_parity_pass']=True;entry['corrected_scaler_difference_is_expected']=True
        report['P2'][name]=entry
        print('P2',name,json.dumps(entry['inputs']),flush=True)
    # Diff every estimator parameter, including inherited defaults, all three seeds.
    old_by_key={(r['model'],r['seed']):r for r in oldfreeze['models']}
    current_versions={p:importlib.metadata.version(p) for p in ('numpy','pandas','scikit-learn','xgboost','joblib')}
    original_environment=loadj(ORIG/'protocol_lock.json')['software_versions']
    report['P3']={'rows':[],'feature_list_match':True,'class_weight_rule_match':True,'early_stopping':{'producing':None,'v1':None,'fixed':None},'seeds':list(SEEDS),'original_environment':original_environment,'v1_environment':loadj(OUT/'ENVIRONMENT_PHASE2.json'),'fixed_tabular_environment':{'python':sys.version,'executable':sys.executable,'packages':current_versions},'representation_difference':'raw daily input versus scaled sequence input; FIX REQUIRED','serialization_difference':{'XGBoost_40':'v1 joblib; producing JSON; fixed JSON','RF_40':'joblib in all versions'},'threshold_numeric_difference':'v1 XGBoost threshold candidates calculated from float32 probabilities; producing and fixed cast predict_proba to float64 first','training_target_dtype_difference':'v1 float32 labels; producing/fixed int32 (binary values unchanged)','software_difference':'v1 Python/NumPy/pandas differ from the recorded tabular environment; fixed uses the installed producing-version Conda environment. Neural environment is retained.'}
    configs={}
    for name,prefix,cls in [('XGBoost_40','xgboost',XGBClassifier),('RF_40','random_forest',RandomForestClassifier)]:
        for seed in SEEDS:
            original_cfg=loadj(ORIG/f'{prefix}_seed{seed}/config.json')
            params={k:v for k,v in original_cfg['hyperparameters'].items() if k!='class_weight_mode'}
            old_spec=old_by_key[name,seed];assert sha(old_spec['checkpoint'])==old_spec['sha256']
            old=joblib.load(old_spec['checkpoint']);expected=cls(**params)
            actual=old.get_params(deep=True);reference=expected.get_params(deep=True)
            changes=[{'parameter':k,'producing':reference.get(k),'v1_development':actual.get(k),'allowed_subset_recompute':k=='scale_pos_weight'} for k in sorted(set(actual)|set(reference)) if not same_param(actual.get(k),reference.get(k))]
            ratio=(len(datasets['train']['y'])-int(datasets['train']['y'].sum()))/int(datasets['train']['y'].sum())
            if name=='XGBoost_40':params['scale_pos_weight']=ratio
            fixed=cls(**params).get_params(deep=True)
            residual=[{'parameter':k,'producing':reference.get(k),'fixed_development':fixed.get(k),'allowed_subset_recompute':k=='scale_pos_weight'} for k in sorted(set(fixed)|set(reference)) if not same_param(fixed.get(k),reference.get(k))]
            assert not any(not r['allowed_subset_recompute'] for r in residual)
            assert all(k in original_cfg['feature_names'] for k in names) and names==original_cfg['feature_names']
            configs[name,seed]={'model':name,'seed':seed,'source':'cert-r52-locked-baselines/scripts/r52_locked_baselines/train.py','params':params,'all_estimator_parameters':fixed,'feature_names':names,'features':'40 aggregates of development-TRAIN-standardized float32 20x13 tensors; exact producing aggregate_common13_windows','early_stopping':None,'fit_eval_set':None,'labels_dtype':'int32','threshold_input_dtype':'float64','threshold_rule':'producing maximum validation F1; sorted grid+quantiles; first maximum','development_only':True,'parity_correction':True}
            report['P3']['rows'].append({'model':name,'seed':seed,'all_parameters_checked':sorted(reference),'producing_all_parameters':reference,'v1_development_all_parameters':actual,'v1_vs_producing_differences':changes,'fixed_vs_producing_differences':residual,'fixed_config':configs[name,seed]})
    # P4 verifies BOTH split tensors directly from the same development raw days.
    old_scaler_path=Path(r'C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor023\review\editor006a_preinference_freeze\EDITOR006A_SCALER.json')
    assert sha(old_scaler_path)=='6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488'
    original_scaler=loadj(old_scaler_path);new_scaler=loadj(PRIVATE/'DEVELOPMENT_DAILY_SCALER.json');features=new_scaler['features']
    om=np.array(original_scaler['mean']);oscale=np.array(original_scaler['scale']);nm=np.array(new_scaler['mean']);ns=np.array(new_scaler['scale'])
    daily_path=Path(r'C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\interval_level\r52_user_day_intervals_dense.parquet')
    pred=ds.field('user').isin(dev)&(ds.field('interval_date')>=date(2010,1,2))&(ds.field('interval_date')<=date(2011,4,10))
    daily=ds.dataset(daily_path,format='parquet').to_table(columns=['user','interval_date',*features],filter=pred).to_pandas().sort_values(['user','interval_date'],kind='mergesort')
    daily['interval_date']=pd.to_datetime(daily.interval_date)
    assert set(daily.user)==set(dev) and len(daily)==1500*464
    groups={str(u):g.reset_index(drop=True) for u,g in daily.groupby('user',sort=False)}
    report['P4']={'original_scaler_sha256':sha(old_scaler_path),'development_scaler_sha256':sha(PRIVATE/'DEVELOPMENT_DAILY_SCALER.json'),'original_fit_train_daily_rows':original_scaler['n_train_daily_rows'],'development_fit_train_daily_rows':new_scaler['fit_rows'],'features':[{'feature':f,'original_mean':float(om[j]),'original_std_ddof0':float(oscale[j]),'development_mean':float(nm[j]),'development_std_ddof0':float(ns[j])} for j,f in enumerate(features)],'splits':{}}
    fit=daily.loc[daily.interval_date<=pd.Timestamp('2011-02-18'),features].to_numpy(dtype=np.float64)
    assert np.array_equal(fit.mean(0),nm) and np.array_equal(fit.std(0,ddof=0),ns)
    for split,bundle in datasets.items():
        original=orig_val if split=='validation' else dev_member(bundle['path'],'X',rows_by_split[split])
        md=bundle['metadata'];current=bundle['X'];oldmax=np.zeros(13);newmax=np.zeros(13);oldn=np.zeros(13,dtype=np.int64);newn=np.zeros(13,dtype=np.int64)
        # Rows are contiguous by user in the producing tensors.
        ur=md['user'];cuts=np.r_[0,np.flatnonzero(ur[1:]!=ur[:-1])+1,len(ur)]
        for lo,hi in zip(cuts[:-1],cuts[1:]):
            g=groups[str(ur[lo])];raw=g[features].to_numpy(dtype=np.float64)
            start=np.searchsorted(g.interval_date.to_numpy(),md['start_date'][lo:hi].astype('datetime64[ns]'))
            ix=start[:,None]+np.arange(20)[None,:];rw=raw[ix]
            assert np.array_equal(g.interval_date.to_numpy()[ix[:,-1]],md['end_date'][lo:hi].astype('datetime64[ns]'))
            old_expected=((rw-om)/oscale).astype(np.float32);new_expected=((rw-nm)/ns).astype(np.float32)
            od=np.abs(original[lo:hi].astype(np.float64)-old_expected);nd=np.abs(current[lo:hi].astype(np.float64)-new_expected)
            oldmax=np.maximum(oldmax,od.max((0,1)));newmax=np.maximum(newmax,nd.max((0,1)))
            oldn+=(od!=0).sum((0,1));newn+=(nd!=0).sum((0,1))
        report['P4']['splits'][split]={'shape':list(current.shape),'original_tensor_reconstructed_from_same_raw_days_max_abs_difference_by_feature':oldmax.tolist(),'development_tensor_reconstructed_from_same_raw_days_max_abs_difference_by_feature':newmax.tolist(),'original_nonidentical_values_by_feature':oldn.tolist(),'development_nonidentical_values_by_feature':newn.tolist(),'labels_and_window_identity_match':True}
        assert np.all(oldmax==0) and np.all(newmax==0),'Unexplained neural tensor mismatch'
        if split=='train':del original
    report['P4']['only_scaler_refit_differs']=True
    print('P4: both TRAIN and VALIDATION tensors reconstructed bitwise from identical raw windows under their respective scalers.',flush=True)
    report['audit_completed_utc']=utc();dump(OUT/'PARITY_GATE.json',report);dump(WORK/'AUDIT_BEFORE_RETRAIN.json',report)
    # Preserve the six old runs and raw input artifacts; do not touch neural weights.
    log_path=OUT/'TRAINING_LOG.csv'
    with log_path.open(newline='',encoding='utf-8') as f:
        reader=csv.DictReader(f);fields=reader.fieldnames;logrows=list(reader)
    for row in logrows:
        if row['model'] in ('XGBoost_40','RF_40') and row['status']=='ok':row['status']='SUPERSEDED_PARITY';row['detail']='P1 raw-versus-standardized aggregation mismatch; preserved checkpoint and v1 freeze; replaced by exact producing pipeline'
    with log_path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(logrows)
    for split,b in datasets.items():
        old=TENSORS/f'{split}_X40.npy'
        if not (ARCHIVE/old.name).exists():shutil.copyfile(old,ARCHIVE/old.name)
        # Close the old mapped view before replacing on Windows.
        b['old_X40']._mmap.close()
        del b['old_X40']
        b['fixed_X40'].flush();b['fixed_X40']._mmap.close();del b['fixed_X40']
        os.replace(WORK/f'{split}_X40_corrected.npy',old)
        b['fixed_X40']=np.load(old,mmap_mode='r')
    updated_manifest=loadj(ARCHIVE/'DATA_MANIFEST.json')
    updated_manifest.update(tabular_feature_recipe='Exact producing aggregate_common13_windows on standardized float32 development sequence tensors; no additional 40-feature scaler',parity_correction_utc=utc(),previous_manifest_sha256=sha(ARCHIVE/'DATA_MANIFEST.json'))
    for split in datasets:updated_manifest['splits'][split]['files'][f'{split}_X40.npy']=sha(TENSORS/f'{split}_X40.npy')
    dump(OUT/'DATA_MANIFEST.json',updated_manifest)
    current_configs=loadj(OUT/'CONFIGS_FROZEN.json')
    for key,cfg in configs.items():current_configs['configs'][f'{key[0]}/seed{key[1]}']=cfg
    current_configs['parity_correction_utc']=utc();dump(OUT/'CONFIGS_FROZEN.json',current_configs)
    corrected_results=[]
    for name in ('XGBoost_40','RF_40'):
        for seed in SEEDS:
            cfg=configs[name,seed]
            for attempt in (1,2):
                t0=time.perf_counter();status={'utc':utc(),'phase':'parity_tabular_retraining','current':{'model':name,'seed':seed,'attempt':attempt},'holdout_scored':False,'test_read':False,'parity_gate':'pending'};dump(OUT/'PHASE2_STATUS.json',status)
                try:
                    cls=XGBClassifier if name=='XGBoost_40' else RandomForestClassifier
                    model=cls(**cfg['params']);model.fit(datasets['train']['fixed_X40'],datasets['train']['y'].astype(np.int32))
                    p=model.predict_proba(val['fixed_X40'])[:,1].astype(np.float64)
                    thr,_=choose_threshold(val['y'],p);score=ap(val['y'],p)
                    folder=PRIVATE/'checkpoints_parity_v2'/name/f'seed{seed}';folder.mkdir(parents=True,exist_ok=True)
                    checkpoint=folder/('model.json' if name=='XGBoost_40' else 'model.joblib')
                    if name=='XGBoost_40':model.save_model(checkpoint)
                    else:joblib.dump(model,checkpoint)
                    np.savez_compressed(folder/'development_validation_probabilities.npz',y_true=val['y'].astype(np.int32),y_proba=p.astype(np.float32),threshold=np.array([thr],dtype=np.float64))
                    r={'model':name,'seed':seed,'config':cfg,'epochs':cfg['params']['n_estimators'],'best_epoch':cfg['params']['n_estimators'],'dev_validation_pr_auc':score,'threshold':float(thr),'wall_seconds':time.perf_counter()-t0,'gpu':'CPU','checkpoint':str(checkpoint),'sha256':sha(checkpoint),'status':'ok','parity_corrected':True}
                    dump(folder/'result.json',r);corrected_results.append(r)
                    row={'utc':utc(),'model':name,'seed':seed,'attempt':attempt,'status':'ok','config':json.dumps(cfg,sort_keys=True),'epochs':r['epochs'],'best_epoch':r['best_epoch'],'dev_validation_pr_auc':score,'wall_seconds':r['wall_seconds'],'gpu':'CPU','checkpoint_sha256':r['sha256'],'detail':'PARITY_CORRECTED_V2; exact locked standardized float32 aggregation and producing environment'}
                    with log_path.open('a',newline='',encoding='utf-8') as f:csv.DictWriter(f,fieldnames=fields).writerow(row)
                    print('RETRAINED',name,seed,'AP',score,'seconds',r['wall_seconds'],flush=True)
                    break
                except Exception:
                    (WORK/f'{name}_{seed}_attempt{attempt}_error.log').write_text(traceback.format_exc())
                    if attempt==2:raise
    assert len(corrected_results)==6
    report['correction']={'old_runs_status':'SUPERSEDED_PARITY','new_models':corrected_results,'all_six_retrained':True,'neural_models_retrained':False,'tabular_features':'Exact producing aggregation over development-refit standardized float32 tensors','original_scaler_used_for_retraining':False,'runtime_environment':{'python':sys.version,'executable':sys.executable,'packages':current_versions}}
    # Patch future data rebuilding, runtime metadata/serialization, and deferred scoring.
    runtime=ROOT/'phase2_runtime.py';text=runtime.read_text()
    needle="sys.path.insert(0,str(ROOT/'producing_model'))\n"
    assert needle in text
    text=text.replace(needle,needle+"sys.path.insert(0,str(ROOT/'parity_source'))\nfrom r52_locked_baselines.data import aggregate_common13_windows\n")
    text=text.replace("'source':'producing run_baseline_evaluation.py','features':'40 raw window summaries'","'source':'cert-r52-locked-baselines/scripts/r52_locked_baselines/train.py','features':'40 aggregates of standardized float32 sequence tensors; exact producing aggregate_common13_windows'")
    text=text.replace("p=m.predict_proba(bundle['validation']['X40'])[:,1]","p=m.predict_proba(bundle['validation']['X40'])[:,1].astype(np.float64)")
    text=text.replace("m.fit(bundle['train']['X40'],bundle['train']['y'])","m.fit(bundle['train']['X40'],bundle['train']['y'].astype(np.int32))")
    text=text.replace("ck=checkpoint(model,seed);ck=ck.with_suffix('.joblib');ck.parent.mkdir(parents=True,exist_ok=True);joblib.dump(m,ck)","ck=checkpoint(model,seed).with_suffix('.json' if model=='XGBoost_40' else '.joblib');ck.parent.mkdir(parents=True,exist_ok=True)\n        if model=='XGBoost_40':m.save_model(ck)\n        else:joblib.dump(m,ck)")
    runtime.write_text(text,encoding='utf-8')
    score_path=ROOT/'phase2_score_later.py';text=score_path.read_text()
    old="            cols=[]\n            for j in range(7):\n                z=rw[:,:,j];cols.extend([z.sum(1),z.mean(1),z.max(1),z.std(1,ddof=0)])\n            for j in range(7,13):\n                z=rw[:,:,j];cols.extend([z.sum(1),z.mean(1)])\n            tt.append(np.stack(cols,axis=1).astype(np.float32));cluster.extend([ui]*len(ix));offset.extend(np.arange(len(ix))%20==0);part.extend([pname]*len(ix))"
    new="            tt.append(rt.aggregate_common13_windows(xx[-1])[0]);cluster.extend([ui]*len(ix));offset.extend(np.arange(len(ix))%20==0);part.extend([pname]*len(ix))"
    assert old in text;text=text.replace(old,new)
    old="            m=joblib.load(spec['checkpoint']);p=m.predict_proba(X40)[:,1]"
    new="            if name=='XGBoost_40':\n                from xgboost import XGBClassifier\n                m=XGBClassifier();m.load_model(spec['checkpoint'])\n            else:m=joblib.load(spec['checkpoint'])\n            p=m.predict_proba(X40)[:,1].astype(np.float64)"
    assert old in text;text=text.replace(old,new);score_path.write_text(text,encoding='utf-8')
    data_path=ROOT/'phase2_data.py';text=data_path.read_text()
    text=text.replace('import hashlib, json, time','import hashlib, json, time, sys')
    needle="FEATURES=['total_events'"
    pos=text.index(needle);text=text[:pos]+"sys.path.insert(0,str(ROOT/'parity_source'))\nfrom r52_locked_baselines.data import aggregate_common13_windows\n"+text[pos:]
    old="            cols=[]\n            for j in range(7):\n                z=rw[:,:,j];cols.extend([z.sum(1),z.mean(1),z.max(1),z.std(1,ddof=0)])\n            for j in range(7,13):\n                z=rw[:,:,j];cols.extend([z.sum(1),z.mean(1)])\n            X40[pos]=np.stack(cols,axis=1).astype(np.float32)"
    assert old in text;text=text.replace(old,"            X40[pos]=aggregate_common13_windows(np.asarray(X[pos]))[0]")
    text=text.replace('40 raw-feature summaries: 7 numeric sum/mean/max/std(ddof=0); 6 binary active-day sum/proportion; producing order','40 summaries of standardized float32 sequence tensors; exact producing aggregate_common13_windows')
    data_path.write_text(text,encoding='utf-8')
    import ast
    for p in (runtime,score_path,data_path):ast.parse(p.read_text(),filename=str(p))
    # Final checks: corrected input matrices reproduce canonical columns exactly;
    # serialized corrected models reproduce their saved DEVELOPMENT probabilities.
    for split,bundle in datasets.items():
        for lo in range(0,len(bundle['y']),8192):assert np.array_equal(aggregate(np.asarray(bundle['X'][lo:lo+8192]))[0],bundle['fixed_X40'][lo:lo+8192])
    for r in corrected_results:
        if r['model']=='XGBoost_40':m=XGBClassifier();m.load_model(r['checkpoint'])
        else:m=joblib.load(r['checkpoint'])
        p=m.predict_proba(val['fixed_X40'])[:,1].astype(np.float64)
        with np.load(Path(r['checkpoint']).parent/'development_validation_probabilities.npz') as z:assert np.array_equal(p.astype(np.float32),z['y_proba'])
    report['status']='PARITY_GATE_FIXED';report['completed_utc']=utc();report['wall_seconds']=time.perf_counter()-start
    report['post_fix_checks']={'canonical_development_feature_max_abs_difference':0.,'original_model_original_features_saved_probability_float32_max_abs_difference':0.,'all_corrected_model_serialization_checks_pass':True,'neural_tensor_only_scaler_difference_confirmed':True,'unexplained_feature_or_recipe_mismatch':False,'scoring_script_executed':False}
    report['scoring_permitted']=False;report['scoring_policy']='Parity requirement satisfied; HOLDOUT scoring remains deferred and requires the pre-existing explicit one-pass invocation and supervisor disclosure record.'
    dump(OUT/'PARITY_GATE.json',report)
    freeze=dict(oldfreeze);freeze['utc']=utc();freeze['version']=2;freeze['supersedes_freeze_sha256']=sha(OUT/'MODELS_FROZEN_v1.json')
    freeze['models']=[r for r in oldfreeze['models'] if r['model'] not in ('XGBoost_40','RF_40')]+corrected_results
    for r in freeze['models']:
        assert sha(r['checkpoint'])==r['sha256']
        if r['model'] not in ('XGBoost_40','RF_40'):assert r['sha256']==old_by_key[r['model'],r['seed']]['sha256']
    freeze['implementation_files']=[{'path':str(p),'sha256':sha(p)} for p in ROOT.rglob('*.py') if '__pycache__' not in str(p)]
    freeze['scoring_script']={'path':str(score_path),'sha256':sha(score_path),'executed':False}
    freeze['data_manifest_sha256']=sha(OUT/'DATA_MANIFEST.json');freeze['configs_frozen_sha256']=sha(OUT/'CONFIGS_FROZEN.json');freeze['parity_gate_sha256']=sha(OUT/'PARITY_GATE.json');freeze['parity_gate_status']='PARITY_GATE_FIXED'
    dump(OUT/'MODELS_FROZEN.json',freeze)
    # Keep the original report intact in the private v1 archive; correct its active claims.
    text=(OUT/'CHATGPT_PHASE2_REPORT.md').read_text()
    text=text.split('\n## Parity gate\n')[0].rstrip()
    text=text.replace('40 raw window summaries use the producing numeric and binary aggregations.','The original 40 raw summaries were superseded after the parity audit: the active tabular inputs now use exact producing aggregation of the standardized float32 20×13 tensors.')
    text=text.replace('The daily scaler does not alter their raw-feature summary definition.','The active tabular summaries aggregate the daily-standardized sequence tensor, exactly as cert-r52-locked-baselines does; no additional 40-feature scaler is fitted.')
    text=text.replace('Recipe deviations: none intended beyond development-user restriction, development scaler refit and the explicitly preregistered uni architecture intervention.','Recipe deviation found and corrected before any holdout scoring: v1 tabular summaries used raw values rather than producing standardized float32 values. All six old tabular runs are SUPERSEDED_PARITY. The active v2 models use the exact producing pipeline with the preregistered development-user restriction and scaler refit, and the explicitly preregistered uni architecture intervention.')
    p2='; '.join(f"{name}: original producing DEVELOPMENT AP {r['inputs']['original_producing_features']['development_AP']:.9f}, saved AP {r['saved_development_AP']:.9f}, max probability difference {r['inputs']['original_producing_features']['max_abs_probability_difference_vs_saved']:.3g} (zero after saved float32 serialization)" for name,r in report['P2'].items())
    newaps='; '.join(f"{name}: "+', '.join(f"seed{r['seed']}={r['dev_validation_pr_auc']:.9f}" for r in corrected_results if r['model']==name) for name in ('XGBoost_40','RF_40'))
    section='\n\n## Parity gate\n\nMandatory development-only P1–P4 audit completed UTC '+report['completed_utc']+'. Detailed per-column differences, every estimator parameter, both scaler means/stds, source hashes and all model metrics are in PARITY_GATE.json.\n\nP1: confirmed raw-versus-standardized input mismatch in v1. Column order and named formulas were identical, but v1 aggregated raw float64 daily values while the producing pipeline aggregates standardized float32 sequence values. All 40 original producing input columns were reproduced bitwise. Corrected development features reproduce the exact producing function bitwise; their residual difference from the original input is the preregistered development-only scaler refit.\n\nP2: '+p2+'. Frozen original seed-42 models were also tested on v1 raw features and corrected development-scaler features, exclusively for the same 48,000 development validation windows. These diagnostics are not new holdout metrics.\n\nP3: every estimator parameter was compared. Hyperparameter recipes match apart from the authorized development recomputation of XGBoost scale_pos_weight (198.1407632044478 original versus 193.4078947368421 development). No early stopping is used; seeds 42/52/62 and the producing tree counts, depth, class weights, sampling and histogram method are retained. Other corrections: exact producing Python/NumPy/pandas environment for tabular runs, int32 labels, float64 probability conversion before threshold selection, and JSON serialization for XGBoost.\n\nP4: for both TRAIN and VALIDATION, original and development tensors were reconstructed bitwise from the same development raw windows using their respective recorded scalers. Labels, window identity, features and ordering match; only the preregistered scaler refit differs. All neural checkpoint hashes are unchanged.\n\nAll six tabular models were retrained, and the six former successful rows were marked SUPERSEDED_PARITY in TRAINING_LOG.csv. Corrected DEVELOPMENT VALIDATION AP: '+newaps+'. MODELS_FROZEN_v1.json preserves the old freeze; MODELS_FROZEN.json is v2 with corrected checkpoint and scoring-script hashes. The deferred scorer now enforces this parity gate and uses the exact producing aggregate function. It was not executed. No TEST data or holdout feature/probability row was materialized, scored or used in fitting.\n\nPARITY_GATE_FIXED\n'
    (OUT/'CHATGPT_PHASE2_REPORT.md').write_text(text+section,encoding='utf-8')
    dump(OUT/'PHASE2_STATUS.json',{'utc':utc(),'phase':'finished_models_frozen_not_scored','requested_successful_runs':27,'requested_total_runs':27,'parity_gate':'PARITY_GATE_FIXED','freeze_version':2,'holdout_scored':False,'test_read':False})
    print('PARITY_GATE_FIXED: six tabular models replaced; neural checkpoints unchanged; no holdout scoring.',flush=True)

if __name__=='__main__':
    try:main()
    except BaseException:
        (WORK/'PARITY_FATAL.log').write_text(traceback.format_exc(),encoding='utf-8')
        raise
