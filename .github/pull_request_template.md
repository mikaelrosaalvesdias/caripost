## Resumo

<!-- O que muda, em uma frase. -->

## Motivo

<!-- Que dor operacional isso resolve. -->

## Como foi validado

<!-- Comandos rodados e o que você viu. Print/arte gerada quando mexe no motor criativo. -->

```
```

## Risco em produção

<!-- O que pode quebrar e como reverter. "Nenhum" também é resposta, se for verdade. -->

## Checklist

- [ ] Versões em sincronia (`app/main.py`, `MP_OS_VERSION`, `?v=` do `index.html`)
- [ ] Cache-bust do `.jsx` alterado
- [ ] `CHANGELOG.md` e changelog interno (`app/ui/app.js`) atualizados
- [ ] `python3 docs/marcos/regressao_check.py` rodado antes e depois (se mexeu no motor criativo)
- [ ] Sem secrets, mídia, banco ou dado de cliente no diff
- [ ] Deploy confirmado no ar (se já entregue)
