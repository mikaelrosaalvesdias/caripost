# Vídeo — contratos de API verificados em 2026-06-29

Este arquivo existe para evitar correções de arte ou tentativas pagas no escuro.
O fluxo abaixo foi conferido em documentação oficial pública, sem gerar vídeo.

## OpenRouter

Fonte: `https://openrouter.ai/docs/guides/overview/multimodal/video-generation.md`.

Fluxo:

- Criar: `POST https://openrouter.ai/api/v1/videos` com JSON.
- Pollar: `GET https://openrouter.ai/api/v1/videos/{job_id}`.
- Baixar: `unsigned_urls[0]` ou `GET /api/v1/videos/{job_id}/content?index=0`.

Payload correto para image-to-video:

```json
{
  "model": "google/veo-3.1",
  "prompt": "...",
  "duration": 8,
  "resolution": "720p",
  "aspect_ratio": "9:16",
  "generate_audio": true,
  "frame_images": [
    {
      "type": "image_url",
      "image_url": { "url": "https://example.com/first-frame.png" },
      "frame_type": "first_frame"
    }
  ]
}
```

Erro que foi corrigido: mandar `frame_images` sem `type: "image_url"` causa `ZodError`
em `frame_images[0].type`. Mandar `seconds` no lugar de `duration` também não segue
o contrato atual.

## CometAPI

Fontes:

- `https://apidoc.cometapi.com/api/video/veo3/create.md`
- `https://apidoc.cometapi.com/api/video/sora-2/create.md`
- `https://apidoc.cometapi.com/api/video/seedance/create.md`
- `https://apidoc.cometapi.com/api/video/wan/create.md`
- `https://apidoc.cometapi.com/api/video/vidu/create.md`
- `https://apidoc.cometapi.com/api/video/omni/create.md`

Fluxo para os modelos listados no seletor genérico:

- Criar: `POST https://api.cometapi.com/v1/videos` com `multipart/form-data`.
- Pollar: `GET https://api.cometapi.com/v1/videos/{task_id}`.
- Baixar: `video_url` quando vier no polling ou `GET /v1/videos/{task_id}/content`.

Campos básicos:

```text
model=<modelo documentado>
prompt=<prompt visual>
seconds=<segundos>
aspect_ratio=9:16
resolution=720p
```

Modelos Comet com rotas próprias, como Kling, Runway e xAI/Grok, não devem aparecer
no seletor genérico enquanto não houver adaptador específico. Misturar esses modelos
com `/v1/videos` cria falha de provedor e risco de cobrança sem entrega.

## Validação sem custo

Use:

```bash
python scripts/test_video_providers_no_api.py
```

O teste substitui o cliente HTTP por fake local. Ele valida payload e parsing sem usar
tokens e sem chamar OpenRouter ou CometAPI.
