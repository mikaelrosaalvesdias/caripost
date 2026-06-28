# Caripost Creative Engine

Motor de composição com detecção para impedir texto em rosto, mão, corpo e objetos importantes.

## Rodar CLI

```bash
python -m creative input.png --config creative/blocks.example.json --seed 42 -o out.png --debug
```

`--debug` salva overlay com regiões protegidas em vermelho/laranja e retângulos livres em verde.

## API

```python
from creative import compose_creative

out, metadata = compose_creative(image, blocks, art_config={"treatment": "column_glass"}, seed=42)
```

Tratamentos disponíveis: `column_glass`, `column_solid`, `scrim_float`, `big_type_bleed`, `behind_subject`, `contour_silhouette`, `cut_band`.

## Teste determinístico sem modelos

```bash
python -m creative.test_positions
```

Valida sujeito à direita, esquerda, centro, canto e dois sujeitos com mocks.
