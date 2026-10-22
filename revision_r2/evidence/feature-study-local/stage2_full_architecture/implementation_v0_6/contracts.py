"""Fixed random streams and bounded, identity-bound continuation generations."""
import copy
import hashlib
import json
import os
import pickle
from pathlib import Path
import random
import re
import shutil
import time
import uuid

import numpy as np
import torch

def atomic_stage(name,path):
    pass  # Synthetic subprocess tests inject interruption here; production is a no-op.

class ObservedWriter:
    def __init__(self,file,event,path):self.file=file;self.event=event;self.path=path;self.observed=False
    def __getattr__(self,name):return getattr(self.file,name)
    def write(self,data):
        result=self.file.write(data)
        if not self.observed:
            self.observed=True;self.file.flush();atomic_stage(self.event,self.path)
        return result


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def atomic_json(path,value):
    path=Path(path);temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temp.open('w',encoding='utf-8') as f:
        if path.name=='CHECKPOINT_POINTER.json':
            writer=ObservedWriter(f,'pointer_write',temp);json.dump(value,writer,indent=2,allow_nan=False)
        else:json.dump(value,f,indent=2,allow_nan=False)
        f.write('\n');f.flush();os.fsync(f.fileno())
        if path.name=='CHECKPOINT_POINTER.json':atomic_stage('pointer_fsynced',temp)
    replace(temp,path)
    if path.name=='CHECKPOINT_POINTER.json':atomic_stage('pointer_published',path)


def replace(source,destination):
    for attempt in range(6):
        try:os.replace(source,destination);return
        except PermissionError:
            if attempt==5:raise
            time.sleep(.05*(attempt+1))


def phase_seed(schema,partition,seed,phase):
    return int.from_bytes(hashlib.sha256(f'stage2-v0.4|{schema}|{partition}|{seed}|{phase}'.encode()).digest()[:4],'big')


def reset_rng(seed):
    random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
    if torch.cuda.is_available():torch.cuda.manual_seed_all(seed)


def initialization_indices(n,schema,partition,seed):
    if n<2:raise ValueError('At least two training windows required')
    rng=np.random.Generator(np.random.PCG64(phase_seed(schema,partition,seed,'init_sample')))
    return np.sort(rng.choice(n,min(n,4096),replace=False))


def initialize_odst(model,contexts,schema,partition,seed):
    if contexts.ndim!=2 or contexts.shape[1]!=128 or len(contexts)<2:raise ValueError('Context shape')
    if next(model.node_head.parameters()).device.type!='cpu':raise ValueError('CPU initialization required')
    state=torch.get_rng_state()
    try:
        generator=torch.Generator(device='cpu');generator.manual_seed(phase_seed(schema,partition,seed,'init_leaf'))
        torch.set_rng_state(generator.get_state())
        with torch.no_grad():
            return model.node_head.data_aware_initialize(contexts.detach().cpu().float(),threshold_quantile=.5,target_scaled_std=1.,leaf_init_std=.05)
    finally:torch.set_rng_state(state)


def cpu(value):
    if isinstance(value,torch.Tensor):return value.detach().cpu().clone()
    if isinstance(value,dict):return {k:cpu(v) for k,v in value.items()}
    if isinstance(value,list):return [cpu(v) for v in value]
    if isinstance(value,tuple):return tuple(cpu(v) for v in value)
    return copy.deepcopy(value)


def state_hash(model):
    h=hashlib.sha256()
    for k,v in sorted(model.state_dict().items()):
        h.update(k.encode());h.update(str(tuple(v.shape)).encode());h.update(str(v.dtype).encode());h.update(v.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


class Checkpoints:
    REQUIRED={'epoch','next_batch','phase','epoch_rng_state','permutation_sha256','best_state','best_ap','best_epoch','stale','history','loss_sum','seen','fit_finished'}

    def __init__(self,directory,identity):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.identity=identity;self.binding=digest(identity);self.pointer=self.directory/'CHECKPOINT_POINTER.json'
        self.state_parent=None
        self.ledger_cache=None
        self.next_sequence=None
        self.retained_rows=None

    def _record(self,path):
        item=json.loads(path.read_text(encoding='utf-8'))
        checksum=item.pop('record_sha256')
        if item['binding']!=self.binding:raise ValueError('Checkpoint identity mismatch')
        if digest(item)!=checksum:raise ValueError('Generation checksum mismatch')
        item['record_sha256']=checksum
        return item

    def _committed(self,force=False):
        if self.ledger_cache is not None and not force:
            for saved in self.ledger_cache[-3:]:
                current=self._record(self.directory/f"commit_{saved['sequence']:08d}.json")
                if current!=saved:raise RuntimeError('Latest checkpoint ledger changed')
            return list(self.ledger_cache)
        rows=[]
        for p in sorted(self.directory.glob('commit_*.json')):
            if not re.fullmatch(r'commit_\d{8}\.json',p.name):continue
            try:
                row=self._record(p)
                if row['previous_record_sha256']!=(rows[-1]['record_sha256'] if rows else None):raise RuntimeError('Broken checkpoint record chain; recovery review required')
                if row['sequence']<= (rows[-1]['sequence'] if rows else 0):raise RuntimeError('Non-increasing checkpoint sequence')
                rows.append(row)
            except (ValueError,OSError,KeyError) as exc:
                if 'identity mismatch' in str(exc):raise ValueError('Checkpoint identity mismatch') from exc
                raise RuntimeError('Damaged checkpoint record; recovery review required') from exc
        self.ledger_cache=list(rows)
        return rows

    def _commit_exclusive(self,row):
        path=self.directory/f"commit_{row['sequence']:08d}.json"
        temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        with temp.open('x',encoding='utf-8',newline='\n') as f:
            json.dump(row,ObservedWriter(f,'commit_write',temp),indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
        atomic_stage('commit_fsynced',temp)
        os.link(temp,path)  # Atomic, exclusive publication of fsynced bytes on NTFS.
        atomic_stage('commit_published',path)
        temp.unlink()

    def save(self,model,optimizer,progress,rng,kind='step'):
        if not self.REQUIRED.issubset(progress) or 'permutation' in progress:raise ValueError('Checkpoint continuation state')
        if shutil.disk_usage(self.directory).free<2*1024**3:raise RuntimeError('Less than 2 GiB free at checkpoint')
        committed=self._committed(force=kind=='final')
        if self.next_sequence is None:
            numbers=[int(m.group(1)) for p in self.directory.iterdir() if (m:=re.fullmatch(r'(?:state|commit)_(\d{8})(?:\..*)?',p.name))]
            self.next_sequence=max(numbers+[0])+1
        seq=self.next_sequence;self.next_sequence+=1
        # Orphan files from an interrupted commit are retained, never overwritten.
        while (self.directory/f'state_{seq:08d}.pt').exists():seq+=1
        name=f'state_{seq:08d}.pt';path=self.directory/name;temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        nr=np.random.get_state()
        state=dict(identity=self.identity,binding=self.binding,model=cpu(model.state_dict()),optimizer=cpu(optimizer.state_dict()),progress=cpu(progress),
            python_rng=random.getstate(),numpy_rng=[nr[0],nr[1].tolist(),nr[2],nr[3],nr[4]],generator_rng=copy.deepcopy(rng.bit_generator.state),
            torch_rng=torch.get_rng_state(),cuda_rng=torch.cuda.get_rng_state_all() if torch.cuda.is_initialized() else None)
        with temp.open('xb') as f:torch.save(state,ObservedWriter(f,'state_write',temp));f.flush();os.fsync(f.fileno())
        atomic_stage('state_fsynced',temp)
        replace(temp,path)
        atomic_stage('state_renamed',path)
        row=dict(binding=self.binding,sequence=seq,file=name,sha256=sha(path),kind=kind,
            previous_record_sha256=committed[-1]['record_sha256'] if committed else None,
            state_parent=self.state_parent,updates=int(progress.get('updates',0)))
        row['record_sha256']=digest(row)
        self._commit_exclusive(row)
        atomic_json(self.pointer,row)
        self.state_parent=dict(sequence=seq,record_sha256=row['record_sha256'],state_sha256=row['sha256'])
        committed.append(row)
        self.ledger_cache=list(committed)
        if self.retained_rows is None:self.retained_rows={v['sequence']:v for v in committed if (self.directory/v['file']).exists()}
        self.retained_rows[seq]=row
        keep={v['sequence'] for v in committed[-3:]}
        keep.update(v['sequence'] for v in [x for x in committed if x['kind']=='epoch'][-2:])
        keep.update(v['sequence'] for v in [x for x in committed if x['kind'] in ('phase','pause','final')][-3:])
        for v in list(self.retained_rows.values()):
            old=self.directory/v['file']
            if v['sequence'] not in keep and old.exists():
                if old.parent.resolve()!=self.directory.resolve() or old.is_symlink():raise ValueError('Checkpoint prune boundary')
                old.unlink()
                self.retained_rows.pop(v['sequence'],None)
        return row

    def exists(self):return self.pointer.exists() or bool(self._committed())

    def load(self,model,optimizer,rng,optimizer_factory=None):
        # An identity mismatch is never turned into a fresh fit or a different arm.
        candidates=[]
        if self.pointer.exists():
            try:
                row=self._record(self.pointer)
                chain=self._committed()
                known={v['record_sha256'] for v in chain}
                if row['record_sha256'] in known or row['previous_record_sha256']==(chain[-1]['record_sha256'] if chain else None):candidates.append(row)
            except (ValueError,OSError,KeyError,json.JSONDecodeError):pass
        candidates+=list(reversed(self._committed(force=True)))
        candidates.sort(key=lambda row:row['sequence'],reverse=True)
        if not candidates:raise ValueError('No valid identity-matched committed checkpoint')
        failures=[];seen=set()
        for row in candidates:
            if row['sequence'] in seen:continue
            seen.add(row['sequence']);path=self.directory/row['file']
            try:
                if not re.fullmatch(r'state_\d{8}\.pt',row['file']) or path.is_symlink():raise ValueError('Generation path')
                if sha(path)!=row['sha256']:raise ValueError('Corrupt checkpoint')
                state=torch.load(path,map_location='cpu',weights_only=True)
                if state['binding']!=self.binding or state['identity']!=self.identity:raise ValueError('Payload identity')
                if not self.REQUIRED.issubset(state['progress']):raise ValueError('Incomplete continuation')
            except (OSError,ValueError,RuntimeError,EOFError,KeyError,pickle.UnpicklingError) as exc:
                failures.append(dict(sequence=row['sequence'],reason=str(exc)));continue
            model.load_state_dict(state['model'],strict=True)
            if optimizer_factory is not None:optimizer=optimizer_factory(state['progress'])
            optimizer.load_state_dict(state['optimizer'])
            random.setstate(state['python_rng']);nr=state['numpy_rng'];np.random.set_state((nr[0],np.asarray(nr[1],dtype=np.uint32),nr[2],nr[3],nr[4]))
            rng.bit_generator.state=state['generator_rng'];torch.set_rng_state(state['torch_rng'])
            if state['cuda_rng'] is not None:
                if not torch.cuda.is_available():raise ValueError('Original CUDA stack unavailable')
                torch.cuda.set_rng_state_all(state['cuda_rng'])
            atomic_json(self.directory/'LAST_RESUME.json',dict(sequence=row['sequence'],fallback_reasons=failures,score_used=False))
            marker=self.directory/f"commit_{row['sequence']:08d}.json"
            if not marker.exists():self._commit_exclusive(row)
            self.ledger_cache=None
            self.state_parent=dict(sequence=row['sequence'],record_sha256=row['record_sha256'],state_sha256=row['sha256'])
            with (self.directory/'RESUME_LOG.jsonl').open('a',encoding='utf-8',newline='\n') as f:
                json.dump(dict(**self.state_parent,updates_at_resume=int(state['progress'].get('updates',0)),fallback_reasons=failures,score_used=False),f);f.write('\n');f.flush();os.fsync(f.fileno())
            return (state['progress'],optimizer) if optimizer_factory is not None else state['progress']
        raise ValueError('All retained checkpoints failed verification; no fresh fit permitted')
