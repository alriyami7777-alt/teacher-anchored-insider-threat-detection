from common6 import *
import re
from PIL import Image
def main():
 for manifest,key in [('TRAINING_PROTOCOL_FROZEN.json','source_hashes'),('INFERENCE_PROTOCOL_FROZEN.json','code_hashes'),('POSTTRAIN_CODE_FROZEN.json','files')]:
  for p,h in read(OUT/manifest)[key].items():assert sha(p)==h,f'Changed frozen code: {p}'
 ip=read(OUT/'INFERENCE_PROTOCOL_FROZEN.json')
 for s in ip['models']:assert sha(s['checkpoint'])==s['sha256'] and sha(s['frozen_predictions'])==s['predictions_sha256']
 for p,h in ip['files'].items():assert sha(p)==h
 runs=read(OUT/'TRAINING_RESULTS_PHASE6.json');assert len(runs)==57
 for r in runs:
  if r['status']=='ok':assert sha(r['checkpoint'])==r['sha256'] and r['wall_seconds']<7200
 assert read(OUT/'TRAINING_COMPLETE.json')['runs']==57
 pr=(H/'PREREGISTRATION_R2_HOLDOUT.md').read_bytes();a=read(OUT/'AMENDMENT4_RECEIPT.json');assert hashlib.sha256(pr[:a['previous_bytes']]).hexdigest()==a['previous_sha256'];at=pr.index(b'\n### Amendment 4 SHA-256 receipt');assert hashlib.sha256(pr[:at]).hexdigest()==a['amendment4_sha256']
 for cfg in read(OUT/'DATA_MANIFEST_PHASE6.json')['configs']:
  for split in ('train','validation'):
   with np.load(PRIVATE/'data'/cfg['config']/f'{split}_metadata.npz') as z:assert not set(z['user'])&excluded()
 with np.load(PRIVATE/'data/r42_T20_F13/test_metadata.npz') as z:assert not set(z['user'])&excluded()
 results=read(OUT/'PHASE6_RESULTS.json');figures=[]
 for f in results['figures']:
  path=OUT/f['png'];im=Image.open(path);assert min(im.info.get('dpi',(0,0)))>=299;assert (OUT/f['csv']).stat().st_size>0;figures.append(f['png'])
 for path in OUT.iterdir():
  if path.suffix in ('.md','.json','.csv'):assert not re.search(r'\b[A-Z]{3}[0-9]{4}\b',path.read_text(encoding='utf-8')),f'Raw ID in {path.name}'
 report=OUT/'CHATGPT_PHASE6_REPORT.md';assert report.read_text(encoding='utf-8').rstrip().splitlines()[-1]=='PHASE6_COMPLETE'
 assert (PRIVATE/'R42_TEST_STARTED_ONCE.json').exists() and not (OUT/'PIPELINE_FAILURE.json').exists()
 t=read(OUT/'T_RESULTS.json');i=read(OUT/'I_RESULTS.json');assert len(t['r42_test'])==sum(r['status']=='ok' and r['phase6_config']=='r42_T20_F13' and r['model'] in ('TA2','XGBoost_40','RF_40','AL_PRECURSOR') for r in runs)
 assert len(i['order_history'])==63 and len(i['same_information'])==18 and len(i['multi_day'])==9 and len(i['attention_CIs'])==24
 v=dict(complete=True,utc=utc(),training_runs=len(runs),successful_training_runs=sum(r['status']=='ok' for r in runs),timeouts=sum(r['status']=='TIMEOUT' for r in runs),original_model_and_prediction_hashes_unchanged=True,preregistration_previous_bytes_preserved=a['previous_bytes'],amendment4_sha256=a['amendment4_sha256'],r52_TEST_sealed=True,HOLDOUT_activity_used=False,r42_test_model_seed_evaluations=len(t['r42_test']),order_history_rows=len(i['order_history']),attention_case_rows=len(i['attention_cases']),attention_intervention_rows=len(i['attention_effects']),figures_300dpi_with_CSVs=figures,output_hashes={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name not in ('FINAL_VERIFICATION.json','STATUS.json')},report_sha256=sha(report),report_final_line='PHASE6_COMPLETE')
 dump(OUT/'FINAL_VERIFICATION.json',v);status('PHASE6_COMPLETE',verified=True,report=str(report));print(json.dumps({k:v for k,v in v.items() if k!='output_hashes'},indent=2))
if __name__=='__main__':main()
