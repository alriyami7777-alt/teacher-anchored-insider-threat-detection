from common9 import *
if __name__=='__main__':
 gate();p=OUT/'SUPPLEMENTARY_METHODS_FROZEN.json';assert not p.exists();dump(p,dict(utc=utc(),code={n:sha(CODE/n) for n in ('clarification9.py','source_targets9.py')},malicious_source_targets_sha256=sha(OUT/'L7_MALICIOUS_SOURCE_TARGETS_FROZEN.json'),clarification_receipt_sha256=sha(OUT/'AMENDMENT9_CLARIFICATION_RECEIPT.json'),r52_test_read=False));print('SUPPLEMENTARY_METHODS_FROZEN',flush=True)
