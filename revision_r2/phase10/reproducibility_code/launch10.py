from common10 import *
gate()
for p in CODE.glob('*.py'):compile(p.read_text(encoding='utf8'),str(p),'exec')
f=OUT/'TRAINING_CODE_FROZEN.json'
if f.exists():
 assert not list((P/'training').glob('*/results/*.json'));f.rename(OUT/'TRAINING_CODE_FROZEN_PRE_SYNTAX_FIX.json')
dump(f,dict(utc=utc(),runtime_sha256=sha(ROOT/'phase2_runtime.py'),code={n:sha(CODE/n) for n in ('common10.py','prepare10.py','train10.py','infer10.py','worker10.py','p1_10.py')}));print('CODE_FROZEN',flush=True)
from worker10 import main
main()
