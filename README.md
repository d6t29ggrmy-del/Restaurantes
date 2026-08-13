# Restaurant Monitor Robot — NW Arkansas

Robô que descobre **restaurantes recém-inaugurados** em **Bentonville, Rogers e
Fayetteville (AR)**. Uma vez por dia ele lê as fontes configuradas, detecta o que
é novo desde a última rodada e envia um resumo agrupado por cidade, com links de
**site / Yelp / Google** para você conferir.

Roda no **GitHub Actions** (Python + `requests` + `BeautifulSoup`), no mesmo
espírito do robô de preços: sem segredos no código, estado salvo no próprio repo.

---

## Como funciona (resumo)

1. Lê os endereços em `fontes.csv`.
2. Extrai candidatos a restaurante (por links e por frases do tipo
   "*X ... in Rogers, recently opened*").
3. Compara com `ja_vistos.json` — só reporta o que ainda não foi visto.
4. Escreve o resumo do dia em `digests/AAAA-MM-DD.md` e envia por e-mail/WhatsApp
   (se os segredos estiverem configurados).
5. Entradas com mais de ~6 meses saem do `ja_vistos.json`, para um lugar poder
   reaparecer se voltar ao noticiário.

> **v0.1 — honestidade:** a extração é heurística. Espere alguns falsos
> positivos (por isso o resumo diz "candidatos" — confira os links). Quando uma
> fonte muda de layout e para de retornar resultados por 4 rodadas seguidas, o
> resumo inclui um **aviso de saúde**.

---

## Passo a passo de instalação

1. **Criar o repositório** novo no GitHub (pode ser **público** — aí o Actions é
   ilimitado; os segredos ficam nos Secrets, nunca no código).
2. **Subir estes arquivos** para o repositório.
3. **Configurar o WhatsApp (CallMeBot) — canal principal.** No próprio CallMeBot,
   autorize o número e pegue sua `apikey` (mesmo processo do robô de preços).
   Depois cadastre em *Settings → Secrets and variables → Actions*:
   - `CALLMEBOT_PHONE` — seu número no formato do CallMeBot
   - `CALLMEBOT_APIKEY` — sua chave do CallMeBot

   A mensagem de WhatsApp chega assim (nomes por cidade + link do Google em cada,
   é só tocar para conferir):

   ```
   🍽️ Novos restaurantes NWA — 2026-08-13 (7)

   *Bentonville*
   • Wright's Barbecue: https://www.google.com/maps/search/...
   • Caffeine Bar: https://www.google.com/maps/search/...

   *Rogers*
   • Chuo Izakaya: https://www.google.com/maps/search/...
   ```

4. **E-mail (opcional).** Se quiser também receber o resumo completo por e-mail,
   cadastre os Secrets `EMAIL_ORIGEM` (iCloud remetente), `EMAIL_SENHA_APP`
   (senha de app do iCloud) e `EMAIL_DESTINO`. Sem esses, o robô manda só o
   WhatsApp — sem erro.
5. **Ajustar o horário** (opcional) no `cron` de `.github/workflows/daily.yml`.
   Lembre: é em UTC.
6. **Primeira rodada manual:** aba *Actions → restaurantes-diario → Run
   workflow*. Como o `ja_vistos.json` começa vazio, a primeira rodada traz tudo
   o que as fontes tiverem hoje — depois disso, só o que for novo.

---

## Ajustar o que é monitorado

- **Fontes:** edite `fontes.csv` (`ativo` = `sim`/`nao`). Cidades: `CIDADES` no
  topo de `monitor.py`.
- **Teste local sem tocar na internet:** o `fontes.csv` aceita caminhos de
  arquivos `.html` locais (em vez de URLs). Basta apontar uma linha para um
  arquivo salvo e rodar `python monitor.py` para validar a lógica offline.

## O que NÃO fazer

- Não raspar Yelp nem Google Maps direto (anti-bot / JavaScript) — eles entram
  só como **links de busca**.
- Não colocar segredos no código — sempre nos **GitHub Secrets**.
- Não tratar "fonte sem resultado" como "não abriu nada" — é o aviso de saúde.
