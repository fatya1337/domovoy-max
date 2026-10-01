"""Package reproducible sources only; reject known runtime credentials."""
from pathlib import Path
import hashlib
import zipfile
import subprocess

root=Path(__file__).resolve().parent
files=[p for p in root.iterdir() if p.is_file() and (p.suffix in ('.py','.md','.yaml') or p.name in ('Dockerfile','Dockerfile.app','Caddyfile','requirements.txt','requirements-dev.txt','openapi.json','test_request.js','.env.example','.env.pilot.example','.gitignore','.dockerignore'))]
for folder in ('web','certs','fixtures','docs'):
    files.extend(p for p in (root/folder).rglob('*') if p.is_file())
for name in ('output/pdf/domovoy-stage-v9.pdf','output/presentation/domovoy-stage-v9.pptx'):
    artifact=root/name
    if not artifact.is_file():raise SystemExit('Missing current presentation artifact; archive aborted')
    files.append(artifact)
extras=[root.parent/n for n in ('PRODUCT-VISION.md','CASE-GAP.md') if (root.parent/n).is_file()]
secrets=[]
for env in (root/'.env',root/'data/preview.env',root/'.env.pilot'):
    if not env.exists():continue
    for line in env.read_text().splitlines():
        key,_,value=line.partition('=')
        if key in ('MAX_BOT_TOKEN','MAX_WEBHOOK_SECRET') and len(value.strip())>8:
            secrets.append(value.strip().strip('\"\'').encode())
for p in files+extras:
    if any(secret in p.read_bytes() for secret in secrets):raise SystemExit('Credential detected; archive aborted')
out=root/'output/domovoy-pilot.zip';out.parent.mkdir(exist_ok=True)
try:
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True,stderr=subprocess.DEVNULL).strip()
except (OSError,subprocess.CalledProcessError):
    revision='unversioned'
(root/'output/REVISION.txt').write_text(revision+'\n')
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(files, key=lambda p: (p.suffix not in ('.pdf', '.pptx'), str(p))):
        archive_name=('Presentation/domovoy-salfetka5'+p.suffix) if p.suffix in ('.pdf', '.pptx') else 'smart-city-bot/'+str(p.relative_to(root))
        z.write(p,archive_name)
    z.writestr('00-START-HERE.txt', 'ДОМОВОЙ / salfetka5\n\n1. Presentation/domovoy-salfetka5.pdf — презентация решения.\n2. Presentation/domovoy-salfetka5.pptx — редактируемая копия.\n3. smart-city-bot/REVIEWER-GUIDE.md — инструкция проверки.\n4. smart-city-bot/ — исходники, тесты и документация.\n5. SOURCE-REVISION.txt — зафиксированная ревизия исходников.\n\nБот: https://max.ru/t738_hakaton_max_bot\nМиниаппа: https://domovoy-doma.ru/ (открывать кнопкой в MAX)\n')
    for p in extras:z.write(p,p.name)
    z.writestr('SOURCE-REVISION.txt',revision+'\n')
(root/'output/domovoy-pilot.sha256').write_text(hashlib.sha256(out.read_bytes()).hexdigest()+'  domovoy-pilot.zip\n')
print('Source archive updated; credential check passed:',len(files)+len(extras),'files')
