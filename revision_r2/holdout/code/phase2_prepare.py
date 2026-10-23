from pathlib import Path
import subprocess, hashlib, json, datetime

REPO = Path(r'C:\PhD\07_Projects\teacher-anchored-insider-threat-detection')
ROOT = Path(r'C:\PhD\07_Projects\r2_holdout')
OUT = Path(r'C:\PhD\04_Journal_Papers\Latest IEEE Access Paper July 2026\R2_revision\holdout')
assert not ROOT.exists(), 'Refusing to overwrite existing isolated project'
assert not OUT.exists(), 'Refusing to overwrite existing holdout output'
ROOT.mkdir()
OUT.mkdir()
(OUT/'private').mkdir()
request = Path(r'<PRIVATE_PATH_TO_PROMPT_TEXT>').read_text(encoding='utf-8')
body = request.split('Create holdout\\PREREGISTRATION_R2_HOLDOUT.md containing exactly these decisions:\n', 1)[1].split('\nThen compute and append:', 1)[0]
stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
content = '# R2 user-disjoint holdout preregistration\n\nFrozen UTC: '+stamp+'\n\n'+body+'\n'
p = OUT/'PREREGISTRATION_R2_HOLDOUT.md'
p.write_text(content, encoding='utf-8', newline='\n')
digest = hashlib.sha256(p.read_bytes()).hexdigest()
with p.open('a', encoding='utf-8', newline='\n') as f:
    f.write('\n## Pre-split freeze receipt\n\nSHA-256 of all bytes preceding this receipt: `'+digest+'`\n\nUTC: '+stamp+'\n\nNo split exists at this timestamp.\n')
(ROOT/'PREREGISTRATION_BASELINE.md').write_text(content,encoding='utf-8',newline='\n')
git = ['git','-c','safe.directory='+REPO.as_posix(),'-C',str(REPO)]
ref = 'editor011-matched-route-confirmation'
paths = subprocess.check_output(git+['ls-tree','-r','--name-only',ref,'--','src','configs'],text=True).splitlines()
manifest=[]
for name in paths:
    if not (name.endswith('.py') or name.endswith('.yaml')): continue
    data=subprocess.check_output(git+['show',ref+':'+name])
    target=ROOT/name
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(data)
    manifest.append({'path':name,'sha256':hashlib.sha256(data).hexdigest()})
(ROOT/'SOURCE_SNAPSHOT.json').write_text(json.dumps({'git_ref':ref,'commit':subprocess.check_output(git+['rev-parse',ref],text=True).strip(),'files':manifest},indent=2))
print(json.dumps({'preregistration':str(p),'pre_split_sha256':digest,'source_files':len(manifest),'code_root':str(ROOT)}))
