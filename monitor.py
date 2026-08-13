# Restaurant Monitor Robot | v0.3 | 13/08/2026 | filtros apertados: bloqueio de cidades/titulos/manchetes + gatilho de abertura obrigatorio
"""
Robo de descoberta de restaurantes recem-inaugurados em NW Arkansas
(Bentonville, Rogers, Fayetteville).

FILOSOFIA
    Diferente do robo de precos (que le um numero de uma URL fixa), este robo
    DESCOBRE: le algumas paginas-fonte que anunciam aberturas na regiao e
    reporta apenas as mencoes que ainda nao viu (diff contra ja_vistos.json),
    agrupadas por cidade e com links (site / Yelp / Google).

    Como as fontes cobrem justamente aberturas recentes, "novo desde a ultima
    rodada" ja aproxima o criterio de "aberto nos ultimos meses". Entradas com
    mais de ~6 meses sao purgadas para que um lugar possa reaparecer.

LIMITACAO HONESTA (v0.1)
    A extracao de nomes de HTML e heuristica -> vai gerar alguns falsos
    positivos que voce filtra. Os padroes das fontes mudam com o tempo; quando
    uma fonte parar de trazer resultados, o alerta de saude avisa (ver §saude).

TESTE LOCAL
    As fontes em fontes.csv podem ser URLs (producao) ou caminhos de arquivos
    .html locais (teste). Rodar:  python monitor.py
"""

import csv
import json
import os
import re
import sys
import time
import datetime
import smtplib
from email.mime.text import MIMEText
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

# ----------------------------- Configuracao ---------------------------------
CIDADES = ["Bentonville", "Rogers", "Fayetteville"]
JANELA_PURGA_DIAS = 180          # remove do ja_vistos apos ~6 meses
LIMITE_SAUDE = 4                 # fonte sem resultados por N rodadas -> alerta
FONTES_CSV = "fontes.csv"
VISTOS_JSON = "ja_vistos.json"
SAUDE_JSON = "saude_fontes.json"
DIGESTS_DIR = "digests"
USER_AGENT = "RestaurantMonitorBot/0.3 (uso pessoal)"
TIMEOUT = 20

# Textos de ancora que NAO sao nome de restaurante (navegacao / boilerplate).
STOPLIST = {
    "read more", "home", "contact", "contact us", "menu", "click here",
    "privacy", "privacy policy", "subscribe", "newsletter", "facebook",
    "instagram", "twitter", "x", "more", "see more", "learn more", "about",
    "about us", "next", "previous", "back", "top", "search", "login", "sign up",
    "terms", "sitemap", "advertise", "share", "email", "print", "here",
    "read also", "click", "visit website", "website", "map", "directions",
}

# Gatilhos FORTES de abertura recente. Agora sao OBRIGATORIOS para qualquer
# candidato (ancora ou texto). Termos fracos ("located", "is open", "new" solto)
# foram removidos porque deixavam passar titulo de lista e manchete.
GATILHOS = (r"(?:now open|newly opened|recently opened|opened its doors|opened|"
            r"opens|will open|set to open|opening soon|grand opening|coming soon|"
            r"new location|debut|debuts|debuted)")

# Nomes de lugares (cidades/regiao) que NUNCA sao restaurante — o extrator vinha
# pegando os proprios nomes das cidades como se fossem nome de estabelecimento.
LUGARES_BLOQUEADOS = {
    "bentonville", "rogers", "fayetteville", "springdale", "centerton",
    "bella vista", "lowell", "cave springs", "siloam springs", "eureka springs",
    "northwest arkansas", "nwa", "arkansas", "downtown bentonville",
    "downtown rogers", "downtown fayetteville",
}

# Se o nome contem um destes trechos, e titulo de lista / secao / manchete —
# nao e nome de restaurante.
TERMOS_BLOQUEADOS = [
    "top ", "best ", "restaurant", "event", "hotel", "airbnb", "things to do",
    "read more", "guide", "near me", "police", "council", "running for",
    "explains", "weekend", "list", "review", "what to", "where to", "how to",
    "meet ", "coupon", "map",
]

# Primeira palavra que denuncia frase (nao nome). Ex.: "A new bar called...".
LEAD_STOP = {
    "a", "an", "this", "that", "new", "read", "here", "here's", "these",
    "those", "more", "see", "why", "how", "what", "who", "when", "if", "our",
    "your", "meet", "discover", "explore",
}


def eh_ruido(nome):
    """True se o nome for cidade, titulo de lista, manchete ou frase — nao restaurante."""
    n = normalizar(nome)
    if n in LUGARES_BLOQUEADOS:
        return True
    if "|" in nome:                       # ex.: "Hotels | Airbnb"
        return True
    palavras = n.split()
    if palavras and palavras[0] in LEAD_STOP:
        return True
    for termo in TERMOS_BLOQUEADOS:
        if termo in n:
            return True
    # "arkansas" so bloqueia quando NAO abre o nome (titulo "...in Bentonville Arkansas");
    # permite nomes proprios que comecam com Arkansas (ex.: "Arkansas Trails Brewing Co.").
    if "arkansas" in n and not n.startswith("arkansas"):
        return True
    if n.endswith(" ar"):                 # "...in Rogers AR"
        return True
    return False


# ------------------------------ Utilidades ----------------------------------
def hoje_iso():
    return datetime.date.today().isoformat()


def normalizar(nome):
    """Chave de comparacao: minusculo, sem pontuacao nas bordas, espacos unicos."""
    n = re.sub(r"\s+", " ", nome).strip()
    n = n.strip(" .,-–—:;\u2022")
    return n.lower()


def parece_nome(texto):
    """Heuristica leve para descartar frases inteiras e ruido obvio."""
    t = texto.strip()
    if not (3 <= len(t) <= 60):
        return False
    if t.lower() in STOPLIST:
        return False
    if len(t.split()) > 6:          # frase, nao nome
        return False
    if not re.search(r"[A-Za-z]", t):
        return False
    if t.islower():                 # nomes proprios costumam ter maiuscula
        return False
    return True


def cidade_no_texto(texto):
    for c in CIDADES:
        if re.search(r"\b" + re.escape(c) + r"\b", texto, re.IGNORECASE):
            return c
    return None


# --------------------------- Coleta das fontes ------------------------------
def carregar_fontes(caminho):
    fontes = []
    with open(caminho, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("ativo", "sim").strip().lower() in ("sim", "s", "1", "true"):
                fontes.append({"nome": row["nome"].strip(), "url": row["url"].strip()})
    return fontes


def buscar(url):
    """URL http -> requests (1 retry). Caminho local -> le arquivo (modo teste)."""
    if not url.lower().startswith("http"):
        with open(url, encoding="utf-8") as f:
            return f.read()
    ultimo_erro = None
    for tentativa in range(2):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            if r.status_code in (403, 429):
                raise RuntimeError(f"bloqueio HTTP {r.status_code}")
            r.raise_for_status()
            return r.text
        except Exception as e:      # noqa: BLE001
            ultimo_erro = e
            time.sleep(3)
    raise RuntimeError(f"falha ao buscar {url}: {ultimo_erro}")


# --------------------------- Extracao de candidatos -------------------------
def eh_link_externo(href, base_url):
    try:
        dom_base = urlparse(base_url).netloc.replace("www.", "")
        dom_href = urlparse(href).netloc.replace("www.", "")
        return bool(dom_href) and dom_href != dom_base
    except Exception:               # noqa: BLE001
        return False


def extrair_candidatos(html, fonte):
    """
    Duas estrategias combinadas (v0.1):
      1) Ancoras cujo texto parece nome de restaurante, com uma das 3 cidades no
         contexto proximo (o paragrafo em volta). href externo vira 'site'.
      2) Regex "<Nome> ... in <Cidade>" perto de um gatilho de abertura.
    Retorna lista de dicts: nome, cidade, site, fonte, url_fonte.
    """
    soup = BeautifulSoup(html, "html.parser")
    base_url = fonte["url"]
    candidatos = {}

    # (1) por ancoras — agora exige gatilho de abertura no contexto e descarta ruido
    for a in soup.find_all("a"):
        nome = a.get_text(strip=True)
        if not parece_nome(nome) or eh_ruido(nome):
            continue
        contexto = a.find_parent(["p", "li", "div", "section"])
        contexto_txt = contexto.get_text(" ", strip=True) if contexto else nome
        cidade = cidade_no_texto(contexto_txt)
        if not cidade:
            continue
        if not re.search(GATILHOS, contexto_txt, re.IGNORECASE):
            continue
        href = a.get("href", "")
        site = href if eh_link_externo(href, base_url) else ""
        chave = normalizar(nome)
        candidatos.setdefault(chave, {
            "nome": nome, "cidade": cidade, "site": site,
            "fonte": fonte["nome"], "url_fonte": base_url,
        })

    # (2) por texto: bloco a bloco (paragrafo/item), pega o nome no inicio da frase.
    #     So considera blocos que citam uma cidade-alvo E um gatilho de abertura.
    nome_inicial = re.compile(
        r"^([A-Z][A-Za-z0-9'&.\-\u2019 ]{2,50}?)"
        r"(?=,|\s+(?:[\u2014\u2013-]|will|is|are|was|were|has|have|had|located|"
        r"opened|opens|open|opening|now|recently|newly|debut|debuts|debuted|"
        r"set to|coming|brings|serves|to open))"
    )
    for bloco in soup.find_all(["p", "li"]):
        txt = bloco.get_text(" ", strip=True)
        cidade = cidade_no_texto(txt)
        if not cidade:
            continue
        if not re.search(GATILHOS, txt, re.IGNORECASE):
            continue
        m = nome_inicial.match(txt)
        if not m:
            continue
        nome = m.group(1).strip()
        if not parece_nome(nome) or eh_ruido(nome):
            continue
        chave = normalizar(nome)
        candidatos.setdefault(chave, {
            "nome": nome, "cidade": cidade, "site": "",
            "fonte": fonte["nome"], "url_fonte": base_url,
        })

    return list(candidatos.values())


# ------------------------------- Links --------------------------------------
def montar_links(nome, cidade):
    q_yelp = quote_plus(nome)
    loc_yelp = quote_plus(f"{cidade}, AR")
    yelp = f"https://www.yelp.com/search?find_desc={q_yelp}&find_loc={loc_yelp}"
    google = "https://www.google.com/maps/search/" + quote_plus(f"{nome} {cidade} AR")
    return yelp, google


# --------------------------- Estado (vistos/saude) --------------------------
def carregar_json(caminho, padrao):
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    return padrao


def salvar_json(caminho, dados):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def purgar_antigos(vistos):
    limite = datetime.date.today() - datetime.timedelta(days=JANELA_PURGA_DIAS)
    mantidos = []
    for v in vistos:
        try:
            visto_em = datetime.date.fromisoformat(v["primeiro_visto"])
        except Exception:           # noqa: BLE001
            visto_em = datetime.date.today()
        if visto_em >= limite:
            mantidos.append(v)
    return mantidos


# ------------------------------- Digest -------------------------------------
def montar_digest(novos, avisos_saude):
    data = hoje_iso()
    linhas = [f"# Novos restaurantes — {data}", ""]
    if not novos:
        linhas.append("_Nenhum restaurante novo detectado nesta rodada._")
    else:
        linhas.append(f"**{len(novos)} candidato(s) novo(s)** desde a ultima rodada.  ")
        linhas.append("_Sao candidatos das fontes — vale conferir os links antes de confiar._")
        linhas.append("")
        for cidade in CIDADES:
            do_grupo = [n for n in novos if n["cidade"] == cidade]
            if not do_grupo:
                continue
            linhas.append(f"## {cidade}")
            for n in do_grupo:
                yelp, google = montar_links(n["nome"], n["cidade"])
                site = f"[Site]({n['site']}) · " if n.get("site") else ""
                linhas.append(
                    f"- **{n['nome']}** — {site}[Yelp]({yelp}) · [Google]({google})  "
                )
                linhas.append(f"  <sub>fonte: {n['fonte']}</sub>")
            linhas.append("")
    if avisos_saude:
        linhas.append("## ⚠️ Saude das fontes")
        for a in avisos_saude:
            linhas.append(f"- {a}")
        linhas.append("")
    return "\n".join(linhas)


# ------------------------------ Entrega -------------------------------------
def enviar_email(assunto, corpo):
    origem = os.environ.get("EMAIL_ORIGEM")
    senha = os.environ.get("EMAIL_SENHA_APP")
    destino = os.environ.get("EMAIL_DESTINO")
    if not (origem and senha and destino):
        print("[email] segredos ausentes — pulando envio de e-mail.")
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


def montar_whatsapp(novos, avisos_saude):
    """Mensagem de WhatsApp com os nomes dos novos + link do Google de cada um
    (tap para conferir). Cap de itens para nao estourar o tamanho da mensagem."""
    if not novos and not avisos_saude:
        return ""
    MAX_ITENS = 15
    linhas = [f"🍽️ Novos restaurantes NWA — {hoje_iso()} ({len(novos)})"]
    mostrados = 0
    for cidade in CIDADES:
        do_grupo = [n for n in novos if n["cidade"] == cidade]
        if not do_grupo:
            continue
        linhas.append(f"\n*{cidade}*")
        for n in do_grupo:
            if mostrados >= MAX_ITENS:
                break
            _, google = montar_links(n["nome"], n["cidade"])
            linhas.append(f"• {n['nome']}: {google}")
            mostrados += 1
    restantes = len(novos) - mostrados
    if restantes > 0:
        linhas.append(f"\n…e mais {restantes} (ver e-mail/digest).")
    if avisos_saude:
        linhas.append(f"\n⚠️ {len(avisos_saude)} aviso(s) de fonte — checar layout.")
    return "\n".join(linhas)


def enviar_whatsapp(texto_curto):
    phone = os.environ.get("CALLMEBOT_PHONE")
    apikey = os.environ.get("CALLMEBOT_APIKEY")
    if not (phone and apikey):
        print("[whatsapp] segredos ausentes — pulando envio de WhatsApp.")
        return
    url = ("https://api.callmebot.com/whatsapp.php?"
           f"phone={quote_plus(phone)}&text={quote_plus(texto_curto)}&apikey={quote_plus(apikey)}")
    try:
        requests.get(url, timeout=TIMEOUT)
        print("[whatsapp] enviado.")
    except Exception as e:          # noqa: BLE001
        print(f"[whatsapp] falha: {e}")


# ------------------------------- Principal ----------------------------------
def main():
    fontes = carregar_fontes(FONTES_CSV)
    vistos = carregar_json(VISTOS_JSON, [])
    saude = carregar_json(SAUDE_JSON, {})
    chaves_vistas = {(v["chave"], v["cidade"]) for v in vistos}

    novos = []
    avisos_saude = []

    for fonte in fontes:
        try:
            html = buscar(fonte["url"])
            candidatos = extrair_candidatos(html, fonte)
        except Exception as e:      # noqa: BLE001
            print(f"[fonte] ERRO em {fonte['nome']}: {e}")
            candidatos = []

        # saude: conta rodadas consecutivas sem candidatos (§scraping falha calado)
        if candidatos:
            saude[fonte["nome"]] = 0
        else:
            saude[fonte["nome"]] = saude.get(fonte["nome"], 0) + 1
            if saude[fonte["nome"]] >= LIMITE_SAUDE:
                avisos_saude.append(
                    f"{fonte['nome']} sem resultados ha {saude[fonte['nome']]} rodadas "
                    f"— possivel mudanca no site."
                )

        for c in candidatos:
            chave = normalizar(c["nome"])
            if (chave, c["cidade"]) in chaves_vistas:
                continue
            chaves_vistas.add((chave, c["cidade"]))
            registro = {
                "chave": chave, "nome": c["nome"], "cidade": c["cidade"],
                "site": c.get("site", ""), "fonte": c["fonte"],
                "url_fonte": c["url_fonte"], "primeiro_visto": hoje_iso(),
            }
            vistos.append(registro)
            novos.append(registro)

    vistos = purgar_antigos(vistos)
    salvar_json(VISTOS_JSON, vistos)
    salvar_json(SAUDE_JSON, saude)

    digest = montar_digest(novos, avisos_saude)
    os.makedirs(DIGESTS_DIR, exist_ok=True)
    caminho_digest = os.path.join(DIGESTS_DIR, f"{hoje_iso()}.md")
    with open(caminho_digest, "w", encoding="utf-8") as f:
        f.write(digest)
    print(f"[digest] {caminho_digest} ({len(novos)} novos)")

    # entrega apenas quando ha novidade ou aviso de saude
    if novos or avisos_saude:
        enviar_email(f"Restaurantes novos NWA — {hoje_iso()} ({len(novos)})", digest)
        enviar_whatsapp(montar_whatsapp(novos, avisos_saude))

    return 0


if __name__ == "__main__":
    sys.exit(main())
