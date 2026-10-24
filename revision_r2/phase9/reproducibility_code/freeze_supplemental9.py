from common9 import *
if __name__=='__main__':
 gate();p=OUT/'SUPPLEMENTAL_STATISTICS_CODE_FROZEN.json';assert not p.exists();dump(p,dict(utc=utc(),code={n:sha(CODE/n) for n in ('supplemental9.py','stats9.py','common9.py')},purpose='Complete predeclared marginal CIs and L3 non-AUC seed-mean CIs using saved scores/ranks and the same fixed2000 user bootstrap; no new scoring, hypotheses or parameter tuning.'));print('SUPPLEMENTAL_STATISTICS_CODE_FROZEN',flush=True)
