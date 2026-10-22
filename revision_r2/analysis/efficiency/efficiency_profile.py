"""Synthetic-only frozen-model efficiency profile. No fit or CERT data reads.
Run with the historical system Python and -B. Uses read-only pinned architecture
sources and five frozen seed-42 models. Timing includes probability conversion;
XGBoost GPU timing includes host/device transfers for NumPy synthetic inputs.
"""
import os,sys,pathlib,json,time,hashlib,subprocess,ast,statistics,csv,threading,gc,traceback
os.environ['PYTHONDONTWRITEBYTECODE']='1'
HERE=pathlib.Path(__file__).resolve().parent
P=pathlib.Path(r'C:\PhD\07_Projects')
REPO=P/'teacher-anchored-insider-threat-detection'
BASE=P/'cert-r52-locked-baselines/outputs/objective2/r52_locked_baselines'
COMMIT='28475d575d5196a09c7267d09781050008ccc6d3'
SPECS={
 'TA2':(P/'teacher-anchored-insider-threat-detection-editor012/outputs/editor012_teacher_anchor_rescue/F11_DROPT/seed42/best_student.pt','54f6c097af9568a4ee5701ef375559a2f649cec6c1817e578d3e8e01e6d73df8'),
 'L1':(P/'teacher-anchored-insider-threat-detection-editor013/outputs/editor013_odst_value_proof/L1/seed42/best.pt','513e272063250aa209efa2c42b490cc44316c7979fa6b2be5dd8cce4592d1ab2'),
 'F00':(P/'teacher-anchored-insider-threat-detection-editor011/outputs/editor011_matched_route_confirmation/C2-OPT/seed42/best_student.pt','d64651d25e48b3bcd4cad7d107d3bc55a4c555a2827f3656a087624e94ac4baf'),
 'XGBoost_40':(BASE/'xgboost_seed42/model.json','2109554164abdd002ce0a4377f957c5aa3bc26886a197749ea79fc04d9b94fae'),
 'RF_40':(BASE/'random_forest_seed42/model.joblib','38b8830acec3b9c399411093ac38ed6bed6dca52a0cf05be9c87178cb05f5780')}
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def gitshow(path):return subprocess.check_output(['git','-c','safe.directory='+REPO.as_posix(),'-C',str(REPO),'show',COMMIT+':'+path]).decode()
def write(name,data):
 (HERE/name).write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
def run_model(name):
 import numpy as np,torch,psutil
 from torch.utils.flop_counter import FlopCounterMode
 torch.set_num_threads(min(8,os.cpu_count() or 1));torch.set_num_interop_threads(1)
 torch.manual_seed(42);np.random.seed(42)
 torch.backends.cudnn.benchmark=False;torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
 path,expected=SPECS[name]
 if not path.is_file():return {'model':name,'status':'missing','path':str(path),'rows':[]}
 assert digest(path)==expected,(name,'checkpoint hash mismatch')
 result={'model':name,'seed':42,'status':'COMPLETE','checkpoint':str(path),'checkpoint_sha256':expected,'rows':[]}
 neural=name in ('TA2','L1','F00')
 if neural:
  source=P/'cert-r42-feasibility/scripts'
  checks={'prototype_v3_node/architecture.py':'9867b0c266f3b735d138e2d8d53f0d3f5c5c644e25302c10c25e2f4677560abd','prototype_v3_node/odst.py':'95764ce80a7c80529108d8d6b72f6bd06896c39d065f7e475c12dce8421417bb','models/sequence_ensemble.py':'43f16bce9c09305c7578d319dadf4c23c6c18cbe70fd7dcc1fda0114c86d6475'}
  for rel,h in checks.items():assert digest(source/rel)==h,rel
  sys.path.insert(0,str(source));from prototype_v3_node.architecture import AttentionNodeEnsemble
  model=AttentionNodeEnsemble(input_dim=13,hidden_size=64,dropout=.2,attention_dim=64,fusion_variant='sparsemax_sigmoid_odst',node_num_layers=2,node_n_trees=4,node_depth=4,node_tree_dim=1,node_temperature=.5,node_dropout=0.,leaf_init_std=.05,gate_hidden_dim=32)
  payload=torch.load(path,map_location='cpu',weights_only=True)
  model.load_state_dict(payload['student_state_dict'] if name=='L1' else payload['model_state_dict'],strict=True);model.eval()
  # Extract only the exact frozen ODST forward function; no training/data module imports.
  source_text=gitshow('src/editor012_rescue/models.py');node=next(n for n in ast.parse(source_text).body if isinstance(n,ast.FunctionDef) and n.name=='live_odst_forward')
  ns={'torch':torch,'nn':torch.nn,'Editor012ProtocolError':RuntimeError};exec('from __future__ import annotations\n'+ast.unparse(node),ns);live=ns['live_odst_forward']
  result['forward_source_sha256']=hashlib.sha256(source_text.encode()).hexdigest();result['architecture_source_sha256']=checks
  head=None
  if name=='L1':
   head=torch.nn.Linear(128,1);head.load_state_dict({k.removeprefix('linear_head.linear.'):v for k,v in payload['modules_state_dict'].items()},strict=True);head.eval()
  class FrozenPredictor(torch.nn.Module):
   def __init__(self):super().__init__();self.base=model;self.head=head
   def forward(self,x):
    z,_=self.base.encode_attention_h(x)
    logit=self.head(z).squeeze(-1) if self.head is not None else live(self.base.node_head,z)['logit']
    return torch.sigmoid(logit)
  predictor=FrozenPredictor().eval()
  result['parameter_count_loaded']=sum(p.numel() for p in predictor.parameters())
  result['parameter_count_classification_path']=sum(p.numel() for component in [model.lstm,model.attention,head if name=='L1' else model.node_head] for p in component.parameters())
  result['forward_semantics']='Frozen encoder/attention and final classification head only; output sigmoid; stored historical linear head still computed by encode_attention_h but its output is unused; diagnostics dictionaries not retained'
  try:
   with torch.inference_mode(),torch.backends.mkldnn.flags(enabled=False),FlopCounterMode(display=False) as counter:predictor(torch.randn(1,20,13))
   result['FLOPs_per_sequence']=int(counter.get_total_flops())
   result['FLOP_operator_counts']={str(k):int(v) for k,v in counter.get_flop_counts().get('Global',{}).items()}
   result['FLOPs_scope']='torch.utils.flop_counter.FlopCounterMode; CPU batch 1, MKLDNN disabled for LSTM matrix-operation visibility; multiply+add=2; excludes elementwise/nonregistered operations'
  except Exception as exc:result['FLOPs_per_sequence']=None;result['FLOPs_error']=repr(exc)
 else:
  if name=='XGBoost_40':
   import xgboost
   predictor=xgboost.XGBClassifier();predictor.load_model(path)
   dumps=[json.loads(x) for x in predictor.get_booster().get_dump(dump_format='json')]
   def walk(node,depth=0):
    children=node.get('children',[]);stats=[walk(c,depth+1) for c in children]
    return 1+sum(s[0] for s in stats),max([depth]+[s[1] for s in stats])
   stats=[walk(t) for t in dumps];result.update(number_of_trees=len(dumps),total_nodes=sum(s[0] for s in stats),max_depth=max(s[1] for s in stats),features=int(predictor.n_features_in_))
  else:
   import joblib
   predictor=joblib.load(path)
   result.update(number_of_trees=len(predictor.estimators_),total_nodes=sum(t.tree_.node_count for t in predictor.estimators_),max_depth=max(t.tree_.max_depth for t in predictor.estimators_),features=int(predictor.n_features_in_),n_jobs=predictor.n_jobs)
  assert result['features']==40
  summary=json.loads((path.parent/'summary.json').read_text());result['training_wall_clock']={'total_seconds':summary.get('training_duration_sec','not recorded'),'per_epoch':'not applicable to tree models','source':str(path.parent/'summary.json'),'units':'seconds'}
 if neural:
  # Frozen neural histories contain epoch metrics but no per-epoch or total duration.
  history=path.parent/'history.json';history_data=json.loads(history.read_text()) if history.is_file() else []
  found=[]
  def time_fields(obj,loc=''):
   if isinstance(obj,dict):
    for k,v in obj.items():
     if any(s in k.lower() for s in ['training_time','duration','elapsed','wall_clock','epoch_time']):found.append({'field':loc+'/'+k,'value':v})
     if isinstance(v,(dict,list)):time_fields(v,loc+'/'+k)
   elif isinstance(obj,list):
    for i,v in enumerate(obj):time_fields(v,loc+'/'+str(i))
  time_fields(history_data)
  result['training_wall_clock']={'total':'not recorded','per_epoch':'not recorded','history_source':str(history),'history_sha256':digest(history) if history.is_file() else None,'duration_fields_found':found,'note':'No retraining; do not infer duration from file timestamps.'}

 devices=['cpu']+(['cuda'] if torch.cuda.is_available() and name!='RF_40' else [])
 if name=='RF_40':result['gpu_status']='SKIPPED: frozen sklearn RandomForestClassifier has no CUDA prediction backend'
 if not torch.cuda.is_available():result['gpu_status']='SKIPPED: CUDA unavailable'
 process=psutil.Process()
 for device in devices:
  if neural:predictor.to(device).eval()
  elif name=='XGBoost_40':predictor.set_params(device=device,n_jobs=min(8,os.cpu_count() or 1))
  for batch in [1,1024]:
   x=torch.randn(batch,20,13,device=device) if neural else np.random.default_rng(42).normal(size=(batch,40)).astype(np.float32)
   fn=(lambda:predictor(x)) if neural else (lambda:predictor.predict_proba(x))
   synchronize=(lambda:torch.cuda.synchronize()) if device=='cuda' else (lambda:None)
   rounds=[];memories=[];rss=[]
   for repeat in range(3):
    with torch.inference_mode():
     for _ in range(50):fn()
     synchronize()
     baseline=process.memory_info().rss;peak=[baseline];stop=threading.Event()
     def sample():
      while not stop.wait(.001):peak[0]=max(peak[0],process.memory_info().rss)
     sampler=None
     if not neural:sampler=threading.Thread(target=sample,daemon=True);sampler.start()
     if device=='cuda':torch.cuda.reset_peak_memory_stats()
     durations=[]
     for _ in range(200):
      synchronize();start=time.perf_counter();out=fn();synchronize();durations.append(time.perf_counter()-start)
     if not neural:
      peak[0]=max(peak[0],process.memory_info().rss);stop.set();sampler.join();rss.append({'peak_RSS_bytes':peak[0],'baseline_RSS_bytes':baseline,'increment_bytes':max(0,peak[0]-baseline)})
     if device=='cuda':memories.append(int(torch.cuda.max_memory_allocated()))
    rounds.append(float(np.median(durations)))
   med=float(np.median(rounds));row={'model':name,'seed':42,'device':device,'batch_size':batch,'warmup_batches_per_repeat':50,'timed_batches_per_repeat':200,'repeats':3,'repeat_median_latency_seconds':rounds,'median_latency_seconds':med,'throughput_sequences_per_second':batch/med,'peak_GPU_memory_bytes':int(np.median(memories)) if memories and neural else None,'peak_RSS_bytes':int(np.median([r['peak_RSS_bytes'] for r in rss])) if rss else None,'incremental_peak_RSS_bytes':int(np.median([r['increment_bytes'] for r in rss])) if rss else None,'memory_repeats':rss or (memories if neural else [])}
   if device=='cuda' and not neural:row['GPU_memory_note']='PyTorch allocator peak excludes XGBoost CUDA allocations; native XGBoost peak GPU memory unavailable from this counter'
   result['rows'].append(row);write(name+'_partial.json',result);print(name,device,batch,round(med*1000,4),'ms',flush=True)
  if neural and device=='cuda':predictor.cpu();torch.cuda.empty_cache()
 assert digest(path)==expected,'frozen checkpoint changed'
 return result

def main():
 import torch,platform,numpy as np,psutil
 try:gpu=subprocess.check_output([r'C:\Windows\System32\nvidia-smi.exe','--query-gpu=name,uuid,driver_version,memory.total','--format=csv,noheader']).decode().strip()
 except Exception as exc:gpu=repr(exc)
 cpu=subprocess.check_output(['powershell.exe','-NoProfile','-Command','Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress']).decode().strip()
 info={'python':sys.version,'executable':sys.executable,'torch':torch.__version__,'numpy':np.__version__,'cuda':torch.version.cuda,'cudnn':torch.backends.cudnn.version(),'GPU':gpu,'CPU':json.loads(cpu),'RAM_bytes':psutil.virtual_memory().total,'torch_threads':min(8,os.cpu_count() or 1),'torch_interop_threads':1,'synthetic_shapes':{'neural':[20,13],'tabular':[40]},'random_seed':42,'timing':'50 warm-up + 200 individually timed batches per repeat; three repeats, median of repeat medians; CUDA synchronize before/after each timed batch; no compilation/AMP/TF32','GPU_memory_scope':'torch allocator, not whole-device memory; CPU tree RSS sampled at 1 ms including predictor process baseline','models':[]}
 write('efficiency_profile.json',info)
 for name in SPECS:
  proc=subprocess.run([sys.executable,'-B',__file__,'--model',name],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  (HERE/(name+'_console.txt')).write_text(proc.stdout+'\n'+proc.stderr)
  print(proc.stdout,flush=True)
  file=HERE/(name+'_result.json')
  info['models'].append(json.loads(file.read_text()) if file.is_file() else {'model':name,'status':'FAILED','exit_code':proc.returncode,'detail':proc.stderr[-4000:],'rows':[]})
  write('efficiency_profile.json',info)
 rows=[r for model in info['models'] for r in model.get('rows',[])]
 fields=['model','seed','device','batch_size','median_latency_seconds','throughput_sequences_per_second','peak_GPU_memory_bytes','peak_RSS_bytes','incremental_peak_RSS_bytes','warmup_batches_per_repeat','timed_batches_per_repeat','repeats']
 with (HERE/'efficiency_profile.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
 complexity=[]
 for model in info['models']:
  training=model.get('training_wall_clock',{})
  complexity.append({**{k:model.get(k) for k in ['model','seed','parameter_count_loaded','parameter_count_classification_path','FLOPs_per_sequence','number_of_trees','total_nodes','max_depth']},'training_total_seconds':training.get('total_seconds',training.get('total','not recorded')),'training_per_epoch':training.get('per_epoch','not recorded'),'CPU':str(info['CPU']),'GPU':info['GPU']})
 with (HERE/'model_complexity_and_training.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(complexity[0]));w.writeheader();w.writerows(complexity)
 print('EFFICIENCY_COMPLETE',len(rows),flush=True)
if __name__=='__main__':
 if '--model' in sys.argv:
  name=sys.argv[sys.argv.index('--model')+1]
  try:write(name+'_result.json',run_model(name))
  except Exception as exc:write(name+'_result.json',{'model':name,'status':'FAILED','reason':repr(exc),'traceback':traceback.format_exc(),'rows':[]});raise
 else:main()

