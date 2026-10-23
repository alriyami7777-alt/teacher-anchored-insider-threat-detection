"""Phase 4: isolated additions; original Phase 2 files are read-only."""
from pathlib import Path
import os,sys,json,hashlib,time
sys.dont_write_bytecode=True
os.environ.setdefault('OMP_NUM_THREADS','2')
os.environ.setdefault('MKL_NUM_THREADS','2')
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
ROOT=Path(r'C:\PhD\07_Projects\r2_holdout')
CODE=ROOT/'phase4'
OUT=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision\holdout')
P4=OUT/'phase4'
PRIVATE=OUT/'private'/'phase4'
EXPL=OUT.parent/'explanation'
SEEDS=(42,52,62)
BASELINES=('BiLSTM_noAttn','BiGRU_Attn','TCN','Transformer','MLP','LSTM_AE','IsolationForest','LightGBM_40')
sys.path.insert(0,str(ROOT))
def utc():
    from datetime import datetime,timezone
    return datetime.now(timezone.utc).isoformat()
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def dump(p,obj):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    tmp=Path(str(p)+'.tmp');tmp.write_text(json.dumps(obj,indent=2,allow_nan=False),encoding='utf-8');os.replace(tmp,p)
def status(stage,**kwargs):
    dump(P4/'STATUS.json',dict(utc=utc(),stage=stage,**kwargs))
    print(utc(),stage,kwargs,flush=True)
def setup_torch():
    import torch
    torch.set_num_threads(2)
    if torch.cuda.is_available():torch.cuda.set_per_process_memory_fraction(.45)
    return torch.device('cuda' if torch.cuda.is_available() else 'cpu')
def verify_original():
    f=json.loads((OUT/'MODELS_FROZEN.json').read_text())
    assert f['version']==2 and f['training_finished'] and not f['holdout_scored'] and not f['test_read']
    for e in f['implementation_files']:
        assert sha(e['path'])==e['sha256'], 'Original implementation hash changed: '+e['path']
    assert sha(f['scoring_script']['path'])==f['scoring_script']['sha256']
    for e in f['models']:assert sha(e['checkpoint'])==e['sha256']
    for name,key in [('DATA_MANIFEST.json','data_manifest_sha256'),('PARITY_GATE.json','parity_gate_sha256'),('CONFIGS_FROZEN.json','configs_frozen_sha256')]:assert sha(OUT/name)==f[key]
    for name,key in [('DEVELOPMENT_DAILY_SCALER.json','scaler_sha256'),('HOLDOUT_USERS.txt','holdout_list_sha256'),('DEVELOPMENT_USERS.txt','development_list_sha256')]:assert sha(OUT/'private'/name)==f[key]
    assert json.loads((OUT/'PARITY_GATE.json').read_text())['status'] in ('PARITY_GATE_PASS','PARITY_GATE_FIXED')
    return f
def build_model(name):
    import torch
    from torch import nn
    class Residual(nn.Module):
        def __init__(self,cin,d):
            super().__init__();self.d=d
            self.c1=nn.Conv1d(cin,64,3,dilation=d);self.c2=nn.Conv1d(64,64,3,dilation=d)
            self.skip=nn.Conv1d(cin,64,1) if cin!=64 else nn.Identity();self.drop=nn.Dropout(.1)
        def forward(self,x):
            y=self.drop(torch.relu(self.c1(nn.functional.pad(x,(2*self.d,0)))))
            y=self.drop(torch.relu(self.c2(nn.functional.pad(y,(2*self.d,0)))))
            return torch.relu(y+self.skip(x))
    class Model(nn.Module):
        def __init__(self):
            super().__init__()
            if name=='BiLSTM_noAttn':self.rnn=nn.LSTM(13,64,batch_first=True,bidirectional=True);self.head=nn.Linear(128,1)
            elif name=='BiGRU_Attn':
                self.rnn=nn.GRU(13,64,batch_first=True,bidirectional=True);self.proj=nn.Linear(128,64);self.att=nn.Linear(64,1,bias=False);self.head=nn.Linear(128,1)
            elif name=='TCN':self.blocks=nn.Sequential(Residual(13,1),Residual(64,2),Residual(64,4));self.head=nn.Linear(64,1)
            elif name=='Transformer':
                self.proj=nn.Linear(13,64);self.pos=nn.Parameter(torch.empty(1,20,64));nn.init.normal_(self.pos,std=.02)
                self.enc=nn.TransformerEncoder(nn.TransformerEncoderLayer(64,4,128,.1,batch_first=True),2,enable_nested_tensor=False);self.head=nn.Linear(64,1)
            elif name=='MLP':self.net=nn.Sequential(nn.Flatten(),nn.Linear(260,128),nn.ReLU(),nn.Dropout(.2),nn.Linear(128,64),nn.ReLU(),nn.Dropout(.2),nn.Linear(64,1))
            elif name=='LSTM_AE':self.enc=nn.LSTM(13,64,batch_first=True);self.dec=nn.LSTM(64,64,batch_first=True);self.head=nn.Linear(64,13)
            else:raise ValueError(name)
        def forward(self,x):
            if name=='BiLSTM_noAttn':
                _,(h,_)=self.rnn(x);return self.head(torch.cat((h[-2],h[-1]),1)).squeeze(-1)
            if name=='BiGRU_Attn':
                h,_=self.rnn(x);a=torch.softmax(self.att(torch.tanh(self.proj(h))).squeeze(-1),1);return self.head((h*a[:,:,None]).sum(1)).squeeze(-1)
            if name=='TCN':return self.head(self.blocks(x.transpose(1,2)).mean(2)).squeeze(-1)
            if name=='Transformer':return self.head(self.enc(self.proj(x)+self.pos).mean(1)).squeeze(-1)
            if name=='MLP':return self.net(x).squeeze(-1)
            _,(h,_)=self.enc(x);r,_=self.dec(h[-1][:,None,:].expand(-1,20,-1));return self.head(r)
    return Model()
def threshold(y,p):
    import numpy as np
    from sklearn.metrics import precision_recall_curve
    precision,recall,thresholds=precision_recall_curve(y,p)
    f=np.divide(2*precision[:-1]*recall[:-1],precision[:-1]+recall[:-1],out=np.zeros_like(thresholds),where=precision[:-1]+recall[:-1]>0)
    return float(thresholds[np.argmax(f)])
