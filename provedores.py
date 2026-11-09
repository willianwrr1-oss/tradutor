"""Provedores de tradução e de reconhecimento de fala."""
import io
import re
import threading
import time
import wave
from urllib.parse import quote

import numpy as np
import requests

import configuracao as C

TIMEOUT = 15
NOME_PT = {"es": "espanhol", "en": "inglês", "ja": "japonês"}
NOME_PARA_COD = {"english": "en", "spanish": "es", "japanese": "ja", "portuguese": "pt"}


class ErroProvedor(RuntimeError):
    pass


def _checar(r):
    if r.status_code >= 400:
        try:
            detalhe = r.json()
        except Exception:
            detalhe = r.text
        raise ErroProvedor(f"HTTP {r.status_code}: {str(detalhe)[:150]}")
    return r


# ----------------------------------------------------------------------------
# Tradução: cada função recebe (provedor, texto, idioma_origem, contexto)
# ----------------------------------------------------------------------------
def _prompt_sistema(src, contexto):
    s = (f"Você é um tradutor simultâneo profissional. Traduza o texto recebido de {NOME_PT.get(src, src)} "
         "para português do Brasil, com naturalidade e fidelidade. O texto vem de uma transcrição automática "
         "de fala e pode ter pequenos erros: corrija-os sem inventar conteúdo. "
         "Responda SOMENTE com a tradução, sem aspas, notas ou explicações.")
    if contexto:
        s += f"\n\nFrase anterior (apenas contexto, não traduza): {contexto}"
    return s


def _google_gratis(p, texto, src, ctx):
    from deep_translator import GoogleTranslator

    return GoogleTranslator(source=src, target="pt").translate(texto)


def _google_cloud(p, texto, src, ctx):
    base = (p.get("url") or "https://translation.googleapis.com").rstrip("/")
    r = requests.post(f"{base}/language/translate/v2",
                      data={"q": texto, "source": src, "target": "pt", "format": "text", "key": p["chave"]},
                      timeout=TIMEOUT)
    return _checar(r).json()["data"]["translations"][0]["translatedText"]


def _deepl(p, texto, src, ctx):
    chave = p["chave"]
    base = (p.get("url") or ("https://api-free.deepl.com" if chave.endswith(":fx")
                             else "https://api.deepl.com")).rstrip("/")
    r = requests.post(f"{base}/v2/translate", headers={"Authorization": f"DeepL-Auth-Key {chave}"},
                      json={"text": [texto], "source_lang": src.upper(), "target_lang": "PT-BR"},
                      timeout=TIMEOUT)
    return _checar(r).json()["translations"][0]["text"]


def _azure(p, texto, src, ctx):
    base = (p.get("url") or "https://api.cognitive.microsofttranslator.com").rstrip("/")
    cab = {"Ocp-Apim-Subscription-Key": p["chave"], "Content-Type": "application/json"}
    if p.get("regiao"):
        cab["Ocp-Apim-Subscription-Region"] = p["regiao"]
    r = requests.post(f"{base}/translate", params={"api-version": "3.0", "from": src, "to": "pt"},
                      headers=cab, json=[{"Text": texto}], timeout=TIMEOUT)
    return _checar(r).json()[0]["translations"][0]["text"]


def _libretranslate(p, texto, src, ctx):
    corpo = {"q": texto, "source": src, "target": "pt", "format": "text"}
    if p.get("chave"):
        corpo["api_key"] = p["chave"]
    r = requests.post(p["url"].rstrip("/") + "/translate", json=corpo, timeout=TIMEOUT)
    return _checar(r).json()["translatedText"]


def _openai_llm(p, texto, src, ctx):
    r = requests.post(p["url"].rstrip("/") + "/chat/completions",
                      headers={"Authorization": f"Bearer {p['chave']}"},
                      json={"model": p["modelo"],
                            "messages": [{"role": "system", "content": _prompt_sistema(src, ctx)},
                                         {"role": "user", "content": texto}]},
                      timeout=30)
    return _checar(r).json()["choices"][0]["message"]["content"].strip()


def _anthropic(p, texto, src, ctx):
    base = (p.get("url") or "https://api.anthropic.com").rstrip("/")
    r = requests.post(base + "/v1/messages",
                      headers={"x-api-key": p["chave"], "anthropic-version": "2023-06-01"},
                      json={"model": p["modelo"], "max_tokens": 1024,
                            "system": _prompt_sistema(src, ctx),
                            "messages": [{"role": "user", "content": texto}]},
                      timeout=30)
    return _checar(r).json()["content"][0]["text"].strip()


LINGVA = ("https://lingva.ml", "https://lingva.garudalinux.org", "https://translate.plausibility.cloud")


def _lingva(p, texto, src, ctx):
    ultimo = None
    for base in LINGVA:
        try:
            r = requests.get(f"{base}/api/v1/{src}/pt/{quote(texto, safe='')}", timeout=8)
            return _checar(r).json()["translation"]
        except Exception as e:
            ultimo = e
    raise ErroProvedor(f"instâncias indisponíveis ({ultimo})")


def _mymemory(p, texto, src, ctx):
    pedacos, atual = [], ""
    for frase in re.split(r"(?<=[.!?。！？])\s*", texto):
        if len(atual) + len(frase) > 400 and atual:
            pedacos.append(atual)
            atual = ""
        atual += frase + " "
    if atual.strip():
        pedacos.append(atual)
    saida = []
    for parte in pedacos:
        r = requests.get("https://api.mymemory.translated.net/get",
                         params={"q": parte.strip()[:480], "langpair": f"{src}|pt-BR"}, timeout=TIMEOUT)
        dados = _checar(r).json()
        if int(dados.get("responseStatus", 200)) != 200:
            raise ErroProvedor(str(dados.get("responseDetails", "erro")))
        saida.append(dados["responseData"]["translatedText"])
    return " ".join(saida)


def _argos(p, texto, src, ctx):
    import argostranslate.translate as at

    return at.translate(texto, src, "pt")


TRADUTORES = {
    "google_gratis": _google_gratis, "google_cloud": _google_cloud, "deepl": _deepl, "azure": _azure,
    "libretranslate": _libretranslate, "openai_llm": _openai_llm, "anthropic": _anthropic,
    "lingva": _lingva, "mymemory": _mymemory, "argos": _argos,
}


class GerenciadorTraducao:
    """Escolhe o serviço de tradução, com reserva automática e descanso após falhas.

    O endpoint gratuito do Google bloqueia por IP em redes compartilhadas. Por isso, quando
    um serviço falha ele fica em "descanso" antes de ser tentado de novo.
    """

    DESCANSO = 60
    DESCANSO_ESCOLHIDO = 15

    def __init__(self, cfg):
        self.cache = {}
        self.descanso_ate = {}
        self.ultimo = None
        self.anterior = ""
        self.escolhido = None
        self.cadeia = []
        self.reconfigurar(cfg)

    def reconfigurar(self, cfg):
        usuario = [p for p in cfg["provedores"] if C.TIPOS[p["tipo"]]["funcao"] == "traducao"]
        if cfg.get("offline"):
            cadeia = [{"id": "argos", "nome": "Argos (offline)", "tipo": "argos"}]
            escolhido = None
        else:
            gratis = list(C.BUILTIN_TRADUCAO)
            todos = {p["id"]: p for p in usuario + gratis}
            escolha = cfg.get("traducao_ativa", "auto")
            if escolha in todos:
                escolhido = escolha
                cadeia = [todos[escolha]]
                if cfg.get("reserva_gratis", True):
                    cadeia += [p for p in gratis if p["id"] != escolha]
            else:
                escolhido = None
                cadeia = usuario + gratis
        self.cache = {}
        self.descanso_ate = {}
        self.escolhido = escolhido
        self.cadeia = cadeia

    def traduzir(self, texto, src):
        """Devolve (tradução, nome do provedor usado)."""
        chave = (src, texto)
        if chave in self.cache:
            return self.cache[chave]
        agora = time.time()
        erros = []
        for p in self.cadeia:
            if self.descanso_ate.get(p["id"], 0) > agora:
                continue
            try:
                resultado = TRADUTORES[p["tipo"]](p, texto, src, self.anterior)
                if not resultado:
                    raise ErroProvedor("resposta vazia")
                self.ultimo = p["nome"]
                self.anterior = texto
                self.cache[chave] = (resultado, p["nome"])
                return self.cache[chave]
            except Exception as e:
                espera = self.DESCANSO_ESCOLHIDO if p["id"] == self.escolhido else self.DESCANSO
                self.descanso_ate[p["id"]] = time.time() + espera
                erros.append(f"{p['nome']}: {str(e)[:90]}")
        raise ErroProvedor(" | ".join(erros) or "todos os serviços estão em descanso")


# ----------------------------------------------------------------------------
# Reconhecimento de fala
# ----------------------------------------------------------------------------
_ES = set("el la los las de que y en un una es por con para pero como muy está no se lo me te qué más "
          "su al del yo tú nos cuando porque también hay esto esta".split())
_EN = set("the and is are to of in that it you for with this was have but not on be we they i he she "
          "my your what so just like".split())


def detectar_idioma(texto):
    """Palpite simples (japonês, espanhol ou inglês) para quando a API não informa o idioma."""
    if re.search(r"[぀-ヿ一-鿿]", texto):
        return "ja"
    palavras = re.findall(r"[a-záéíóúñü]+", texto.lower())
    es = sum(w in _ES for w in palavras) + 2 * len(re.findall(r"[ñ¿¡]", texto.lower()))
    en = sum(w in _EN for w in palavras)
    return "es" if es > en else "en"


def para_wav(audio):
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def transcrever_api(p, audio, idioma):
    """Transcrição por API compatível com OpenAI. Devolve (texto, idioma)."""
    modelo = p["modelo"]
    dados = {"model": modelo,
             "response_format": "verbose_json" if modelo.lower().startswith("whisper") else "json"}
    if idioma:
        dados["language"] = idioma
    r = requests.post(p["url"].rstrip("/") + "/audio/transcriptions",
                      headers={"Authorization": f"Bearer {p['chave']}"}, data=dados,
                      files={"file": ("audio.wav", para_wav(audio), "audio/wav")}, timeout=30)
    j = _checar(r).json()
    texto = (j.get("text") or "").strip()
    lang = idioma
    if lang is None and texto:
        nome = (j.get("language") or "").lower()
        lang = NOME_PARA_COD.get(nome) or (nome if len(nome) == 2 else None)
        if lang not in C.PERMITIDOS and lang != "pt":
            lang = detectar_idioma(texto)
    return texto, lang


class ReconhecedorLocal:
    """Whisper rodando neste computador (faster-whisper)."""

    def __init__(self, cfg, avisar):
        self.cfg, self.avisar = cfg, avisar
        self.modelo = None
        self.trava = threading.Lock()

    def carregar(self):
        with self.trava:
            if self.modelo is not None:
                return
            import os
            from pathlib import Path

            from faster_whisper import WhisperModel

            cfg = self.cfg
            self.avisar(f"Carregando o modelo '{cfg['model']}' (na primeira vez ele é baixado)...")
            pasta = Path(C.pasta_modelos(cfg))
            pasta.mkdir(parents=True, exist_ok=True)
            cpu = cfg["device"] == "cpu"
            self.modelo = WhisperModel(
                cfg["model"], device=cfg["device"], compute_type="int8" if cpu else "float16",
                download_root=str(pasta), cpu_threads=max(4, min(8, os.cpu_count() or 4)) if cpu else 0)

    def transcrever(self, audio, idioma):
        self.carregar()
        kw = dict(beam_size=1, vad_filter=True, condition_on_previous_text=False, no_speech_threshold=0.6)
        segs, info = self.modelo.transcribe(audio, language=idioma, **kw)
        segs = list(segs)
        lang = idioma
        if idioma is None:
            probs = dict(getattr(info, "all_language_probs", None) or [])
            melhor = max(C.PERMITIDOS, key=lambda c: probs.get(c, 0.0)) if probs else info.language
            if melhor in C.PERMITIDOS and melhor != info.language:
                segs, info = self.modelo.transcribe(audio, language=melhor, **kw)
                segs = list(segs)
            lang = melhor if melhor in C.PERMITIDOS else info.language
        segs = [s for s in segs if s.avg_logprob > -1.2 and s.no_speech_prob < 0.7]
        return " ".join(s.text.strip() for s in segs).strip(), lang


class GerenciadorFala:
    """Usa o Whisper local ou uma API de transcrição, conforme a escolha do usuário."""

    def __init__(self, cfg, avisar):
        self.local = ReconhecedorLocal(cfg, avisar)
        self.api = None
        self.reconfigurar(cfg)

    def reconfigurar(self, cfg):
        ativo = cfg.get("fala_ativa", "whisper_local")
        self.api = next((p for p in cfg["provedores"]
                         if p["id"] == ativo and C.TIPOS[p["tipo"]]["funcao"] == "fala"), None)

    def transcrever(self, audio, idioma):
        """Devolve (texto, idioma, nome do provedor)."""
        if self.api is not None:
            texto, lang = transcrever_api(self.api, audio, idioma)
            return texto, lang, self.api["nome"]
        texto, lang = self.local.transcrever(audio, idioma)
        return texto, lang, "Whisper local"


# ----------------------------------------------------------------------------
# Teste de conexão (botão "Testar" das configurações)
# ----------------------------------------------------------------------------
def testar_provedor(p):
    """Devolve uma mensagem de sucesso ou levanta uma exceção com o motivo."""
    funcao = C.funcao_do(p)
    if p["tipo"] == "whisper_local":
        return "O Whisper local não usa rede. Ele é testado ao tocar um áudio."
    if funcao == "traducao":
        t0 = time.time()
        r = TRADUTORES[p["tipo"]](p, "Hello, how are you today?", "en", "")
        return f"Funcionou em {time.time() - t0:.1f}s.\n\nTeste: “Hello, how are you today?”\nResposta: “{r}”"
    t0 = time.time()
    transcrever_api(p, np.zeros(16000, dtype=np.float32), None)
    return f"Conexão e chave aceitas ({time.time() - t0:.1f}s)."
