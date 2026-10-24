from common10 import *
def main():
 # One-shot presentation refresh after the sole live writer exits. No training,
 # inference, bootstrap or new contrast computation is performed here.
 while not (OUT/'REPORT_FINISHED.json').exists() and time.time()<DEADLINE+60:time.sleep(1)
 log=P/'logs/final_presentation_refresh.log'
 with log.open('w',encoding='utf8') as h:
  proc=subprocess.Popen([str(PY),'-X','utf8','-B',str(CODE/'report10.py'),'--final'],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
  rc=proc.wait(timeout=120)
 assert rc==0,log.read_text(encoding='utf8')
 dump(OUT/'FINAL_PRESENTATION_READY.json',dict(utc=utc(),report_sha256=sha(OUT/'CHATGPT_PHASE10_REPORT.md'),result_sha256=sha(OUT/'PHASE10_RESULTS.json'),figure_receipt=read(OUT/'FIGURE_RECEIPT.json'),no_scientific_rerun=True));print('FINAL_PRESENTATION_READY',flush=True)
if __name__=='__main__':main()
