# Restaurant Monitor Robot — NW Arkansas (Google Places API)

Robô que descobre restaurantes em **Bentonville, Rogers e Fayetteville (AR)** via
**Google Places API (New)**. Uma vez por dia consulta a API, compara com o que já
viu (`ja_vistos.json`, pela ID única do Google) e avisa no **WhatsApp** os que
forem novos — cada um com nota, avaliações e links de site/Yelp/Google.

Roda no **GitHub Actions** (Python). Sem segredos no código.

---

## Como funciona

1. Para cada cidade, consulta "restaurants in <cidade>, Arkansas" (até 3 páginas).
2. Junta os resultados e compara com `ja_vistos.json` pela `place_id` do Google.
3. Reporta só os novos; salva o resumo em `digests/AAAA-MM-DD.md`.
4. **Primeira rodada (seed):** se `ja_vistos.json` estiver vazio, a estreia
   cadastra todos em silêncio (senão seriam centenas). Da 2a rodada em diante,
   só os genuinamente novos são avisados.

> **Honestidade:** a Places API não tem "data de abertura". "Novo" aqui = "novo
> para o robô" (apareceu depois da estreia) — aproxima recém-aberto, mas não
> garante. A cobertura pega os mais relevantes por cidade, não 100%.

---

## Instalação

1. **Chave da Places API** — no Google Cloud, uma chave com a **Places API (New)**
   habilitada, sem restrição de aplicativo (para rodar no GitHub). Guarde o valor
   com segurança (nunca no código nem em chat).
2. **Secrets** em Settings -> Secrets and variables -> Actions -> New repository secret:
   - GOOGLE_API_KEY — a chave da Places API (obrigatorio)
   - CALLMEBOT_PHONE e CALLMEBOT_APIKEY — WhatsApp (canal principal)
   - EMAIL_ORIGEM, EMAIL_SENHA_APP, EMAIL_DESTINO — e-mail (opcional)
3. **Permissao de escrita:** Settings -> Actions -> General -> Workflow permissions
   -> Read and write permissions -> Save.
4. **Horario** (opcional): cron em .github/workflows/daily.yml (em UTC).
5. **Primeira rodada:** Actions -> restaurantes-diario -> Run workflow. A estreia
   e o seed silencioso (chega so uma mensagem curta de confirmacao no WhatsApp).

## Ajustes

- **Cidades:** CIDADES no topo de monitor.py.
- **Profundidade:** MAX_PAGINAS (1 pagina ~ 20 lugares; max. 3).

## Custo

Poucas consultas por dia (3 cidades x ate 3 paginas). Volume minimo — cabe
folgado no credito mensal gratuito do Google Maps Platform.
