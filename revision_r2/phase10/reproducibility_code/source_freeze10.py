from common10 import *
gate();dest=OUT/'SOURCE_INTEGRITY_FROZEN.json';assert not dest.exists();sources=[]
for s in SEEDS:
 for n in (*MODELS,'T-OPT'):
  z=oldspec(n,s);assert sha(z['checkpoint'])==z['sha256'];sources.append(dict(path=z['checkpoint'],sha256=z['sha256'],role='frozen original checkpoint'))
 for n in MODELS:
  p=P5/f'private/transfer/r6.2/development_{n}_{s}.npy';sources.append(dict(path=str(p),sha256=sha(p),role='cached r6.2 zero-shot scores'))
  p=HP/f'phase4/scores/{n}_{s}.npz';sources.append(dict(path=str(p),sha256=sha(p),role='cached r5.2 original scores'))
for name in ('scaled_dense_daily.npy','window_index.npy','completed_window_labels.npy','malicious_day_labels.npy','calendar_dates.npy','user_ids.npy'):
 p=B/name;sources.append(dict(path=str(p),sha256=sha(p),role='immutable r6.2 source'))
for part in ('train','validation'):
 for name in ('X','y','X40'):
  p=HP/f'tensors/{part}_{name}.npy';sources.append(dict(path=str(p),sha256=sha(p),role='original development only tensor'))
p=R2/'phase9/CHATGPT_PHASE9_REPORT.md';sources.append(dict(path=str(p),sha256=sha(p),role='completed Phase9 report'))
dump(dest,dict(utc=utc(),sources=sources,read_test=False));dump(OUT/'ANALYSIS_CODE_FROZEN.json',dict(utc=utc(),code={n:sha(CODE/n) for n in ('stats10.py','contrasts10.py','analysis_worker10.py')}))
dump(OUT/'SPLIT_METADATA_ACCESS_CORRECTION.json',dict(utc=utc(),split_receipt_sha256=sha(OUT/'R62_SPLIT_RECEIPT.json'),correction='The split receipt field features_or_labels_opened=false is inaccurate for labels: completed-window labels and window user indices were read ONLY to derive the 29-user stratification status under the hashed pre-split clarification. No feature data, scores, metrics or training were read before split hashing. The frozen split and indices are unchanged.',insider_status_sha256=sha(P/'INSIDER_STATUS.npy'),split_only_label_sources=[s for s in sources if Path(s['path']).name in ('completed_window_labels.npy','window_index.npy')]))
print('SOURCE_AND_ANALYSIS_FROZEN',flush=True)
