"""Isolated development-only model construction and frozen training recipes."""
from pathlib import Path
import sys, os, json, time, random, hashlib, gc
ROOT=Path(r'C:\PhD\07_Projects\r2_holdout')
OUT=Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision\holdout')
PRIVATE=OUT/'private'
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'producing_model'))
sys.path.insert(0,str(ROOT/'parity_source'))
from r52_locked_baselines.data import aggregate_common13_windows
import numpy as np
import torch
from torch import nn
from torch.utils.data import TensorDataset,DataLoader
from sklearn.metrics import average_precision_score,f1_score
from models.sequence_ensemble import SequenceEnsembleModel
from prototype_v3_node.architecture import AttentionNodeEnsemble
from editor011_confirmation.constants import ENCODER_ARCH
from editor011_confirmation.models import student_forward,freeze_teacher,enable_student,build_student_optimizer,build_teacher_optimizer,clone_state
from editor012_rescue.losses import route_consistency_loss,et1_ensemble_logit_mse

SEEDS=(42,52,62)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def dump(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_suffix(p.suffix+'.tmp');temp.write_text(json.dumps(obj,indent=2),encoding='utf-8');os.replace(temp,p)
def gate():
    report=OUT.parent/'CHATGPT_PHASE1_REPORT.md'
    assert report.exists() and report.read_text(encoding='utf-8-sig').rstrip().endswith('PHASE1_COMPLETE'),'Phase 1 gate closed'
def seed_all(seed,primary=True):
    random.seed(seed);np.random.seed(seed);torch.manual_seed(seed);torch.cuda.manual_seed_all(seed)
    if primary:
        torch.backends.cudnn.deterministic=True;torch.backends.cudnn.benchmark=False
def checkpoint(model,seed):return PRIVATE/'checkpoints'/model/f'seed{seed}'/'best.pt'
def data():
    p=PRIVATE/'tensors'
    return {s:{'X':np.load(p/f'{s}_X.npy',mmap_mode='c'),'X40':np.load(p/f'{s}_X40.npy',mmap_mode='c'),'y':np.load(p/f'{s}_y.npy').astype(np.float32)} for s in ('train','validation')}
def loaders(bundle,seed,extras=None,precursor=False):
    ts=[torch.from_numpy(bundle['train']['X']),torch.from_numpy(bundle['train']['y'])]
    if extras is not None:ts.append(torch.from_numpy(np.asarray(extras,dtype=np.float32)))
    opts={'batch_size':1024,'num_workers':0,'drop_last':False}
    g=None if precursor else torch.Generator().manual_seed(seed)
    train=DataLoader(TensorDataset(*ts),shuffle=True,generator=g,pin_memory=precursor,**opts)
    val=DataLoader(TensorDataset(torch.from_numpy(bundle['validation']['X']),torch.from_numpy(bundle['validation']['y'])),shuffle=False,pin_memory=precursor,**opts)
    return train,val
def build(kind,uni=False):
    # The uni intervention changes only directionality/hidden size; representation remains 128.
    if kind=='precursor':
        m=SequenceEnsembleModel(input_dim=13,hidden_size=64,dropout=.2,attention_dim=64,classification_head='linear',temporal_aggregation='attention')
    else:m=AttentionNodeEnsemble(**ENCODER_ARCH)
    if uni:
        m.lstm=nn.LSTM(13,128,num_layers=1,batch_first=True,bidirectional=False)
        m.hidden_size=128
    return m
def load_model(model,seed,device):
    path=checkpoint(model,seed)
    assert path.is_relative_to(PRIVATE/'checkpoints')
    payload=torch.load(path,map_location='cpu',weights_only=False)
    m=build('precursor' if 'PRECURSOR' in model else 'odst',model.startswith('uni'))
    if model=='L1':m.linear_head=nn.Linear(128,1)
    m.load_state_dict(payload['model_state_dict'],strict=True);m.to(device);m.eval()
    return m
def forward(m,x,kind):
    if kind=='precursor':return {'logit':m(x)[0]}
    if kind=='linear':
        z,_=m.encode_attention_h(x)
        return {'logit':m.linear_head(z).squeeze(-1)}
    return student_forward(m,x)
@torch.no_grad()
def logits(m,loader,device,kind='odst'):
    m.eval();out=[]
    for batch in loader:out.append(forward(m,batch[0].to(device),kind)['logit'].cpu().numpy())
    return np.concatenate(out)
def probs(logit):
    # Exact float64 conversion and clipping from EDITOR011/012 metrics.
    z=np.clip(np.asarray(logit,dtype=np.float64),-60,60)
    return 1.0/(1.0+np.exp(-z))
def threshold(y,p):
    candidates=set(np.linspace(.01,.99,99).tolist())
    candidates.update(float(q) for q in np.quantile(p,np.linspace(.01,.99,50)))
    best_t,best_f=.5,-1.
    for t in sorted(candidates):
        score=f1_score(y,(p>=t).astype(int),zero_division=0)
        if score>best_f:best_t,best_f=float(t),float(score)
    return best_t
def recipe(model,seed,bundle):
    n=len(bundle['train']['y']);pos=int(bundle['train']['y'].sum());ratio=(n-pos)/pos
    base={'model':model,'seed':seed,'development_only':True,'max_epochs':15,'patience':4,'batch_size':1024,'gradient_clip_norm':1.,'weight_decay':0.,'dropout':.2,'attention_dim':64,'hidden_size':128 if model.startswith('uni') else 64,'bidirectional':not model.startswith('uni'),'state_dim':128,'checkpoint_metric':'development_validation_average_precision','threshold_rule':'maximum development validation F1; sorted grid+quantile candidates; first maximum','pos_weight':.25*ratio,'optimizer':'Adam','encoder_lr':3e-5,'attention_lr':3e-5,'head_lr':1e-3,'lambda_teacher':.5 if model in ('TA2','F10','L1','uniTA2') else 0.,'lambda_route':.5 if model in ('TA2','uniTA2') else 0.}
    base['architecture']=dict(ENCODER_ARCH)
    if model.startswith('uni'):base['architecture'].update(hidden_size=128,bidirectional=False,encoder_dim=128)
    if 'PRECURSOR' in model:
        base.update({'source':'producing r52_odst_confirmation attention_linear config / run_sequence_ensemble.py','pos_weight':ratio,'pos_weight_multiplier':1.,'encoder_lr':1e-3,'attention_lr':1e-3,'scheduler':{'name':'ReduceLROnPlateau','factor':.5,'patience':2,'min_lr':1e-5},'improvement_epsilon':1e-6,'role':'development-only prerequisite for frozen T-OPT initialization'})
    elif model in ('T-OPT','uniT-OPT'):base.update({'source':'EDITOR011 producing frozen-node teacher recipe','encoder_frozen':True,'attention_frozen':True,'linear_frozen':True})
    elif model=='L1':base.update({'source':'EDITOR013 L1 (used by EDITOR023)','linear_init':'zero','initial_encoder':'matched development T-OPT','teacher_target':'equal mean of 3 development T-OPT logits','node_head_used':False})
    else:base.update({'source':'EDITOR011 matched ODST046 and EDITOR012 factorial producing recipes','teacher_target':'equal mean of 3 development T-OPT logits' if base['lambda_teacher'] else None,'initialization':'matched development T-OPT'})
    if model in ('RF_40','XGBoost_40'):
        if model=='RF_40':params={'n_estimators':200,'max_depth':20,'min_samples_leaf':2,'n_jobs':-1,'class_weight':'balanced_subsample','random_state':seed}
        else:params={'n_estimators':300,'max_depth':6,'learning_rate':.1,'subsample':.8,'colsample_bytree':.8,'reg_lambda':1.,'objective':'binary:logistic','eval_metric':'aucpr','scale_pos_weight':ratio,'n_jobs':-1,'random_state':seed,'tree_method':'hist'}
        return {'model':model,'seed':seed,'source':'cert-r52-locked-baselines/scripts/r52_locked_baselines/train.py','features':'40 aggregates of standardized float32 sequence tensors; exact producing aggregate_common13_windows','params':params,'threshold_rule':base['threshold_rule'],'development_only':True}
    return base

def ensemble(bundle,uni,device):
    name='uni' if uni else 'bi'
    p=PRIVATE/'teacher_cache'/f'{name}_train_ensemble_logits.npy'
    if p.exists():return np.load(p)
    loader=DataLoader(TensorDataset(torch.from_numpy(bundle['train']['X'])),batch_size=1024,shuffle=False,num_workers=0)
    all_logits=[]
    for s in SEEDS:
        gate();m=load_model('uniT-OPT' if uni else 'T-OPT',s,device);freeze_teacher(m)
        all_logits.append(logits(m,loader,device));del m;torch.cuda.empty_cache()
    result=np.mean(all_logits,axis=0)
    p.parent.mkdir(parents=True,exist_ok=True);np.save(p,result)
    return result

def train_run(model,seed,result_path):
    gate();bundle=data();cfg=recipe(model,seed,bundle);started=time.perf_counter()
    if model in ('RF_40','XGBoost_40'):
        if model=='RF_40':
            from sklearn.ensemble import RandomForestClassifier
            m=RandomForestClassifier(**cfg['params'])
        else:
            from xgboost import XGBClassifier
            m=XGBClassifier(**cfg['params'])
        m.fit(bundle['train']['X40'],bundle['train']['y'].astype(np.int32))
        p=m.predict_proba(bundle['validation']['X40'])[:,1].astype(np.float64)
        import joblib
        ck=checkpoint(model,seed).with_suffix('.json' if model=='XGBoost_40' else '.joblib');ck.parent.mkdir(parents=True,exist_ok=True)
        if model=='XGBoost_40':m.save_model(ck)
        else:joblib.dump(m,ck)
        result={'model':model,'seed':seed,'config':cfg,'epochs':cfg['params']['n_estimators'],'best_epoch':cfg['params']['n_estimators'],'dev_validation_pr_auc':float(average_precision_score(bundle['validation']['y'],p)),'threshold':threshold(bundle['validation']['y'],p),'wall_seconds':time.perf_counter()-started,'gpu':'CPU','checkpoint':str(ck),'sha256':sha(ck),'status':'ok'}
        dump(result_path,result);return
    device=torch.device('cuda');assert torch.cuda.is_available(),'CUDA unavailable; do not silently change frozen GPU recipe'
    precursor='PRECURSOR' in model;uni=model.startswith('uni');teacher_stage=model in ('T-OPT','uniT-OPT');linear=model=='L1'
    seed_all(seed,primary=not precursor)
    y=bundle['train']['y'];pos=int(y.sum());w=(len(y)-pos)/pos*(1. if precursor else .25)
    kind='precursor' if precursor else ('linear' if linear else 'odst')
    extras=ensemble(bundle,uni,device) if cfg['lambda_teacher'] else None
    # Ensemble collection is deterministic and eval-only; restore exact producing run seed.
    seed_all(seed,primary=not precursor)
    tr,va=loaders(bundle,seed,extras,precursor)
    matched=None
    if precursor:
        m=build('precursor',uni).to(device)
        opt=torch.optim.Adam(m.parameters(),lr=1e-3,weight_decay=0.)
        scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(opt,mode='max',factor=.5,patience=2,min_lr=1e-5)
    elif teacher_stage:
        m=build('odst',uni)
        pre=torch.load(checkpoint('uniAL_PRECURSOR' if uni else 'AL_PRECURSOR',seed),map_location='cpu',weights_only=False)['model_state_dict']
        inherited={k:v for k,v in pre.items() if k.startswith(('lstm.','attention.','linear_head.'))}
        missing,unexpected=m.load_state_dict(inherited,strict=False)
        assert not unexpected and not any(k.startswith(('lstm.','attention.','linear_head.')) for k in missing)
        del pre,inherited
        m.apply_frozen_node_trainability();m.to(device)
        xb,_=next(iter(tr));m.data_aware_initialize_from_batch(xb.to(device))
        opt=build_teacher_optimizer(m);scheduler=None
    else:
        m=load_model('uniT-OPT' if uni else 'T-OPT',seed,device)
        if linear:
            # Fresh zero-initialized EDITOR013 linear head; train encoder/attention/head only.
            m.linear_head=nn.Linear(128,1).to(device);nn.init.zeros_(m.linear_head.weight);nn.init.zeros_(m.linear_head.bias)
            for p in m.parameters():p.requires_grad=False
            for mod in (m.lstm,m.attention,m.linear_head):
                for p in mod.parameters():p.requires_grad=True
            opt=torch.optim.Adam([{'params':m.lstm.parameters(),'lr':3e-5},{'params':m.attention.parameters(),'lr':3e-5},{'params':m.linear_head.parameters(),'lr':1e-3}],weight_decay=0.)
        else:enable_student(m);opt=build_student_optimizer(m)
        if not linear:
            # Producing campaigns construct their matched teacher before resetting the
            # student seed. Preserve RNG state when loading it in an isolated child.
            with torch.random.fork_rng(devices=[0]):
                matched=load_model('uniT-OPT' if uni else 'T-OPT',seed,device);freeze_teacher(matched)
        scheduler=None
    criterion=nn.BCEWithLogitsLoss(pos_weight=torch.tensor([w],device=device))
    best=-1.;best_epoch=0;best_state=None;best_p=None;left=4;history=[]
    for epoch in range(1,16):
        m.train()
        if teacher_stage:m.lstm.eval();m.attention.eval();m.linear_head.eval();m.dropout.eval()
        t0=time.perf_counter();total=0.;n=0
        for batch in tr:
            xb,yb=batch[0].to(device),batch[1].to(device)
            opt.zero_grad(set_to_none=True);s=forward(m,xb,kind);loss=criterion(s['logit'],yb)
            if cfg['lambda_teacher']:loss=loss+.5*et1_ensemble_logit_mse(s['logit'],batch[2].to(device))
            if cfg['lambda_route']:
                with torch.no_grad():t=student_forward(matched,xb)
                loss=loss+.5*route_consistency_loss(s['choices'],t['choices'])
            assert torch.isfinite(loss),'Nonfinite training loss'
            loss.backward();nn.utils.clip_grad_norm_([p for p in m.parameters() if p.requires_grad],1.);opt.step()
            total+=float(loss.item())*len(yb);n+=len(yb)
        if precursor:
            # Producing precursor performs a validation-loss pass before its AP pass.
            m.eval()
            with torch.no_grad():
                for vb,vy in va:criterion(m(vb.to(device))[0],vy.to(device))
        vl=logits(m,va,device,kind)
        if matched is not None:
            # Retain the producing teacher-validation pass and DataLoader RNG cadence.
            logits(matched,va,device)
        # Precursor uses torch.sigmoid, primary producing metrics use numpy sigmoid.
        p=torch.sigmoid(torch.from_numpy(vl)).numpy() if precursor else probs(vl)
        ap=float(average_precision_score(bundle['validation']['y'],p))
        if scheduler:scheduler.step(ap)
        history.append({'epoch':epoch,'dev_validation_pr_auc':ap,'train_loss':total/n,'seconds':time.perf_counter()-t0})
        print(f'{model} seed={seed} epoch={epoch} dev_validation_AP={ap:.8f} seconds={history[-1]["seconds"]:.1f}',flush=True)
        dump(PRIVATE/'progress'/f'{model}_{seed}.json',{'model':model,'seed':seed,'config':cfg,'history':history})
        if ap>best+(1e-6 if precursor else 0.):best=ap;best_epoch=epoch;best_state=clone_state(m);best_p=p.copy();left=4
        else:left-=1
        if left<=0:break
    assert best_state is not None
    ck=checkpoint(model,seed);ck.parent.mkdir(parents=True,exist_ok=True)
    frozen_threshold=threshold(bundle['validation']['y'],best_p)
    torch.save({'model_state_dict':best_state,'model':model,'seed':seed,'best_epoch':best_epoch,'best_val_pr_auc':best,'config':cfg,'frozen_threshold':frozen_threshold,'development_only':True,'holdout_scored':False,'test_read':False},ck)
    result={'model':model,'seed':seed,'config':cfg,'epochs':len(history),'best_epoch':best_epoch,'dev_validation_pr_auc':best,'threshold':frozen_threshold,'wall_seconds':time.perf_counter()-started,'gpu':torch.cuda.get_device_name(0),'checkpoint':str(ck),'sha256':sha(ck),'status':'ok','history':history}
    dump(result_path,result)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True);parser.add_argument('--seed',required=True,type=int);parser.add_argument('--result',required=True)
    args=parser.parse_args();train_run(args.model,args.seed,Path(args.result))
