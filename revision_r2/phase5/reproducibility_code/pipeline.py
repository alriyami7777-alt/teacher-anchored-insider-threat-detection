from p5common import *
import subprocess
def main():
    PRIVATE.mkdir(parents=True,exist_ok=True)
    with (PRIVATE/'PIPELINE_STARTED.json').open('x') as f:json.dump(dict(utc=utc(),pid=os.getpid(),no_training=True,r52_test_sealed=True),f)
    stages=[('prepare',['prepare.py']),('transfer_r51',['transfer.py','--release','r5.1']),('transfer_r62',['transfer.py','--release','r6.2']),('robustness_score',['robust.py']),('transfer_analysis',['transfer.py','--analyze']),('robustness_analysis',['robust.py','--analyze']),('operational',['operational.py']),('ranking_and_stability',['ranking_stats.py']),('calibration',['calibration.py']),('report',['report.py'])]
    for name,args in stages:
        log=PRIVATE/'logs'/f'{name}.log';log.parent.mkdir(exist_ok=True);print(utc(),'START',name,flush=True)
        with log.open('x',encoding='utf-8') as h:rc=subprocess.call([sys.executable,'-B',str(CODE/args[0]),*args[1:]],cwd=CODE,stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        print(utc(),'FINISH',name,'exit',rc,flush=True)
        if rc:
            dump(OUT/'PIPELINE_FAILURE.json',dict(utc=utc(),stage=name,exit_code=rc,scoring_retries=0,private_log=str(log)));raise RuntimeError('Stage failed; no scoring rerun permitted: '+name)
    assert (OUT/'CHATGPT_PHASE5_REPORT.md').read_text(encoding='utf-8').rstrip().endswith('PHASE5_COMPLETE');print('PHASE5_COMPLETE',flush=True)
if __name__=='__main__':main()
