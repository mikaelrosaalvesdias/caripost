# creative_engine — Motor de composição de criativos (CARIAP)

A IA gera SÓ a imagem (pessoa/cena). Este motor posiciona o TEXTO por código:
**nunca** sobre rosto/mão/objeto (confiabilidade) e com **variedade de tratamentos**
(criatividade). CPU-only, determinístico dado um seed.

## 3 camadas
- `detect.py` — YOLO11n-seg (person + objetos COCO + silhueta) + MediaPipe Face/Hand → mapa de proteção.
- `placement.py` — **Maximal Empty Rectangle**: maior espaço livre em QUALQUER posição do sujeito.
- `treatments.py` — tratamentos distintos (column_glass, column_solid, scrim_float, big_type_bleed, behind_subject). Os ousados usam a silhueta.

## Rodar local (com deps)
```
pip install -r requirements.txt
python __main__.py entrada.png --config blocks.json --seed 42 -o saida.png --debug
```

## Docker (CPU-only)
```
docker build -t caripost-creative .
docker run --rm -v $PWD:/data caripost-creative /data/entrada.png --config /data/blocks.json -o /data/saida.png --debug
```

## Validar SEM GPU/deps (placement + treatments com detecção MOCK)
```
python test_positions.py        # 5 posições do sujeito; valida texto fora do proibido/rosto
python __main__.py entrada.png --mock right --treatment behind_subject -o out.png --debug
```
`--mock right|left|center|corner|two` usa detecções simuladas (sem YOLO/MediaPipe).

## API (pra integrar no Caripost)
```python
from compose import compose_creative
out, meta = compose_creative(pil_image, blocks, art_config={"treatment":"column_solid","accent":"#ED5E1F"}, seed=42)
```
`meta` traz tratamento, regiões protegidas e zonas. Para manter a marca (logo/rodapé/fonte),
use as ZONAS de `meta["zones"]` e desenhe com o composer da Caripost.

## Critérios de aceite
- Rosto NUNCA coberto (padding maior no rosto).
- Texto nunca intersecta área proibida.
- Maximal rect validado: direita, esquerda, centro, canto, 2 sujeitos (`test_positions.py`).
- ≥5 tratamentos distintos. Mesmo input+seed → mesmo output.
