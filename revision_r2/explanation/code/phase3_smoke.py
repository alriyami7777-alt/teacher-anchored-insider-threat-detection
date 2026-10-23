"""CPU-only frozen loader and differentiation test, using synthetic inputs only."""
import os
os.environ['CUDA_VISIBLE_DEVICES']=''
os.environ['OMP_NUM_THREADS']='2'
os.environ['MKL_NUM_THREADS']='2'
import sys
sys.dont_write_bytecode=True
import time
from pathlib import Path
import numpy as np
import torch
from run_phase3 import TAForward,XGForward,TA_BASE,XG_BASE,TA_SHA,XG_SHA
from phase3_engine import SEEDS,integrated_gradients,checked
torch.set_num_threads(2)
t0=time.monotonic()
for s in SEEDS:
    checked(TA_BASE/f'seed{s}/best_student.pt',TA_SHA[s])
    checked(XG_BASE/f'xgboost_seed{s}/model.json',XG_SHA[s])
print('All six original checkpoint hashes match frozen identities',flush=True)
f=TAForward(TA_BASE/'seed42/best_student.pt',TA_SHA[42],torch.device('cpu'))
x=np.random.default_rng(42).normal(0,.1,(2,20,13)).astype(np.float32)
b=np.zeros((20,13),np.float32)
before={k:v.detach().clone() for k,v in f.model.state_dict().items()}
a,d,r,e=integrated_gradients(f,x,b,steps=50,batch_size=2)
for k,v in f.model.state_dict().items():
    assert torch.equal(v,before[k]),'Model state changed during IG'
assert np.isfinite(a).all()
np.testing.assert_allclose(a[:,-1],a[:,:8].mean(1),atol=1e-6,rtol=1e-4)
print('Frozen TA2 CPU synthetic 50-step IG: nine finite targets; parameters and buffers unchanged',flush=True)
g=XGForward(XG_BASE/'xgboost_seed42/model.json',XG_SHA[42])
z=np.zeros((2,40),np.float32); shap=g.contributions(z)
np.testing.assert_allclose(shap.sum(1),g.predict(z),atol=1e-3)
print('Frozen XGBoost CPU synthetic TreeSHAP margin additivity passes',flush=True)
print('CPU synthetic smoke seconds:',round(time.monotonic()-t0,2),flush=True)
