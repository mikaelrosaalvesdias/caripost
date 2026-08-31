"""Falha o CI quando as tres strings de versao saem de sincronia.

app/main.py `version=`, app/os/apps-manage.jsx `MP_OS_VERSION` e o `?v=` de
app/os/index.html precisam apontar para a mesma versao — senao o navegador
serve JSX antigo depois do deploy.
"""
import pathlib
import re
import sys

main_py = pathlib.Path("app/main.py").read_text()
manage = pathlib.Path("app/os/apps-manage.jsx").read_text()
index = pathlib.Path("app/os/index.html").read_text()

api = re.search(r'FastAPI\(title="[^"]*", version="([\d.]+)"', main_py)
osv = re.search(r"MP_OS_VERSION\s*=\s*'v([\d.]+)'", manage)
bust = set(re.findall(r"\?v=(\d+)", index))

if not api or not osv:
    sys.exit("nao foi possivel ler as versoes de app/main.py ou apps-manage.jsx")

api_v, os_v = api.group(1), osv.group(1)
expected_bust = api_v.replace(".", "")

problems = []
if api_v != os_v:
    problems.append(f"main.py={api_v} != MP_OS_VERSION={os_v}")
stale = sorted(b for b in bust if b != expected_bust)
if stale:
    problems.append(f"cache-bust ?v= desatualizado: {stale} (esperado {expected_bust})")

if problems:
    sys.exit("versoes fora de sincronia:\n- " + "\n- ".join(problems))
print(f"versoes em sincronia: {api_v} (cache-bust {expected_bust})")
