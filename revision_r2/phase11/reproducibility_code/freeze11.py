from common11 import *
def main():
 gate();assert not (OUT/'TRAINING_CODE_FROZEN.json').exists();names=('common11.py','prepare11.py','train11.py','infer11.py','worker11.py','cutoff11.py');dump(OUT/'TRAINING_CODE_FROZEN.json',dict(utc=utc(),code={n:sha(CODE/n) for n in names},runtime_sha256=sha(ROOT/'phase2_runtime.py'),training_not_started=True))
 baseline=read(P10/'SOURCE_INTEGRITY_FROZEN.json')['sources'];evaluation=read(P10/'EVALUATION_INPUTS_FROZEN.json')['sources'];sources={x['path']:x['sha256'] for x in baseline+evaluation}
 for path,value in sources.items():assert sha(path)==value,Path(path).name+' changed since Phase10'
 for path in B.glob('*.npy'):sources[str(path)]=sha(path)
 for path in (P10/'R62_SPLIT_RECEIPT.json',P10/'FINAL_AUDIT.json',P10/'CHATGPT_PHASE10_REPORT.md',P10/'private/DEVELOPMENT_indices.npy',P10/'private/HOLDOUT_indices.npy',P10/'CROSS_RELEASE_USER_DISJOINTNESS.json',R2/'CHATGPT_PHASE11_PROMPT.md'):sources[str(path)]=sha(path)
 dump(OUT/'SOURCE_INTEGRITY_FROZEN.json',dict(utc=utc(),read_test=False,sources=[dict(path=p,sha256=v) for p,v in sources.items()],pre_training=True))
 r62=set(map(str,np.load(B/'user_ids.npy')));r52dev=set((HP/'DEVELOPMENT_USERS.txt').read_text().splitlines());r52hu=set((HP/'HOLDOUT_USERS.txt').read_text().splitlines());assert len(r52dev)==1500 and len(r52hu)==500
 overlap=len(r62&(r52dev|r52hu));cross=dict(utc=utc(),all_release_ID_overlap=overlap,r62_all_overlap_r52_development=len(r62&r52dev),r62_all_overlap_r52_holdout=len(r62&r52hu),r52_development_holdout_overlap=len(r52dev&r52hu),source_lists_pseudonymized=all(x.startswith('U_') for x in r52dev|r52hu),raw_IDs_disclosed=False,phase10_check=read(P10/'CROSS_RELEASE_USER_DISJOINTNESS.json'))
 assert overlap==0 and not r52dev&r52hu;dump(OUT/'CROSS_RELEASE_USER_DISJOINTNESS.json',cross);print('SOURCE_AND_CODE_FROZEN',len(sources),flush=True)
if __name__=='__main__':main()
