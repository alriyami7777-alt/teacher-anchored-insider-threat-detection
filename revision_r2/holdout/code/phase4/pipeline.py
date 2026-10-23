"""Sequential unattended completion. Never retries holdout inference."""
from common import *
import subprocess,traceback
def main():
    PRIVATE.mkdir(parents=True,exist_ok=True)
    with (PRIVATE/'PIPELINE_STARTED.json').open('x') as f:json.dump(dict(utc=utc(),pid=os.getpid(),code_sha256=sha(__file__)),f)
    while True:
        p=P4/'STATUS.json'
        if p.exists():
            s=json.loads(p.read_text())
            if s['stage']=='TRAINING_FINISHED':break
            assert s['stage']=='TRAINING','Refuse to take over an already executing scoring pipeline'
        time.sleep(5)
    stages=[('freeze_preflight',['score.py','--freeze-preflight']),('score_once',['score.py','--execute-once']),('metrics',['metrics.py']),('explanation',['explain.py']),('report',['report.py'])]
    for name,args in stages:
        target=PRIVATE/'logs'/f'pipeline_{name}.log';target.parent.mkdir(exist_ok=True)
        print(utc(),'START',name,flush=True)
        with target.open('x',encoding='utf-8') as log:
            rc=subprocess.call([sys.executable,'-B',str(CODE/args[0]),*args[1:]],cwd=CODE,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        print(utc(),'FINISH',name,'exit',rc,flush=True)
        if rc:
            dump(P4/'PIPELINE_FAILURE.json',dict(utc=utc(),stage=name,exit_code=rc,no_scoring_retries=True,private_log=str(target)))
            raise RuntimeError('Pipeline stopped at '+name+'; scoring is never retried')
    assert (P4/'CHATGPT_PHASE4_REPORT.md').read_text().rstrip().endswith('PHASE4_COMPLETE')
    print('PHASE4_COMPLETE',flush=True)
if __name__=='__main__':main()
