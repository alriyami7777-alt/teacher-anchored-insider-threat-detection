from common6 import *
import ast
assert not (OUT/'POSTTRAIN_CODE_FROZEN.json').exists()
for p in CODE.glob('*.py'):ast.parse(p.read_text(encoding='utf-8'))
from bootstrap6 import selfcheck
selfcheck()
dump(OUT/'POSTTRAIN_CODE_FROZEN.json',dict(utc=utc(),files={str(CODE/n):sha(CODE/n) for n in ('training_analysis6.py','report6.py','verify6.py','pipeline6.py')},policy='Frozen before Part I inference, design-choice analyses, and r4.2 TEST access; inference6.py separately frozen earlier. r4.2 TEST one-pass per selected model/seed after training/checkpoint/threshold freeze.'))
print('Post-training analysis code frozen',flush=True)
