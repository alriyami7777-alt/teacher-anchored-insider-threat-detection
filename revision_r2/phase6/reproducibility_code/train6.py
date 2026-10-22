from common6 import *
import argparse,torch
from torch import nn
p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--model',required=True);p.add_argument('--seed',type=int,required=True);a=p.parse_args()
CONFIG=a.config;BASE=PRIVATE/'training'/CONFIG
manifest=read(PRIVATE/'data'/CONFIG/'manifest.json');D=len(manifest['features'])
rt.OUT=OUT;rt.PRIVATE=BASE
rt.gate=lambda:None
rt.data=lambda:loadbundle(CONFIG)
rt.ENCODER_ARCH=dict(rt.ENCODER_ARCH,input_dim=D)
def build(kind,uni=False):
 if kind=='precursor':return rt.SequenceEnsembleModel(input_dim=D,hidden_size=64,dropout=.2,attention_dim=64,classification_head='linear',temporal_aggregation='attention')
 return rt.AttentionNodeEnsemble(**rt.ENCODER_ARCH)
rt.build=build
old_recipe=rt.recipe
def recipe(model,seed,bundle):
 cfg=old_recipe(model,seed,bundle)
 cfg.update(phase6_config=CONFIG,features=manifest['features'],sequence_length=manifest['length'],training_partition='TRAIN',selection_partition='VALIDATION',excluded_holdout=True)
 if model in ('RF_40','XGBoost_40'):cfg['params']['n_jobs']=2
 return cfg
rt.recipe=recipe
old_forward=rt.forward
def forward(*args,**kwargs):
 out=old_forward(*args,**kwargs);time.sleep(.002);return out
rt.forward=forward
device();result=BASE/'results'/f'{a.model}_{a.seed}.json'
assert not result.exists(),'Refuse repeated completed run'
rt.train_run(a.model,a.seed,result)
# Freeze and retain selected VALIDATION predictions for later paired analysis.
r=read(result);bundle=loadbundle(CONFIG);x=bundle['validation']['X']
if a.model in ('XGBoost_40','RF_40'):
 import joblib
 if a.model=='RF_40':m=joblib.load(r['checkpoint'])
 else:
  from xgboost import XGBClassifier
  m=XGBClassifier();m.load_model(r['checkpoint']);m.set_params(n_jobs=2)
 prob=m.predict_proba(bundle['validation']['X40'])[:,1].astype(np.float64)
else:
 m=rt.load_model(a.model,a.seed,torch.device('cuda'))
 loader=torch.utils.data.DataLoader(torch.utils.data.TensorDataset(torch.from_numpy(x)),batch_size=1024,shuffle=False)
 logit=rt.logits(m,loader,torch.device('cuda'),'precursor' if 'PRECURSOR' in a.model else 'odst')
 prob=torch.sigmoid(torch.from_numpy(logit)).numpy() if 'PRECURSOR' in a.model else rt.probs(logit)
np.save(BASE/'results'/f'{a.model}_{a.seed}_validation.npy',prob)
print('RUN_COMPLETE',CONFIG,a.model,a.seed,flush=True)
