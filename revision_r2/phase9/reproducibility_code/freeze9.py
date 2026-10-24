from common9 import *
def main():
 gate();assert read(OUT/'DEVELOPMENT_NUMERICAL_VERIFICATION.json')['all_checks_passed'];p=OUT/'ANALYSIS_CODE_FROZEN.json';assert not p.exists()
 names=('common9.py','prepare9.py','stats9.py','infer9.py','transfer_analysis9.py','lead9.py','ensemble9.py','attribution9.py','routes9.py','attacks9.py','robust_analysis9.py','pipeline9.py');deps=[ROOT/'phase2_runtime.py',Path(rt.student_forward.__code__.co_filename),Path(rt.AttentionNodeEnsemble.__init__.__code__.co_filename)]
 dump(p,dict(utc=utc(),code={n:sha(CODE/n) for n in names},dependencies={str(p):sha(p) for p in deps},amendment9_sha256=read(OUT/'AMENDMENT9_RECEIPT.json')['sha256']));status('ANALYSIS_METHODS_FROZEN')
if __name__=='__main__':main()
