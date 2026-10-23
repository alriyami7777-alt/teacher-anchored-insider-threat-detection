from pathlib import Path
import numpy as np, pyarrow.parquet as pq, json, subprocess
root=Path(r'C:\PhD\07_Projects\cert-r42-feasibility')
for split in ('train','validation'):
    with np.load(root/f'data/processed/r5.2/tensors/r52_T20_s1_{split}.npz',allow_pickle=True) as z:
        print(split,'keys:',z.files)
        for k in ('start_date','end_date'):
            a=z[k].astype(str)
            print(k,str(min(a)),str(max(a)))
        print('users:',len(set(z['user'].astype(str))),'windows:',len(z['y']),'positives:',int(z['y'].sum()))
p=root/'data/processed/r5.2/interval_level/r52_user_day_intervals_dense.parquet'
pf=pq.ParquetFile(p)
print('daily schema:',pf.schema_arrow,'rowgroups:',pf.num_row_groups)
print('first group date stats:',pf.metadata.row_group(0).column(pf.schema_arrow.names.index('interval_date')).statistics)
repo=r'C:\PhD\07_Projects\teacher-anchored-insider-threat-detection'
git=['git','-c','safe.directory='+repo.replace('\\','/'),'-C',repo]
dest=Path(r'C:\PhD\07_Projects\r2_holdout')
ref='editor023-positive-architecture-value'
paths=subprocess.check_output(git+['ls-tree','-r','--name-only',ref,'--','src/editor012_rescue','src/editor023_architecture_value'],text=True).splitlines()
for name in paths:
    if name.endswith('.py'):
        target=dest/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(subprocess.check_output(git+['show',ref+':'+name]))
print('Additional frozen source files:',len(paths))

