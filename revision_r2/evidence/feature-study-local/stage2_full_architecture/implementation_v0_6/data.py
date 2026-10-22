"""Bounded saved-array access; TEST and raw logs are not opened."""
from pathlib import Path
import json
import numpy as np
from contracts import sha,digest

ROOT=Path(__file__).resolve().parents[2]
TRAIN=ROOT/'implementation_runs/full_train_preflight_20261007_r1'
VAL=ROOT/'implementation_runs/validation_preflight_20261007_r1'
SCHEMAS=('F6_PRIMITIVES','F13','F29')
SEEDS=(42,52,62)

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))

def input_records():
    requested={TRAIN:['train_daily_F29.npy','train_daily_label_event_counts.npy','COHORT_LOCAL.json','REALIZED_SCHEMAS.json','DAILY_PREPROCESSORS.json'],
               VAL:['validation_daily_F29.npy','validation_daily_label_event_counts.npy']}
    entries=[]
    for folder,names in requested.items():
        registry=read(folder/'OUTPUT_IDENTITY.json')
        entries.append(dict(path=str(folder/'OUTPUT_IDENTITY.json'),sha256=sha(folder/'OUTPUT_IDENTITY.json')))
        for name in names:
            path=folder/name;record=registry[name]
            if Path(record['path']).resolve()!=path.resolve():raise RuntimeError('Input path binding mismatch')
            if sha(path)!=record['sha256']:raise RuntimeError('Saved input drift: '+name)
            entries.append(dict(path=str(path),sha256=record['sha256'],bytes=path.stat().st_size))
    return entries

class Dataset:
    def __init__(self,schema,partition):
        self.schema=schema;self.partition=partition
        schemas=read(TRAIN/'REALIZED_SCHEMAS.json');self.spec=schemas[schema]
        self.columns=[schemas['F29']['behavioural_columns'].index(n) for n in self.spec['behavioural_columns']]
        self.prep=read(TRAIN/'DAILY_PREPROCESSORS.json')[schema]['INNER_TRAIN' if partition=='inner' else 'TRAIN']
        if self.prep['indicator_source_indexes']:raise RuntimeError('This reviewed panel expects no missingness indicators')
        self.cohort=read(TRAIN/'COHORT_LOCAL.json')['users']
        if len(self.cohort)!=2000 or len(set(self.cohort))!=2000 or self.cohort!=sorted(self.cohort):raise RuntimeError('Cohort key parity')
        self.base=np.load(TRAIN/'train_daily_F29.npy',mmap_mode='r',allow_pickle=False)
        self.labels=np.load(TRAIN/'train_daily_label_event_counts.npy',mmap_mode='r',allow_pickle=False).sum(axis=2)>0
        self.evalbase=self.base if partition=='inner' else np.load(VAL/'validation_daily_F29.npy',mmap_mode='r',allow_pickle=False)
        self.evlabels=self.labels if partition=='inner' else np.load(VAL/'validation_daily_label_event_counts.npy',mmap_mode='r',allow_pickle=False).sum(axis=2)>0
        self.fit_range=(0,330) if partition=='inner' else (0,413)
        self.eval_range=(330,413) if partition=='inner' else (0,51)
        self.y=self.window_labels(self.labels,*self.fit_range)
        self.ye=self.window_labels(self.evlabels,*self.eval_range)
        expected=(622000,2457,128000,1214) if partition=='inner' else (788000,3957,64000,728)
        if (len(self.y),int(self.y.sum()),len(self.ye),int(self.ye.sum()))!=expected:raise RuntimeError('Label/split parity')
        if self.base.shape!=(2000,413,29) or self.evalbase.shape[:2]!=(2000,413 if partition=='inner' else 51):raise RuntimeError('Array shape')

    @staticmethod
    def window_labels(days,lo,hi):
        return np.lib.stride_tricks.sliding_window_view(days[:,lo:hi],20,axis=1).max(axis=2).reshape(-1).astype('int8')

    def batch(self,index,evaluation=False):
        lo,hi=self.eval_range if evaluation else self.fit_range;n=hi-lo-19
        index=np.asarray(index,dtype=np.int64);users=index//n;starts=lo+index%n
        base=self.evalbase if evaluation else self.base
        x=base[users[:,None],starts[:,None]+np.arange(20)][...,self.columns].astype('float64')
        filled=np.where(np.isnan(x),np.asarray(self.prep['median']),x)
        result=((filled-np.asarray(self.prep['mean']))/np.asarray(self.prep['scale'])).astype('float32')
        if not np.isfinite(result).all():raise RuntimeError('Nonfinite standardized windows')
        return result

    def keys(self):
        n=64 if self.partition=='inner' else 32;date='2010-11-28' if self.partition=='inner' else '2011-02-19'
        users=np.repeat(np.asarray(self.cohort),n);starts=np.tile(np.datetime64(date)+np.arange(n),2000)
        base=330 if self.partition=='inner' else 394
        ids=np.asarray([f'seq_{460*u+base+j+1:08d}' for u in range(2000) for j in range(n)])
        return dict(user=users,start_date=starts,end_date=starts+19,sequence_id=ids,
                    label_task=np.full(len(users),'ANY_DAY_COMPLETED_WINDOW_T20'))

    def identity(self):
        return dict(schema=self.schema,partition=self.partition,representation_sha256=self.spec['representation_sha256'],
                    columns=self.spec['output_columns'],preprocessor_sha256=digest(self.prep),
                    train_labels_sha256=__import__('hashlib').sha256(self.y.tobytes()).hexdigest(),
                    eval_labels_sha256=__import__('hashlib').sha256(self.ye.tobytes()).hexdigest())
