"""Pre-push audit for public copies (R2 revision).
Usage: python audit_public_copy.py <folder>
Flags CERT-style user IDs (AAA0000), absolute personal paths, CERT raw/answer
file names, binary/checkpoint extensions, files >10 MB and any private/ folder.
PNG files are skipped for text checks. Every finding must be reviewed by hand."""
import os,re,sys,collections
root=sys.argv[1]
uid=re.compile(rb'\b[A-Z]{3}[0-9]{4}\b')
paths=re.compile(rb'(?i)([A-Z]:[\\/]{1,2}(PhD|Users)|/sessions/|/home/[a-z]|\\\\Users\\\\|OneDrive|alriyami7777@gmail)')
cert=re.compile(rb'(?i)(answers?[_/\\-]|insiders\.csv|psychometric|LDAP|r5\.2[_/\\]test|logon\.csv|device\.csv|http\.csv|email\.csv|file\.csv)')
bad_ext={'.pt','.pth','.ckpt','.npz','.npy','.pkl','.joblib','.parquet','.h5','.safetensors','.feather','.zip'}
hits=collections.defaultdict(list)
for dp,dn,fn in os.walk(root):
  if 'private' in dp.split(os.sep): hits['PRIVATE_DIR'].append(dp)
  for f in fn:
    p=os.path.join(dp,f); rel=os.path.relpath(p,root); ext=os.path.splitext(f)[1].lower()
    if ext in bad_ext: hits['BINARY_EXT'].append(rel)
    if os.path.getsize(p)>10e6: hits['BIG'].append(rel)
    if ext=='.png': continue
    b=open(p,'rb').read()
    for name,rx in (('USERID',uid),('ABSPATH',paths),('CERTNAME',cert)):
      m=sorted(set(x.group(0).decode(errors='replace') for x in rx.finditer(b)))
      if m: hits[name].append((rel,len(m),m[:6]))
for k,v in hits.items():
  print('==',k,len(v))
  for x in v[:40]: print('  ',x)
print('DONE', sum(len(v) for v in hits.values()),'findings')
