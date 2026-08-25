# Restaurant Monitor Robot | v0.7 | 25/08/2026 | WhatsApp: link ainda mais curto (sem https://) para economizar espaco
"""
Robo de descoberta de restaurantes em NW Arkansas (Bentonville, Rogers,
Fayetteville) usando a GOOGLE PLACES API (New).
 
COMO FUNCIONA
    A cada rodada, consulta a Places API por "restaurants in <cidade>, Arkansas"
    (ate 3 paginas por cidade), junta os resultados e compara com ja_vistos.json
    pela ID unica do Google (place_id). So reporta o que ainda nao tinha visto.
 
PRIMEIRA RODADA (seed silencioso)
    Se ja_vistos.json estiver vazio, a estreia cadastra TODOS os restaurantes
    atuais sem alertar (senao seriam centenas de uma vez). A partir da 2a rodada,
    so os genuinamente novos sao reportados.
 
LIMITACAO HONESTA
    A Places API nao tem "data de abertura". Entao "novo" aqui = "novo para o
    robo" (apareceu na busca depois da estreia), o que se aproxima de recem-aberto
    mas nao garante. A cobertura tambem nao e exaustiva: pega os mais relevantes
    por cidade, nao 100% dos restaurantes.
 
SEGREDOS
    A chave vem do ambiente (GOOGLE_API_KEY), nunca do codigo. Nos GitHub Secrets.
"""
 
import json
import os
import re
import sys
import time
import datetime
import smtplib
from email.mime.text import MIMEText
from urllib.parse import quote_plus
 
import requests
 
# ----------------------------- Configuracao ---------------------------------
CIDADES = ["Bentonville", "Rogers", "Fayetteville"]
ESTADO_UF = "Arkansas"
VISTOS_JSON = "ja_vistos.json"
DIGESTS_DIR = "digests"
MAX_PAGINAS = 3                  # ate 3 paginas (~60 lugares) por cidade
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.websiteUri,"
    "places.googleMapsUri,places.rating,places.userRatingCount,"
    "places.primaryTypeDisplayName,nextPageToken"
)
TIMEOUT = 30
 
 
def hoje_iso():
    return datetime.date.today().isoformat()
 
 
# --------------------------- Consulta a Places API --------------------------
def buscar_cidade(cidade, api_key):
    """Retorna lista de restaurantes da cidade via Places API (paginado)."""
    resultados = []
    page_token = None
    for _ in range(MAX_PAGINAS):
        body = {"textQuery": f"restaurants in {cidade}, {ESTADO_UF}"}
        if page_token:
            body["pageToken"] = page_token
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        }
        r = requests.post(PLACES_URL, headers=headers, json=body, timeout=TIMEOUT)
        if r.status_code != 200:
            # nao imprime a chave; so status e corpo (que nao contem a chave)
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        for p in data.get("places", []):
            resultados.append({
                "place_id": p.get("id"),
                "nome": (p.get("displayName") or {}).get("text", ""),
                "cidade": cidade,
                "endereco": p.get("formattedAddress", ""),
                "site": p.get("websiteUri", ""),
                "google": p.get("googleMapsUri", ""),
                "nota": p.get("rating"),
                "avaliacoes": p.get("userRatingCount"),
                "tipo": (p.get("primaryTypeDisplayName") or {}).get("text", ""),
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(2)  # Google exige uma pequena espera antes do pageToken valer
    return resultados
 
 
# ------------------------------- Links --------------------------------------
def link_yelp(nome, cidade):
    return (f"https://www.yelp.com/search?find_desc={quote_plus(nome)}"
            f"&find_loc={quote_plus(cidade + ', AR')}")
 
 
def encurtar_google(url):
    """Reduz o googleMapsUri ao minimo. O parametro g_mp gigante e removido (o
    cid sozinho abre o local) e o https:// e cortado — o WhatsApp reconhece
    'maps.google.com/...' como link clicavel mesmo sem o esquema. Cai de ~140
    para ~30 caracteres."""
    if not url:
        return ""
    m = re.search(r"cid=(\d+)", url)
    if m:
        return f"maps.google.com/?cid={m.group(1)}"
    return url.split("&")[0].replace("https://", "").replace("http://", "")
 
 
# --------------------------- Estado (vistos) --------------------------------
def carregar(caminho, padrao):
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    return padrao
 
 
def salvar(caminho, dados):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
 
 
# ------------------------------- Digest -------------------------------------
def linha_nota(p):
    if p.get("nota"):
        n = f"nota {p['nota']}"
        if p.get("avaliacoes"):
            n += f", {p['avaliacoes']} avaliações"
        return f" ({n})"
    return ""
 
 
def montar_digest(novos):
    linhas = [f"# Novos restaurantes — {hoje_iso()}", ""]
    if not novos:
        linhas.append("_Nenhum restaurante novo nesta rodada._")
        return "\n".join(linhas)
    linhas.append(f"**{len(novos)} novo(s)** desde a última rodada.")
    linhas.append("")
    for cidade in CIDADES:
        grupo = [p for p in novos if p["cidade"] == cidade]
        if not grupo:
            continue
        linhas.append(f"## {cidade}")
        for p in grupo:
            site = f"[Site]({p['site']}) · " if p.get("site") else ""
            google = f"[Google]({p['google']})" if p.get("google") else ""
            yelp = f"[Yelp]({link_yelp(p['nome'], cidade)})"
            linhas.append(f"- **{p['nome']}**{linha_nota(p)} — {site}{yelp} · {google}")
        linhas.append("")
    return "\n".join(linhas)
 
 
def montar_whatsapp(novos):
    """Mensagem curta e à prova do limite do CallMeBot: nome + nota + link curto
    do Google. Para ao aproximar do teto de caracteres e indica o restante."""
    if not novos:
        return ""
    MAX_CHARS = 700                 # teto seguro contra truncamento do CallMeBot
    cabecalho = f"🍽️ Novos restaurantes NWA — {hoje_iso()} ({len(novos)})"
    partes = [cabecalho]
    tamanho = len(cabecalho)
    mostrados = 0
    cidade_atual = None
    for cidade in CIDADES:
        grupo = [p for p in novos if p["cidade"] == cidade]
        for p in grupo:
            nota = f" (nota {p['nota']})" if p.get("nota") else ""
            alvo = (encurtar_google(p.get("google")) or p.get("site")
                    or link_yelp(p["nome"], cidade))
            bloco = ""
            if cidade != cidade_atual:
                bloco += f"\n\n*{cidade}*"
            bloco += f"\n• {p['nome']}{nota}: {alvo}"
            if tamanho + len(bloco) > MAX_CHARS and mostrados > 0:
                partes.append(f"\n\n…e mais {len(novos) - mostrados} (ver digest).")
                return "".join(partes)
            partes.append(bloco)
            tamanho += len(bloco)
            cidade_atual = cidade
            mostrados += 1
    return "".join(partes)
 
 
# ------------------------------ Entrega -------------------------------------
def enviar_email(assunto, corpo):
    origem = os.environ.get("EMAIL_ORIGEM")
    senha = os.environ.get("EMAIL_SENHA_APP")
    destino = os.environ.get("EMAIL_DESTINO")
    if not (origem and senha and destino):
        print("[email] segredos ausentes — pulando e-mail.")
        return
    msg = MIMEText(corpo, "plain", "utf-8")
    msg["Subject"] = assunto
    msg["From"] = origem
    msg["To"] = destino
    with smtplib.SMTP("smtp.mail.me.com", 587, timeout=TIMEOUT) as s:
        s.starttls()
        s.login(origem, senha)
        s.sendmail(origem, [destino], msg.as_string())
    print("[email] enviado.")
 
 
def enviar_whatsapp(texto):
    phone = os.environ.get("CALLMEBOT_PHONE")
    apikey = os.environ.get("CALLMEBOT_APIKEY")
    if not (phone and apikey):
        print("[whatsapp] segredos ausentes — pulando WhatsApp.")
        return
    url = ("https://api.callmebot.com/whatsapp.php?"
           f"phone={quote_plus(phone)}&text={quote_plus(texto)}&apikey={quote_plus(apikey)}")
    try:
        requests.get(url, timeout=TIMEOUT)
        print("[whatsapp] enviado.")
    except Exception as e:  # noqa: BLE001
        print(f"[whatsapp] falha: {e}")
 
 
# ------------------------------- Principal ----------------------------------
def main():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("[erro] GOOGLE_API_KEY ausente nos Secrets. Abortando.")
        return 1
 
    vistos = carregar(VISTOS_JSON, [])
    ids_vistos = {v["place_id"] for v in vistos}
    seed = len(vistos) == 0        # ja_vistos vazio = primeira rodada
 
    todos = {}
    for cidade in CIDADES:
        try:
            for p in buscar_cidade(cidade, api_key):
                if p["place_id"]:
                    todos[p["place_id"]] = p
        except Exception as e:      # noqa: BLE001
            print(f"[cidade] ERRO em {cidade}: {e}")
 
    novos = [p for pid, p in todos.items() if pid not in ids_vistos]
 
    # registra tudo o que viu (novos entram no estado permanente)
    for pid, p in todos.items():
        if pid not in ids_vistos:
            vistos.append({"place_id": pid, "nome": p["nome"],
                           "cidade": p["cidade"], "primeiro_visto": hoje_iso()})
            ids_vistos.add(pid)
    salvar(VISTOS_JSON, vistos)
    os.makedirs(DIGESTS_DIR, exist_ok=True)
    caminho = os.path.join(DIGESTS_DIR, f"{hoje_iso()}.md")
 
    if seed:
        # primeira rodada: cadastra em silencio, sem enxurrada de alertas
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(f"# Primeira rodada (seed) — {hoje_iso()}\n\n"
                    f"{len(todos)} restaurantes cadastrados em modo silencioso.\n"
                    f"A partir da próxima rodada, só os novos serão reportados.\n")
        print(f"[seed] {len(todos)} cadastrados sem alerta.")
        enviar_whatsapp(f"🍽️ Robô de restaurantes iniciado: {len(todos)} lugares "
                        f"cadastrados. A partir de amanhã aviso só as novidades.")
        return 0
 
    digest = montar_digest(novos)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(digest)
    print(f"[digest] {caminho} ({len(novos)} novos)")
 
    if novos:
        enviar_email(f"Restaurantes novos NWA — {hoje_iso()} ({len(novos)})", digest)
        enviar_whatsapp(montar_whatsapp(novos))
    return 0
 
 
if __name__ == "__main__":
    sys.exit(main())
 
