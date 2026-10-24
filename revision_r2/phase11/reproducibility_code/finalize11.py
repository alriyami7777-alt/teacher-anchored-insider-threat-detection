from common11 import *
def main():
 while not (OUT/'REPORT_FINISHED.json').exists() and time.time()<DEADLINE+60:time.sleep(1)
 log=P/'logs/final_presentation_refresh.log'
 with log.open('w',encoding='utf8') as h:
  proc=subprocess.Popen([str(PY),'-X','utf8','-B',str(CODE/'report11.py'),'--final'],stdout=h,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW);code=proc.wait(timeout=120)
 assert code==0,log.read_text(encoding='utf8');dump(OUT/'FINAL_PRESENTATION_READY.json',dict(utc=utc(),report_sha256=sha(OUT/'CHATGPT_PHASE11_REPORT.md'),results_sha256=sha(OUT/'PHASE11_RESULTS.json')));print('FINAL_PRESENTATION_READY',flush=True)
if __name__=='__main__':main()
