# Restaurant Monitor Robot | v0.10 | 28-ago-26 | so alerta nota >=4 (ou sem nota) e menos de 15 avaliacoes
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
# Cidades cobertas e quantas paginas buscar em cada uma. Cidade maior = mais
# paginas (mais restaurantes); cidade pequena = 1 pagina basta. Assim a cobertura
# cresce para toda a regiao NWA sem estourar a cota gratuita da Places API.
CIDADES_PAGINAS = [
    ("Fayetteville", 3), ("Springdale", 3), ("Rogers", 3), ("Bentonville", 3),
    ("Bella Vista", 2), ("Centerton", 2), ("Siloam Springs", 2), ("Lowell", 2),
    ("Cave Springs", 1), ("Johnson", 1), ("Pea Ridge", 1), ("Farmington", 1),
    ("Prairie Grove", 1), ("Eureka Springs", 1),
]
CIDADES = [c for c, _ in CIDADES_PAGINAS]   # ordem usada para agrupar no digest/WhatsApp
ESTADO_UF = "Arkansas"
VISTOS_JSON = "ja_vistos.json"
DIGESTS_DIR = "digests"
# So alerta lugares "recem-abertos e bem avaliados":
#  - menos de 15 avaliacoes (aprox. recem-aberto), OU sem avaliacoes ainda; E
#  - nota >= 4 estrelas, OU ainda sem nota (novo demais para ter media).
# Lugares fora desses criterios sao registrados, mas nao alertados.
MAX_AVALIACOES = 15              # alerta so quem tem MENOS de 15 avaliacoes
MIN_NOTA = 4.0                   # e nota >= 4 (sem nota tambem passa)
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
def buscar_cidade(cidade, api_key, paginas):
    """Retorna lista de restaurantes da cidade via Places API (paginado)."""
    resultados = []
    page_token = None
    for _ in range(paginas):
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
 
 
def poucas_avaliacoes(p):
    """True se o lugar tem menos de MAX_AVALIACOES avaliacoes (ou nenhuma)."""
    n = p.get("avaliacoes")
    return n is None or n < MAX_AVALIACOES
 
 
def nota_ok(p):
    """True se a nota e >= MIN_NOTA, ou se ainda nao tem nota (novo demais)."""
    nota = p.get("nota")
    return nota is None or nota >= MIN_NOTA
 
 
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
