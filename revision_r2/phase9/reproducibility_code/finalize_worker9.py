from common9 import *
def main():
 while not (OUT/'ANALYSES_COMPLETE.json').exists():time.sleep(5)
 for script in ('figures9.py','report9.py'):
  r=child(script,[],f'finalize_{script}')
  if r['status']!='ok':status('FINALIZATION_FAILED',result=r);return
 status('AWAITING_VISUAL_QA')
 while not (OUT/'VISUAL_QA_RECEIPT.json').exists():time.sleep(5)
 r=child('verify9.py',[],'finalize_verify9.py');status('FINALIZATION_FINISHED',result=r)
if __name__=='__main__':main()
