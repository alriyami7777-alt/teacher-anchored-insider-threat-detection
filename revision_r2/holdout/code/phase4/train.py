from common import *
import argparse,subprocess,csv,traceback
def train(name,seed):
    import numpy as np,torch,joblib
    from torch import nn
    from torch.utils.data import DataLoader,TensorDataset,Subset
    from sklearn.metrics import average_precision_score
    import phase2_runtime as rt
    result=PRIVATE/'runs'/f'{name}_{seed}.json';assert not result.exists()
    device=setup_torch();rt.seed_all(seed);start=time.perf_counter();data=rt.data()
    tr,va=data['train'],data['validation'];assert len(tr['y'])==591000 and int(tr['y'].sum())==3040
    ck=PRIVATE/'checkpoints'/name/f'seed{seed}'/'best.pt';ck.parent.mkdir(parents=True,exist_ok=False)
    if name in ('IsolationForest','LightGBM_40'):
        if name=='IsolationForest':
            from sklearn.ensemble import IsolationForest
            params=dict(n_estimators=200,max_samples=256,contamination='auto',random_state=seed,n_jobs=2)
            m=IsolationForest(**params);m.fit(tr['X40']);p=-m.score_samples(va['X40'])
        else:
            from lightgbm import LGBMClassifier
            params=dict(n_estimators=300,num_leaves=31,learning_rate=.05,scale_pos_weight=(591000-3040)/3040,subsample=.8,subsample_freq=1,colsample_bytree=.8,deterministic=True,random_state=seed,n_jobs=2,verbosity=-1)
            m=LGBMClassifier(**params);m.fit(tr['X40'],tr['y'].astype(np.int32));p=m.predict_proba(va['X40'])[:,1]
        ck=ck.with_suffix('.joblib');joblib.dump(m,ck);epochs=best_epoch=params['n_estimators'];best=float(average_precision_score(va['y'],p));history=[];used_device='CPU'
    else:
        ds=TensorDataset(torch.from_numpy(tr['X']),torch.from_numpy(tr['y']))
        if name=='LSTM_AE':ds=Subset(ds,np.flatnonzero(tr['y']==0))
        loader=DataLoader(ds,batch_size=1024,shuffle=True,generator=torch.Generator().manual_seed(seed),num_workers=0)
        vl=DataLoader(TensorDataset(torch.from_numpy(va['X'])),batch_size=1024,shuffle=False,num_workers=0)
        m=build_model(name).to(device);opt=torch.optim.Adam(m.parameters(),lr=.001)
        criterion=nn.MSELoss() if name=='LSTM_AE' else nn.BCEWithLogitsLoss(pos_weight=torch.tensor([.25*(591000-3040)/3040],device=device))
        best=-1.;patience=4;history=[];best_p=None
        for epochs in range(1,16):
            m.train();loss_sum=0.;count=0;t=time.perf_counter()
            for x,y in loader:
                x=x.to(device);opt.zero_grad(set_to_none=True);out=m(x);loss=criterion(out,x if name=='LSTM_AE' else y.to(device))
                assert torch.isfinite(loss);loss.backward();nn.utils.clip_grad_norm_(m.parameters(),1.);opt.step();loss_sum+=loss.item()*len(x);count+=len(x)
            m.eval();scores=[]
            with torch.no_grad():
                for (x,) in vl:
                    x=x.to(device);out=m(x);scores.append(((out-x).square().mean((1,2)) if name=='LSTM_AE' else out).cpu().numpy())
            raw=np.concatenate(scores);p=raw.astype(np.float64) if name=='LSTM_AE' else rt.probs(raw)
            ap=float(average_precision_score(va['y'],p));history.append(dict(epoch=epochs,development_AP=ap,train_loss=loss_sum/count,seconds=time.perf_counter()-t))
            print(name,seed,'epoch',epochs,'development_AP',ap,'seconds',history[-1]['seconds'],flush=True)
            dump(PRIVATE/'progress'/f'{name}_{seed}.json',dict(history=history))
            if ap>best:
                best=ap;best_epoch=epochs;best_p=p.copy();torch.save(dict(model_state_dict={k:v.detach().cpu().clone() for k,v in m.state_dict().items()},model=name,seed=seed),ck);patience=4
            else:patience-=1
            if patience<=0:break
        p=best_p;params=dict(optimizer='Adam',learning_rate=.001,batch_size=1024,gradient_clip=1.,max_epochs=15,patience=4,positive_weight=.25*(591000-3040)/3040,benign_only=name=='LSTM_AE');used_device=str(device);assert best_p is not None
    spec=dict(model=name,seed=seed,status='ok',epochs=epochs,best_epoch=best_epoch,development_AP=best,duration=time.perf_counter()-start,device=used_device,checkpoint=str(ck),sha256=sha(ck),threshold=threshold(va['y'],p),params=params,history=history)
    dump(result,spec)
def coordinate():
    verify_original();P4.mkdir(parents=True,exist_ok=True);PRIVATE.mkdir(parents=True,exist_ok=True)
    with (PRIVATE/'TRAINING_STARTED.json').open('x') as f:json.dump(dict(utc=utc(),code_sha256=sha(__file__)),f)
    recipes=dict(utc=utc(),seeds=SEEDS,recipe_source='PREREGISTRATION_R2_HOLDOUT.md Amendment 2',implementation_choices={'TCN':'two causal Conv1d layers per residual block, left zero padding; 1x1 residual projection where dimensions differ','Transformer':'PyTorch default post-norm encoder with ReLU; positional parameters initialized N(0,0.02)','LSTM_AE':'encoder final hidden vector repeated 20 steps; decoder initial hidden and cell are zero','threshold':'exact maximum DEVELOPMENT VALIDATION F1 over distinct observed scores; lowest threshold on ties','resources':'one seed at a time, two CPU threads and 45% GPU allocation cap'},preregistration_sha256=sha(OUT/'PREREGISTRATION_R2_HOLDOUT.md'),files={p.name:sha(p) for p in CODE.glob('*.py')})
    dump(P4/'RECIPES_FROZEN_PHASE4.json',recipes)
    rows=[]
    for name in BASELINES:
        for seed in SEEDS:
            status('TRAINING',model=name,seed=seed,completed=len(rows));log=PRIVATE/'logs'/f'{name}_{seed}.log';log.parent.mkdir(exist_ok=True)
            result=PRIVATE/'runs'/f'{name}_{seed}.json';start=time.perf_counter()
            with log.open('x') as handle:
                proc=subprocess.Popen([sys.executable,str(CODE/'train.py'),'--model',name,'--seed',str(seed)],cwd=CODE,stdout=handle,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                try:rc=proc.wait(timeout=5400)
                except subprocess.TimeoutExpired:proc.kill();proc.wait();rc='TIMEOUT'
            if result.exists() and rc==0:r=json.loads(result.read_text())
            else:r=dict(model=name,seed=seed,status='TIMEOUT' if rc=='TIMEOUT' else 'FAILED',epochs=None,best_epoch=None,development_AP=None,duration=time.perf_counter()-start,device='unavailable',reason='See private log; no retry')
            rows.append(r)
            fields=['model','seed','epochs','best_epoch','development_AP','duration','device','status']
            with (P4/'TRAINING_LOG_PHASE4.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:r.get(k) for k in fields} for r in rows)
            dump(P4/'TRAINING_RESULTS_PHASE4.json',rows)
    status('TRAINING_FINISHED',successful=sum(r['status']=='ok' for r in rows),total=len(rows))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model');p.add_argument('--seed',type=int);a=p.parse_args()
    if a.model:train(a.model,a.seed)
    else:coordinate()
