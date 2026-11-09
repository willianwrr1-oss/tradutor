"""Configuração persistente e catálogo de provedores de API."""
import copy
import json
import sys
import uuid
from pathlib import Path

# Pasta do programa (ao lado do .exe quando empacotado)
PASTA_APP = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
ARQ_CONFIG = PASTA_APP / "tradutor_config.json"

IDIOMAS = {"Automático": None, "Espanhol": "es", "Inglês": "en", "Japonês": "ja"}
PERMITIDOS = ("es", "en", "ja")

FUNCOES = {"traducao": "Tradução", "fala": "Reconhecimento de fala"}
CAMPOS = {
    "url": "Endereço (URL)",
    "chave": "Chave de API",
    "modelo": "Modelo",
    "regiao": "Região",
}

# Tipos de provedor que o usuário pode adicionar na janela de configurações.
TIPOS = {
    "google_cloud": {
        "nome": "Google Cloud Translation", "funcao": "traducao",
        "campos": ["chave"], "obrig": ["chave"], "padrao": {},
        "dica": "Chave da API Cloud Translation. 500 mil caracteres grátis por mês.",
    },
    "deepl": {
        "nome": "DeepL", "funcao": "traducao",
        "campos": ["chave", "url"], "obrig": ["chave"], "padrao": {"url": ""},
        "dica": "Deixe a URL em branco: chaves terminadas em :fx usam a API gratuita, as demais a API Pro.",
    },
    "azure": {
        "nome": "Microsoft Azure Translator", "funcao": "traducao",
        "campos": ["chave", "regiao", "url"], "obrig": ["chave"],
        "padrao": {"url": "https://api.cognitive.microsofttranslator.com"},
        "dica": "A região (ex.: brazilsouth) é exigida por recursos regionais.",
    },
    "libretranslate": {
        "nome": "LibreTranslate", "funcao": "traducao",
        "campos": ["url", "chave"], "obrig": ["url"],
        "padrao": {"url": "http://localhost:5000"},
        "dica": "Servidor próprio ou público. A chave é opcional, conforme o servidor.",
    },
    "openai_llm": {
        "nome": "Modelo de linguagem (compatível com OpenAI)", "funcao": "traducao",
        "campos": ["url", "chave", "modelo"], "obrig": ["url", "chave", "modelo"],
        "padrao": {"url": "https://api.openai.com/v1", "modelo": "gpt-4o-mini"},
        "dica": "Serve para OpenAI, Groq, OpenRouter, servidores locais (LM Studio, Ollama) e outros "
                "que aceitem /chat/completions.",
    },
    "anthropic": {
        "nome": "Claude (Anthropic)", "funcao": "traducao",
        "campos": ["chave", "modelo", "url"], "obrig": ["chave", "modelo"],
        "padrao": {"url": "https://api.anthropic.com", "modelo": "claude-haiku-5-5"},
        "dica": "Um modelo menor responde mais rápido, o que reduz o atraso da tradução.",
    },
    "stt_openai": {
        "nome": "Transcrição (compatível com OpenAI)", "funcao": "fala",
        "campos": ["url", "chave", "modelo"], "obrig": ["url", "chave", "modelo"],
        "padrao": {"url": "https://api.openai.com/v1", "modelo": "whisper-1"},
        "dica": "Serve para OpenAI, Groq e outros que aceitem /audio/transcriptions. "
                "Modelos que começam com 'whisper' informam o idioma detectado.",
    },
}

# Provedores que já vêm com o programa (não editáveis)
BUILTIN_TRADUCAO = [
    {"id": "google_gratis", "nome": "Google (gratuito)", "tipo": "google_gratis"},
    {"id": "lingva", "nome": "Lingva (gratuito)", "tipo": "lingva"},
    {"id": "mymemory", "nome": "MyMemory (gratuito)", "tipo": "mymemory"},
]
BUILTIN_FALA = [{"id": "whisper_local", "nome": "Whisper local", "tipo": "whisper_local"}]

PADRAO = {
    "model": "small",
    "device": "cpu",
    "limiar": 0.008,
    "max_seg": 8.0,
    "silencio": 0.5,
    "log": None,
    "pasta_modelos": None,
    "offline": False,
    "tamanho_fonte": 17,
    "mostrar_original": True,
    "sempre_no_topo": True,
    "idioma_origem": "Automático",
    "fala_ativa": "whisper_local",
    "traducao_ativa": "auto",
    "reserva_gratis": True,
    "provedores": [],
}


def novo_provedor(tipo, **extra):
    info = TIPOS[tipo]
    p = {"id": uuid.uuid4().hex[:8], "nome": info["nome"], "tipo": tipo, "funcao": info["funcao"]}
    p.update(info["padrao"])
    p.update(extra)
    return p


def funcao_do(provedor):
    """Função ('traducao' ou 'fala') de um provedor, do usuário ou embutido."""
    if provedor["tipo"] in TIPOS:
        return TIPOS[provedor["tipo"]]["funcao"]
    return "fala" if provedor["tipo"] == "whisper_local" else "traducao"


def lista_provedores(cfg, funcao):
    """Embutidos + os adicionados pelo usuário, para a função pedida."""
    base = BUILTIN_TRADUCAO if funcao == "traducao" else BUILTIN_FALA
    usuario = [p for p in cfg["provedores"] if TIPOS[p["tipo"]]["funcao"] == funcao]
    return usuario + list(base) if funcao == "traducao" else list(base) + usuario


def pasta_modelos(cfg):
    return cfg.get("pasta_modelos") or str(PASTA_APP / "modelos")


def carregar():
    cfg = copy.deepcopy(PADRAO)
    try:
        dados = json.loads(ARQ_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        dados = {}
    if isinstance(dados, dict):
        for k, v in dados.items():
            if k in PADRAO or k == "google_api_key":
                cfg[k] = v
    # Migração do formato antigo (uma única chave do Google)
    chave = cfg.pop("google_api_key", None)
    if not isinstance(cfg["provedores"], list):
        cfg["provedores"] = []
    cfg["provedores"] = [p for p in cfg["provedores"] if isinstance(p, dict) and p.get("tipo") in TIPOS]
    if chave and not any(p["tipo"] == "google_cloud" for p in cfg["provedores"]):
        cfg["provedores"].append(novo_provedor("google_cloud", chave=chave))
    return cfg


def salvar(cfg):
    ARQ_CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
