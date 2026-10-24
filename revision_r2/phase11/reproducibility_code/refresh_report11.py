from common11 import *
import psutil
def main():
 history=P/'control_history/report_writer_refresh';assert not history.exists();history.mkdir(parents=True);candidates=[]
 for proc in psutil.process_iter(['pid','cmdline']):
  try:
   if str(CODE/'report_worker11.py') in (proc.info['cmdline'] or []):candidates.append(proc)
  except (psutil.NoSuchProcess,psutil.AccessDenied):pass
 assert candidates,'Expected exactly the owned presentation worker launcher/interpreter'
 for proc in reversed(candidates):
  try:proc.kill()
  except psutil.NoSuchProcess:pass
 for proc in candidates:
  try:proc.wait(timeout=10)
  except psutil.NoSuchProcess:pass
 for name in ('CHATGPT_PHASE11_REPORT.md','PHASE11_RESULTS.json','FIGURE_RECEIPT.json'):
  path=OUT/name
  if path.exists():(history/name).write_bytes(path.read_bytes())
 dump(OUT/'REPORT_WRITER_REFRESH_RECEIPT.json',dict(utc=utc(),owned_presentation_PIDs_stopped=[p.pid for p in candidates],scientific_training_inference_analysis_uninterrupted=True,no_heldout_rescoring=True,reason='Load current report-only findings, original-r52 comparisons and coverage/guard provenance; fresh writer starts immediately'))
 print('OWNED_PRESENTATION_WRITER_STOPPED',flush=True)
if __name__=='__main__':main()
