"""Reviewed-gate Phase 2 local campaign: 72 registered fits, pause and resume."""
import os
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
import argparse
import copy
from datetime import datetime,timezone
import gc
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

import numpy as np
import psutil
import torch
from sklearn.metrics import average_precision_score

from contracts import Checkpoints,atomic_json,cpu,digest,initialize_odst,initialization_indices,replace,reset_rng,sha,state_hash
from control import Control,Paused,now
from data import ROOT,TRAIN,VAL,SCHEMAS,SEEDS,Dataset,input_records,read
from models import build,copy_encoder,configure_model,optimizer,loss,training_seed,verify_vendor

BASE=Path(__file__).resolve().parent
PROTOCOL=BASE.parent/'PROTOCOL_DRAFT_v0.6.md'
EVIDENCE=BASE.parent/'SOURCE_EVIDENCE_v0.6.json'
TEST_RECORD=BASE.parent/'synthetic_v0_6_final/VERIFICATION.json'
DEVICE='cuda:0'
BATCH_SIZE=1024
MAX_EPOCHS=30
CHECKPOINT_EVERY=25
def event(name,**fields):
    pass  # Production no-op; synthetic tests inject pause requests at this seam.


def source_identity():
    return {str(p.relative_to(BASE)):sha(p) for p in sorted(BASE.rglob('*')) if p.suffix in ('.py','.json') and p.is_file()}

def runtime():
    import sklearn
    packages=sorted(subprocess.run([sys.executable,'-m','pip','freeze','--all'],capture_output=True,text=True,check=True).stdout.splitlines())
    driver=subprocess.run(['nvidia-smi','--query-gpu=uuid,name,driver_version','--format=csv,noheader'],capture_output=True,text=True,check=True).stdout.strip()
    if not torch.cuda.is_available():raise RuntimeError('Locked CUDA device unavailable')
    return dict(python=sys.version,executable=sys.executable,torch=torch.__version__,numpy=np.__version__,sklearn=sklearn.__version__,
                cuda=torch.version.cuda,cudnn=torch.backends.cudnn.version(),gpu_driver=driver,platform=sys.platform,
                windows_version=str(sys.getwindowsversion()) if sys.platform=='win32' else None,package_freeze=packages,package_freeze_sha256=digest(packages),stage1_stack_note='Different system-Python stack from Stage 1 conda environment')

def configure():
    if os.environ['CUBLAS_WORKSPACE_CONFIG']!=':4096:8':raise RuntimeError('CUDA determinism workspace mismatch')
    torch.set_num_threads(4);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark=False;torch.backends.cudnn.deterministic=True
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False

def run_path(name):
    if not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in name):raise ValueError('Run ID')
    return ROOT/'experiment_runs'/name

def registered_fits():
    return [dict(id=f'{partition}_{condition}_{schema}_seed{seed}',partition=partition,condition=condition,schema=schema,seed=seed)
            for partition in ('inner','outer') for schema in SCHEMAS for condition in ('L','T','C','G') for seed in SEEDS]

def verify_gate(run,manifest,full_inputs=False):
    if sha(run/'MANIFEST.json')!=read(run/'MANIFEST_IDENTITY.json')['sha256']:raise RuntimeError('Manifest bytes changed')
    if manifest['sources']!=source_identity() or manifest['protocol_sha256']!=sha(PROTOCOL):raise RuntimeError('Source/protocol drift')
    if manifest['evidence_sha256']!=sha(EVIDENCE) or manifest['test_record_sha256']!=sha(TEST_RECORD):raise RuntimeError('Evidence/test record drift')
    if manifest['runtime']!=runtime():raise RuntimeError('Runtime/device/driver drift; resume prohibited')
    if full_inputs and manifest['inputs']!=input_records():raise RuntimeError('Saved input drift')
    verify_vendor()

def prepare(run):
    if not (ROOT/'experiment_runs/campaign_20261007_r1/COMPLETE.json').exists():raise RuntimeError('Stage 1 completion required')
    tests=read(TEST_RECORD)
    if tests['unit_test_exit_code']!=0 or any(v!='EXACT_MODEL_OPTIMIZER_LOSS_RNG_PARITY' for v in tests['fresh_process']['results'].values()):raise RuntimeError('Synthetic verification gates failed')
    if tests['source_hashes']!=source_identity():raise RuntimeError('Executable sources differ from tested sources')
    run.mkdir(exist_ok=False)
    inputs=input_records();checks=[]
    for partition in ('inner','outer'):
        for schema in SCHEMAS:
            data=Dataset(schema,partition)
            # Bounded preflight shape/order check, not inference or training.
            x=data.batch([0,len(data.y)-1]);keys=data.keys()
            if x.shape!=(2,20,len(data.columns)):raise RuntimeError('Window layout')
            if len(np.unique(keys['sequence_id']))!=len(data.ye):raise RuntimeError('Duplicate canonical sequence keys')
            checks.append(dict(**data.identity(),windows=len(data.y),positives=int(data.y.sum()),eval_windows=len(data.ye),eval_positives=int(data.ye.sum())))
    manifest=dict(scope='CERT_STUDY',created_utc=now(),status='IMPLEMENTATION_REVIEW_PREPARED_NO_TRAINING',sources=source_identity(),protocol_sha256=sha(PROTOCOL),evidence_sha256=sha(EVIDENCE),test_record_sha256=sha(TEST_RECORD),
        runtime=runtime(),inputs=inputs,preflight=checks,registered_fits=registered_fits(),fit_budget=72,schemas=list(SCHEMAS),seeds=list(SEEDS),
        max_epochs=30,patience=4,batch_size=1024,checkpoint_every_updates=25,checkpoint_retention='last 3 step + last 2 epoch + last 3 phase/pause/final; at most 8 states',
        label_task='ANY_DAY_COMPLETED_WINDOW_T20',test_access=False,student_stream='student',epoch_policy='T min4; shared outer C/G=max rounded medians',
        operations_ack_required=True,independent_implementation_review_required=True)
    atomic_json(run/'MANIFEST.json',manifest);atomic_json(run/'MANIFEST_IDENTITY.json',dict(sha256=sha(run/'MANIFEST.json')))
    atomic_json(run/'PREFLIGHT.json',dict(status='SAVED_ARRAY_PREFLIGHT_PASSED',new_model_fits=0,inference=False,test_access=False,checks=checks,
        free_disk_bytes=shutil.disk_usage(run).free,raw_event_parity_independently_reproduced=False))
    print('PREPARED FOR INDEPENDENT IMPLEMENTATION REVIEW: '+str(run),flush=True)

def complete_fit(folder):
    done=read(folder/'COMPLETE.json')
    if done['identity_sha256']!=digest(read(folder/'RUN_IDENTITY.json')):raise RuntimeError('Completed identity drift')
    for name,checksum in done['artifacts'].items():
        if sha(folder/name)!=checksum:raise RuntimeError('Completed artifact drift: '+name)
    return read(folder/'RESULT.json')

def model_file(folder):
    complete_fit(folder)
    return torch.load(folder/'MODEL.pt',map_location='cpu',weights_only=True)

def predict(model,data,control,evaluation=True,pause_callback=None):
    count=len(data.ye) if evaluation else len(data.y);out=np.empty(count,dtype='float64');model.eval()
    with torch.no_grad():
        for begin in range(0,count,BATCH_SIZE):
            event('prediction_chunk',evaluation=evaluation,begin=begin)
            if control.requested():
                if pause_callback:pause_callback()
                control.paused(reason='Prediction/target generation interrupted; partial array discarded')
            end=min(begin+BATCH_SIZE,count);x=torch.from_numpy(data.batch(np.arange(begin,end),evaluation)).to(DEVICE)
            logits,_=model(x);out[begin:end]=logits.cpu().double().numpy()
    if not np.isfinite(out).all():raise RuntimeError('Nonfinite model logits')
    return out

def teacher_cache(run,data,control):
    cache=run/f'{data.partition}_teacher_ensemble_{data.schema}';cache.mkdir(exist_ok=True)
    teachers=[run/f'{data.partition}_T_{data.schema}_seed{s}' for s in SEEDS]
    for f in teachers:complete_fit(f)
    binding=dict(data=data.identity(),manifest_sha256=sha(run/'MANIFEST.json'),teachers=[sha(f/'MODEL.pt') for f in teachers])
    if (cache/'COMPLETE.json').exists():
        rec=read(cache/'COMPLETE.json')
        if rec['binding']!=binding:raise RuntimeError('Teacher ensemble binding drift')
        for n,h in rec['artifacts'].items():
            if sha(cache/n)!=h:raise RuntimeError('Teacher cache corrupt')
        return np.load(cache/'TRAIN_LOGITS.npy',mmap_mode='r',allow_pickle=False)
    mean_train=np.zeros(len(data.y),dtype='float64');mean_eval=np.zeros(len(data.ye),dtype='float64')
    for seed,folder in zip(SEEDS,teachers):
        event('teacher_cache',schema=data.schema,partition=data.partition,seed=seed)
        model=build(data.schema,len(data.columns),data.partition,seed,'T');model.load_state_dict(model_file(folder),strict=True);model.to(DEVICE)
        mean_train+=predict(model,data,control,False)/3;mean_eval+=predict(model,data,control,True)/3
        del model;gc.collect();torch.cuda.empty_cache()
    for name,array in [('TRAIN_LOGITS.npy',mean_train.astype('float32')),('EVAL_LOGITS.npy',mean_eval)]:
        with (cache/(name+'.tmp')).open('wb') as f:np.save(f,array,allow_pickle=False);f.flush();os.fsync(f.fileno())
        replace(cache/(name+'.tmp'),cache/name)
    probabilities=1/(1+np.exp(-mean_eval))
    atomic_json(cache/'RESULT.json',dict(average_precision=float(average_precision_score(data.ye,probabilities)),reference='sigmoid of mean canonical teacher logits',threshold=None,fit_count=0))
    atomic_json(cache/'COMPLETE.json',dict(binding=binding,artifacts={n:sha(cache/n) for n in ['TRAIN_LOGITS.npy','EVAL_LOGITS.npy','RESULT.json']},new_fits=0))
    return np.load(cache/'TRAIN_LOGITS.npy',mmap_mode='r',allow_pickle=False)

def metric_functions():
    # An exact recorded copy of Stage 1 pure metric functions, not an import from its runner.
    from metrics import f1_threshold,metrics
    return f1_threshold,metrics

def fit(run,manifest,job,data,control,outer_epochs=None,targets=None,threshold=None):
    folder=run/job['id'];folder.mkdir(exist_ok=True)
    if (folder/'COMPLETE.json').exists():return complete_fit(folder)
    if shutil.disk_usage(run).free<20*1024**3:raise RuntimeError('Less than 20 GiB free before fit')
    condition=job['condition'];seed=job['seed'];model=build(data.schema,len(data.columns),data.partition,seed,condition)
    construction_hash=state_hash(model);dependencies={};init_report=None
    if condition=='T':
        precursor=run/f'{data.partition}_L_{data.schema}_seed{seed}'
        dependencies['precursor']=sha(precursor/'COMPLETE.json');copy_encoder(model,model_file(precursor))
        indexes=initialization_indices(len(data.y),data.schema,data.partition,seed);contexts=[];model.eval();model.to(DEVICE)
        with torch.no_grad():
            for start in range(0,len(indexes),BATCH_SIZE):
                z,_=model.encode_attention_h(torch.from_numpy(data.batch(indexes[start:start+BATCH_SIZE])).to(DEVICE));contexts.append(z.cpu())
        model.cpu();init_report=initialize_odst(model,torch.cat(contexts),data.schema,data.partition,seed)
        dependencies['init_sample_sha256']=__import__('hashlib').sha256(indexes.tobytes()).hexdigest()
    elif condition in ('C','G'):
        teacher=run/f'{data.partition}_T_{data.schema}_seed{seed}'
        dependencies['teacher']=sha(teacher/'COMPLETE.json');model.load_state_dict(model_file(teacher),strict=True)
        cache=run/f'{data.partition}_teacher_ensemble_{data.schema}'
        dependencies['ensemble']=sha(cache/'COMPLETE.json')
    identity=dict(**job,data=data.identity(),manifest_sha256=sha(run/'MANIFEST.json'),construction_state_sha256=construction_hash,
        starting_state_sha256=state_hash(model),dependencies=dependencies,outer_epochs=outer_epochs,threshold=threshold,
        training_rng_seed=training_seed(data.schema,data.partition,seed,condition))
    if (folder/'RUN_IDENTITY.json').exists():
        if read(folder/'RUN_IDENTITY.json')!=identity:raise RuntimeError('Fit identity changed before resume')
    else:atomic_json(folder/'RUN_IDENTITY.json',identity)
    if init_report is not None and not (folder/'INITIALIZATION.json').exists():atomic_json(folder/'INITIALIZATION.json',init_report)
    model.to(DEVICE);opt=optimizer(model,condition,1);reset_rng(identity['training_rng_seed'])
    rng=np.random.Generator(np.random.PCG64(identity['training_rng_seed']));store=Checkpoints(folder/'checkpoints',identity)
    progress=dict(epoch=1,next_batch=0,phase='train',epoch_rng_state=None,permutation_sha256=None,best_state=None,best_ap=None,
        best_epoch=None,stale=0,history=[],loss_sum=0.,seen=0,fit_finished=False,phase_optimizer_epoch=1,updates=0,compute_seconds=0.)
    resumed=store.exists()
    if resumed:
        progress,opt=store.load(model,opt,rng,optimizer_factory=lambda saved:optimizer(model,condition,saved['phase_optimizer_epoch']))
    elif any((folder/'checkpoints').glob('state_*.pt')):raise RuntimeError('Uncommitted partial fit; explicit recovery required')
    else:store.save(model,opt,progress,rng,'phase')
    def segment_record(record):
        with (folder/'PROCESS_SEGMENTS.jsonl').open('a',encoding='utf-8',newline='\n') as f:f.write(json.dumps(record)+'\n');f.flush();os.fsync(f.fileno())
    segment_record(dict(event='START',started_utc=now(),pid=os.getpid(),resume=resumed,score_used=False,resumed_from_sequence=store.state_parent['sequence'] if resumed else None,updates_at_resume=progress['updates']))
    cap=outer_epochs or MAX_EPOCHS;positive_weight=.25*(len(data.y)-int(data.y.sum()))/int(data.y.sum())
    if DEVICE.startswith('cuda'):torch.cuda.reset_peak_memory_stats()
    rss=0
    def pause_fit():
        pointer=store.save(model,opt,progress,rng,'pause');segment_record(dict(event='PAUSED',pid=os.getpid(),updates_at_end=progress['updates'],checkpoint_sequence=pointer['sequence']));control.paused(fit=job['id'],checkpoint=pointer,score_used=False)
    while not progress['fit_finished']:
        if control.requested():pause_fit()
        epoch=progress['epoch'];configure_model(model,condition,epoch)
        if condition=='T' and epoch>=4 and progress['phase_optimizer_epoch']==1:
            event('warmup_transition',fit=job['id'],epoch=epoch)
            if control.requested():pause_fit()
            opt=optimizer(model,condition,4);progress['phase_optimizer_epoch']=4;store.save(model,opt,progress,rng,'phase')
        if progress['epoch_rng_state'] is None:
            progress['epoch_rng_state']=copy.deepcopy(rng.bit_generator.state);order=rng.permutation(len(data.y))
            progress['permutation_sha256']=__import__('hashlib').sha256(order.tobytes()).hexdigest()
            store.save(model,opt,progress,rng,'epoch')
        else:
            replay=np.random.Generator(np.random.PCG64());replay.bit_generator.state=progress['epoch_rng_state'];order=replay.permutation(len(data.y))
            if __import__('hashlib').sha256(order.tobytes()).hexdigest()!=progress['permutation_sha256']:raise RuntimeError('Permutation drift')
        control.publish('RUNNING',fit=job['id'],epoch=epoch,next_batch=progress['next_batch'])
        for batch in range(progress['next_batch'],math.ceil(len(order)/BATCH_SIZE)):
            event('training_batch',fit=job['id'],epoch=epoch,batch=batch)
            if control.requested():pause_fit()
            started=time.monotonic();idx=order[batch*BATCH_SIZE:(batch+1)*BATCH_SIZE]
            x=torch.from_numpy(data.batch(idx)).to(DEVICE);label=torch.from_numpy(data.y[idx].astype('float32')).to(DEVICE)
            opt.zero_grad(set_to_none=True)
            masks=[];handle=None
            if condition in ('C','G') and epoch==1 and batch==0:
                handle=model.dropout.register_forward_hook(lambda module,inputs,output:masks.append(__import__('hashlib').sha256(((output.detach()==0)&(inputs[0].detach()!=0)).cpu().numpy().tobytes()).hexdigest()))
            logit,_=model(x)
            if handle is not None:
                handle.remove()
                pairing=dict(starting_state_sha256=identity['starting_state_sha256'],training_rng_seed=identity['training_rng_seed'],first_permutation_sha256=progress['permutation_sha256'],first_batch_dropout_mask_sha256=masks)
                pairing_path=folder/'PAIRING.json'
                if pairing_path.exists() and read(pairing_path)!=pairing:raise RuntimeError('First-batch pairing observation changed on replay')
                if not pairing_path.exists():atomic_json(pairing_path,pairing)
            target=torch.from_numpy(np.asarray(targets[idx],dtype='float32')).to(DEVICE) if condition=='G' else None
            value=loss(logit,label,positive_weight,target)
            if not torch.isfinite(value):raise RuntimeError('Nonfinite loss')
            value.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.);opt.step()
            progress['loss_sum']+=float(value.detach().cpu())*len(idx);progress['seen']+=len(idx)
            progress['next_batch']=batch+1;progress['updates']+=1;progress['compute_seconds']+=time.monotonic()-started
            rss=max(rss,psutil.Process().memory_info().rss)
            segment_record(dict(event='UPDATE_OBSERVED',pid=os.getpid(),updates=progress['updates']))
            event('update_completed',fit=job['id'],updates=progress['updates'],order_sha256=progress['permutation_sha256'])
            if progress['updates']%CHECKPOINT_EVERY==0:store.save(model,opt,progress,rng)
        record=dict(epoch=epoch,weighted_training_loss=progress['loss_sum']/progress['seen'],phase='warmup' if condition=='T' and epoch<=3 else 'joint')
        if data.partition=='inner':
            store.save(model,opt,progress,rng,'epoch')
            logits=predict(model,data,control,True,pause_fit);p=1/(1+np.exp(-logits));ap=float(average_precision_score(data.ye,p));record['inner_select_ap']=ap
            if condition!='T' or epoch>=4:
                if progress['best_ap'] is None or ap>progress['best_ap']:
                    progress.update(best_ap=ap,best_epoch=epoch,best_state=cpu(model.state_dict()),stale=0)
                else:progress['stale']+=1
        else:progress.update(best_epoch=epoch,best_state=cpu(model.state_dict()))
        progress['history'].append(record);print(job['id']+' '+json.dumps(record),flush=True)
        progress['fit_finished']=epoch>=cap or (data.partition=='inner' and progress['stale']>=4)
        progress.update(epoch=epoch+1,next_batch=0,epoch_rng_state=None,permutation_sha256=None,loss_sum=0.,seen=0)
        store.save(model,opt,progress,rng,'final' if progress['fit_finished'] else 'epoch')
    if progress['best_state'] is None:raise RuntimeError('No eligible checkpoint')
    model.load_state_dict(progress['best_state'],strict=True)
    logits=predict(model,data,control,True,pause_fit);probability=1/(1+np.exp(-logits))
    f1_threshold,measure=metric_functions();chosen=f1_threshold(data.ye,probability) if data.partition=='inner' else (float('inf') if threshold=='+infinity' else threshold)
    result=measure(data.ye,probability,chosen);result.update(**job,best_epoch=progress['best_epoch'],terminal_epoch=progress['epoch']-1,
        cap_hit=(progress['epoch']-1>=MAX_EPOCHS) if data.partition=='inner' else None,threshold_role='INNER_SELECT_CALIBRATED_DEVELOPMENT' if data.partition=='inner' else 'TRANSPORTED_THRESHOLD',
        evidence_role='NEW_DEVELOPMENT' if data.partition=='inner' else 'OUTCOME_EXPOSED_RETROSPECTIVE_VALIDATION')
    temp=folder/'MODEL.tmp';torch.save(cpu(model.state_dict()),temp);replace(temp,folder/'MODEL.pt')
    temp=folder/'PREDICTIONS.tmp'
    with temp.open('wb') as f:np.savez_compressed(f,probability=probability,logit=logits,label=data.ye,**data.keys())
    replace(temp,folder/'PREDICTIONS_LOCAL.npz')
    atomic_json(folder/'RESULT.json',result);atomic_json(folder/'TRAINING_HISTORY.json',progress['history'])
    atomic_json(folder/'COST.json',dict(optimizer_update_seconds=progress['compute_seconds'],sampled_process_rss_bytes=rss,
        peak_torch_cuda_allocated_bytes=torch.cuda.max_memory_allocated() if DEVICE.startswith('cuda') else 0,resource_scope='Last process segment only',cost_limit='Resume initialization and checkpoint/evaluation costs not included in optimizer-update time; process segments retained'))
    artifacts={n:sha(folder/n) for n in ['RUN_IDENTITY.json','MODEL.pt','PREDICTIONS_LOCAL.npz','RESULT.json','TRAINING_HISTORY.json','COST.json']}
    if condition in ('C','G'):artifacts['PAIRING.json']=sha(folder/'PAIRING.json')
    atomic_json(folder/'COMPLETE.json',dict(identity_sha256=digest(identity),artifacts=artifacts))
    segment_record(dict(event='COMPLETE',pid=os.getpid(),updates_at_end=progress['updates']))
    del model,opt;gc.collect();torch.cuda.empty_cache();return result

def operating_points(run,jobs):
    result={}
    for schema in SCHEMAS:
        result[schema]={}
        for condition in ('L','T','C','G'):
            values=[complete_fit(run/f'inner_{condition}_{schema}_seed{s}') for s in SEEDS]
            result[schema][condition]=dict(epochs=max(4 if condition=='T' else 1,min(30,math.ceil(np.median([v['best_epoch'] for v in values])))),thresholds={str(v['seed']):v['threshold'] for v in values})
        shared=max(result[schema]['C']['epochs'],result[schema]['G']['epochs']);result[schema]['C']['epochs']=shared;result[schema]['G']['epochs']=shared
    return result

def run_campaign(run):
    if (run/'COMPLETE.json').exists():raise RuntimeError('Completed campaign is immutable; refusing rerun')
    manifest=read(run/'MANIFEST.json');verify_gate(run,manifest,True)
    approval=read(run/'EXECUTION_APPROVAL.json');review=read(run/'IMPLEMENTATION_REVIEW.json');ops=read(run/'OPERATIONS_ACK.json')
    prelaunch=read(run/'PRE_LAUNCH_TESTS.json')
    for record in [approval,review,ops,prelaunch]:
        if record.get('manifest_sha256')!=sha(run/'MANIFEST.json'):raise RuntimeError('Approval/review/operations binding mismatch')
        if record.get('scope')!=manifest.get('scope'):raise RuntimeError('Execution scope mismatch; synthetic fixtures cannot approve CERT')
        if manifest.get('scope')!='SYNTHETIC_ONLY' and record.get('synthetic_gate_fixture'):raise RuntimeError('Synthetic gate fixture is not CERT execution evidence')
    report=Path(review['report_path']);findings=Path(review['findings_path'])
    if sha(report)!=review['report_sha256'] or sha(findings)!=review['findings_sha256']:raise RuntimeError('Independent review bytes changed')
    adjudication=read(findings)
    if manifest.get('scope')!='SYNTHETIC_ONLY' and adjudication.get('synthetic_gate_fixture'):raise RuntimeError('Synthetic review fixture cannot authorize CERT')
    if adjudication.get('verdicts',{}).get('EXECUTION')!='READY' or adjudication.get('execution_conditions_open')!=[]:raise RuntimeError('Independent review does not clear execution conditions')
    required={'orchestration_cpu','orchestration_cuda','cg_pairing','hard_kill_20','full_shape_cost','failure_paths'}
    if set(prelaunch['checks'])!=required or prelaunch.get('status')!='PASSED':raise RuntimeError('Required pre-launch checks missing')
    for name,record in prelaunch['checks'].items():
        evidence=Path(record['path'])
        if sha(evidence)!=record['sha256']:raise RuntimeError('Pre-launch evidence bytes changed')
        item=read(evidence)
        if manifest.get('scope')!='SYNTHETIC_ONLY' and item.get('synthetic_gate_fixture'):raise RuntimeError('Synthetic evidence fixture cannot authorize CERT')
        if item.get('status')!='PASSED' or item.get('source_hashes')!=manifest['sources']:raise RuntimeError('Pre-launch evidence not passed for these sources')
    if review.get('verdict')!='NO_BLOCKING_DEFECT_FOUND' or review.get('execution_verdict')!='READY' or any(c.get('status')!='CLOSED' for c in review['conditions']) or approval.get('authorized') is not True or ops.get('ready') is not True:raise RuntimeError('Execution gates not satisfied')
    if (run/'STATUS.json').exists() and read(run/'STATUS.json')['status']=='FAILED_RESERVED':
        recovery=read(run/'RESUME_AFTER_FAILURE.json')
        if recovery.get('authorized') is not True or recovery.get('manifest_sha256')!=sha(run/'MANIFEST.json') or recovery.get('failure_sha256')!=sha(run/'STATUS.json'):raise RuntimeError('Explicit failure-bound recovery authorization required')
    control=Control(run,manifest);control.acquire();control.clear_request()
    try:
        jobs=manifest['registered_fits']
        for partition in ('inner','outer'):
            verify_gate(run,manifest,True)
            if partition=='outer':
                points=read(run/'INNER_OPERATING_POINTS.json')
                for job in [j for j in jobs if j['partition']=='inner']:complete_fit(run/job['id'])
                if points!=operating_points(run,jobs):raise RuntimeError('Inner operating points changed')
                lock=dict(manifest_sha256=sha(run/'MANIFEST.json'),operating_points_sha256=sha(run/'INNER_OPERATING_POINTS.json'))
                if (run/'OUTER_ENTRY_LOCK.json').exists():
                    if read(run/'OUTER_ENTRY_LOCK.json')!=lock:raise RuntimeError('Outer entry lock drift')
                else:atomic_json(run/'OUTER_ENTRY_LOCK.json',lock)
            for schema in SCHEMAS:
                data=Dataset(schema,partition)
                for condition in ('L','T','C','G'):
                    targets=teacher_cache(run,data,control) if condition in ('C','G') else None
                    for job in [j for j in jobs if (j['partition'],j['schema'],j['condition'])==(partition,schema,condition)]:
                        event('fit_boundary',fit=job['id'])
                        if control.requested():control.paused(reason='Fit boundary')
                        fit(run,manifest,job,data,control,points[schema][condition]['epochs'] if partition=='outer' else None,targets,
                            points[schema][condition]['thresholds'][str(job['seed'])] if partition=='outer' else None)
                del data;gc.collect()
            if partition=='inner':
                calculated=operating_points(run,jobs)
                if (run/'INNER_OPERATING_POINTS.json').exists():
                    if read(run/'INNER_OPERATING_POINTS.json')!=calculated:raise RuntimeError('Operating point drift')
                else:atomic_json(run/'INNER_OPERATING_POINTS.json',calculated)
        from analysis import analyze
        analyze(run,manifest,control)
        for job in jobs:complete_fit(run/job['id'])
        verify_gate(run,manifest,True)
        if len(jobs)!=72:raise RuntimeError('Registered count mismatch')
        fits={j['id']:sha(run/j['id']/'COMPLETE.json') for j in jobs}
        segments={j['id']:sum(json.loads(line).get('event')=='START' for line in (run/j['id']/'PROCESS_SEGMENTS.jsonl').read_text().splitlines()) for j in jobs}
        ensembles={f'{p}_{s}':sha(run/f'{p}_teacher_ensemble_{s}'/'COMPLETE.json') for p in ('inner','outer') for s in SCHEMAS}
        atomic_json(run/'COMPLETE.json',dict(status='PHASE2_COMPLETE',logical_fit_count=len(fits),finished_utc=now(),analysis_sha256=sha(run/'ANALYSIS.json'),test_access=False,per_fit_complete_hashes=fits,process_segment_counts=segments,ensemble_complete_hashes=ensembles))
        control.finish('COMPLETE',completed_logical_fits=72)
    except Paused:print('PAUSED; reservation retained. Safe to shut down after this status.',flush=True)
    except BaseException as exc:
        control.finish('FAILED_RESERVED',error=str(exc),traceback=traceback.format_exc());raise

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','pause','status']);p.add_argument('--run-id',required=True);args=p.parse_args()
    run=run_path(args.run_id)
    if args.action=='pause':atomic_json(run/'PAUSE_REQUEST.json',dict(requested_utc=now()));print('Pause requested; wait for PAUSED before shutdown.');return
    if args.action=='status':print(json.dumps(read(run/('STATUS.json' if (run/'STATUS.json').exists() else 'PREFLIGHT.json')),indent=2));return
    configure()
    if args.action=='prepare':prepare(run)
    else:run_campaign(run)

if __name__=='__main__':main()
