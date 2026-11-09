"""
Tradutor de áudio do Windows -> Português (Brasil)

Captura o que está tocando no computador (alto-falante, fone com fio, Bluetooth,
HDMI...) via WASAPI loopback, transcreve com Whisper (espanhol, inglês ou
japonês, detecção automática) e mostra a tradução em tempo quase real.

Uso:
    python tradutor_audio.py                 # modelo "small", CPU
    python tradutor_audio.py --model base    # mais rápido, menos preciso
    python tradutor_audio.py --device cuda   # placa NVIDIA
    python tradutor_audio.py --offline       # tradução offline (Argos)
    python tradutor_audio.py --log saida.txt # grava transcrições em arquivo
"""
import argparse
import collections
import datetime
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import ttk

# No .exe sem console, stdout/stderr são None e bibliotecas que escrevem
# barras de progresso (download do modelo) quebrariam. Redireciona para o nada.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import numpy as np
import pyaudiowpatch as pyaudio

# Pasta do programa (ao lado do .exe quando empacotado)
PASTA_APP = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent

TARGET_RATE = 16000
IDIOMAS = {"Automático": None, "Espanhol": "es", "Inglês": "en", "Japonês": "ja"}
PERMITIDOS = ("es", "en", "ja")


# --------------------------------------------------------------------------
# Captura do áudio que sai do computador (loopback)
# --------------------------------------------------------------------------
def achar_loopback(p):
    """Devolve o dispositivo loopback correspondente à saída padrão atual."""
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    saida = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    if saida.get("isLoopbackDevice"):
        return saida
    for lb in p.get_loopback_device_info_generator():
        if saida["name"] in lb["name"]:
            return lb
    raise RuntimeError("Nenhum dispositivo loopback encontrado para a saída padrão.")


def nome_saida_padrao():
    p = pyaudio.PyAudio()
    try:
        return achar_loopback(p)["name"]
    finally:
        p.terminate()


def para_16k_mono(raw, canais, taxa):
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if canais > 1:
        x = x[: len(x) // canais * canais].reshape(-1, canais).mean(axis=1)
    if taxa == TARGET_RATE:
        return x
    if taxa % TARGET_RATE == 0:
        f = taxa // TARGET_RATE
        return x[: len(x) // f * f].reshape(-1, f).mean(axis=1)
    n = int(len(x) * TARGET_RATE / taxa)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


class Captura(threading.Thread):
    """Captura o loopback e acompanha mudanças do dispositivo padrão
    (plugar/desplugar fone, trocar para Bluetooth etc.)."""

    def __init__(self, audio_q, ui_q, parar):
        super().__init__(daemon=True)
        self.audio_q, self.ui_q, self.parar = audio_q, ui_q, parar

    def run(self):
        while not self.parar.is_set():
            p = pyaudio.PyAudio()
            stream = None
            try:
                dev = achar_loopback(p)
                taxa = int(dev["defaultSampleRate"])
                canais = int(dev["maxInputChannels"])

                def callback(dados, frames, tempo, status):
                    try:
                        self.audio_q.put_nowait(para_16k_mono(dados, canais, taxa))
                    except queue.Full:
                        pass
                    return (None, pyaudio.paContinue)

                stream = p.open(
                    format=pyaudio.paInt16, channels=canais, rate=taxa, input=True,
                    input_device_index=dev["index"], frames_per_buffer=2048,
                    stream_callback=callback,
                )
                self.ui_q.put(("status", f"Capturando: {dev['name']}"))
                while not self.parar.is_set():
                    time.sleep(1.5)
                    try:
                        if nome_saida_padrao() != dev["name"]:
                            self.ui_q.put(("status", "Dispositivo de saída mudou, reconectando..."))
                            break
                    except Exception:
                        break
            except Exception as e:
                self.ui_q.put(("status", f"Erro na captura: {e}"))
                time.sleep(2)
            finally:
                if stream is not None:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
                p.terminate()


# --------------------------------------------------------------------------
# Segmentação por silêncio
# --------------------------------------------------------------------------
class Segmentador(threading.Thread):
    def __init__(self, audio_q, seg_q, ui_q, parar, pausado, limiar, max_seg):
        super().__init__(daemon=True)
        self.audio_q, self.seg_q, self.ui_q = audio_q, seg_q, ui_q
        self.parar, self.pausado = parar, pausado
        self.limiar, self.max_seg = limiar, max_seg

    def emitir(self, buf, dur_fala):
        if dur_fala < 0.5:
            return
        audio = np.concatenate(buf)
        if self.seg_q.full():
            try:
                self.seg_q.get_nowait()  # descarta o mais antigo se o modelo não acompanha
                self.ui_q.put(("status", "Processamento atrasado: descartando trecho antigo"))
            except queue.Empty:
                pass
        self.seg_q.put(audio)

    def run(self):
        pre = collections.deque(maxlen=6)
        buf, falando, silencio, total = [], False, 0.0, 0.0
        while not self.parar.is_set():
            try:
                chunk = self.audio_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if self.pausado.is_set() or len(chunk) == 0:
                buf, falando, silencio, total = [], False, 0.0, 0.0
                continue
            dur = len(chunk) / TARGET_RATE
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            if rms >= self.limiar:
                if not falando:
                    buf = list(pre)
                    falando = True
                buf.append(chunk)
                total += dur
                silencio = 0.0
            elif falando:
                buf.append(chunk)
                total += dur
                silencio += dur
            else:
                pre.append(chunk)
                continue
            if falando and (silencio >= 0.7 or total >= self.max_seg):
                self.emitir(buf, total - silencio)
                buf, falando, silencio, total = [], False, 0.0, 0.0
                pre.clear()


# --------------------------------------------------------------------------
# Transcrição + tradução
# --------------------------------------------------------------------------
def criar_tradutor(offline):
    if offline:
        import argostranslate.translate as at

        return lambda texto, src: at.translate(texto, src, "pt")
    from deep_translator import GoogleTranslator

    return lambda texto, src: GoogleTranslator(source=src, target="pt").translate(texto)


class Transcritor(threading.Thread):
    def __init__(self, args, seg_q, ui_q, parar, idioma_var):
        super().__init__(daemon=True)
        self.args, self.seg_q, self.ui_q = args, seg_q, ui_q
        self.parar, self.idioma_var = parar, idioma_var

    def run(self):
        from faster_whisper import WhisperModel

        self.ui_q.put(("status", f"Carregando modelo '{self.args.model}' (1ª vez baixa o arquivo)..."))
        try:
            tipo = "float16" if self.args.device == "cuda" else "int8"
            pasta = Path(self.args.pasta_modelos)
            pasta.mkdir(parents=True, exist_ok=True)
            modelo = WhisperModel(self.args.model, device=self.args.device, compute_type=tipo,
                                  download_root=str(pasta))
            traduzir = criar_tradutor(self.args.offline)
        except Exception as e:
            self.ui_q.put(("status", f"Erro ao iniciar: {e}"))
            return
        self.ui_q.put(("status", "Pronto. Toque algum áudio no computador."))

        while not self.parar.is_set():
            try:
                audio = self.seg_q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                lang = self.idioma_var["codigo"]
                kw = dict(beam_size=1, vad_filter=True, condition_on_previous_text=False,
                          no_speech_threshold=0.6)
                segs, info = modelo.transcribe(audio, language=lang, **kw)
                segs = list(segs)
                if lang is None:
                    probs = dict(getattr(info, "all_language_probs", None) or [])
                    melhor = max(PERMITIDOS, key=lambda c: probs.get(c, 0.0)) if probs else info.language
                    if melhor in PERMITIDOS and melhor != info.language:
                        segs, info = modelo.transcribe(audio, language=melhor, **kw)
                        segs = list(segs)
                    lang = melhor if melhor in PERMITIDOS else info.language
                segs = [s for s in segs if s.avg_logprob > -1.2 and s.no_speech_prob < 0.7]
                texto = " ".join(s.text.strip() for s in segs).strip()
                if not texto:
                    continue
                if lang == "pt":
                    trad = texto
                else:
                    try:
                        trad = traduzir(texto, lang)
                    except Exception as e:
                        trad = f"[falha na tradução: {e}]"
                self.ui_q.put(("linha", lang, texto, trad))
            except Exception as e:
                self.ui_q.put(("status", f"Erro ao processar trecho: {e}"))


# --------------------------------------------------------------------------
# Janela
# --------------------------------------------------------------------------
class App:
    def __init__(self, args):
        self.args = args
        self.parar = threading.Event()
        self.pausado = threading.Event()
        self.ui_q = queue.Queue()
        self.audio_q = queue.Queue(maxsize=400)
        self.seg_q = queue.Queue(maxsize=3)
        self.idioma = {"codigo": None}

        self.root = tk.Tk()
        self.root.title("Tradutor de áudio → Português (Brasil)")
        self.root.geometry("820x460")
        self.root.configure(bg="#14161a")
        self.root.attributes("-topmost", True)

        topo = tk.Frame(self.root, bg="#14161a")
        topo.pack(fill="x", padx=10, pady=8)
        tk.Label(topo, text="Idioma de origem:", bg="#14161a", fg="#ccc").pack(side="left")
        self.combo = ttk.Combobox(topo, values=list(IDIOMAS), state="readonly", width=12)
        self.combo.set("Automático")
        self.combo.pack(side="left", padx=6)
        self.combo.bind("<<ComboboxSelected>>", self.mudou_idioma)

        self.mostrar_orig = tk.BooleanVar(value=True)
        tk.Checkbutton(topo, text="Mostrar original", variable=self.mostrar_orig, bg="#14161a",
                       fg="#ccc", selectcolor="#14161a", activebackground="#14161a").pack(side="left", padx=8)
        self.fixo = tk.BooleanVar(value=True)
        tk.Checkbutton(topo, text="Sempre no topo", variable=self.fixo, command=self.alterna_topo,
                       bg="#14161a", fg="#ccc", selectcolor="#14161a",
                       activebackground="#14161a").pack(side="left")
        self.btn_pausa = ttk.Button(topo, text="Pausar", command=self.alterna_pausa)
        self.btn_pausa.pack(side="right")
        ttk.Button(topo, text="Limpar", command=self.limpar).pack(side="right", padx=6)

        self.txt = tk.Text(self.root, bg="#14161a", fg="#f2f2f2", wrap="word", bd=0,
                           padx=12, pady=8, state="disabled")
        self.txt.pack(fill="both", expand=True)
        self.txt.tag_config("meta", foreground="#7d8590", font=("Segoe UI", 9))
        self.txt.tag_config("orig", foreground="#9aa4b2", font=("Segoe UI", 11))
        self.txt.tag_config("trad", foreground="#ffffff", font=("Segoe UI", 17, "bold"))

        self.status = tk.Label(self.root, text="Iniciando...", anchor="w", bg="#0e1013", fg="#8b949e")
        self.status.pack(fill="x")

        Captura(self.audio_q, self.ui_q, self.parar).start()
        Segmentador(self.audio_q, self.seg_q, self.ui_q, self.parar, self.pausado,
                    args.limiar, args.max_seg).start()
        Transcritor(args, self.seg_q, self.ui_q, self.parar, self.idioma).start()

        self.root.protocol("WM_DELETE_WINDOW", self.fechar)
        self.root.after(100, self.consumir)

    def mudou_idioma(self, _=None):
        self.idioma["codigo"] = IDIOMAS[self.combo.get()]

    def alterna_topo(self):
        self.root.attributes("-topmost", self.fixo.get())

    def alterna_pausa(self):
        if self.pausado.is_set():
            self.pausado.clear()
            self.btn_pausa.config(text="Pausar")
        else:
            self.pausado.set()
            self.btn_pausa.config(text="Retomar")

    def limpar(self):
        self.txt.config(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.config(state="disabled")

    def consumir(self):
        try:
            while True:
                msg = self.ui_q.get_nowait()
                if msg[0] == "status":
                    self.status.config(text=msg[1])
                else:
                    self.adicionar(*msg[1:])
        except queue.Empty:
            pass
        if not self.parar.is_set():
            self.root.after(100, self.consumir)

    def adicionar(self, lang, original, traducao):
        hora = datetime.datetime.now().strftime("%H:%M:%S")
        self.txt.config(state="normal")
        self.txt.insert("end", f"{hora}  [{lang.upper()}]\n", "meta")
        if self.mostrar_orig.get():
            self.txt.insert("end", original + "\n", "orig")
        self.txt.insert("end", traducao + "\n\n", "trad")
        self.txt.see("end")
        self.txt.config(state="disabled")
        if self.args.log:
            with open(self.args.log, "a", encoding="utf-8") as f:
                f.write(f"{hora} [{lang}] {original}\n{hora} [pt] {traducao}\n\n")

    def fechar(self):
        self.parar.set()
        self.root.destroy()

    def rodar(self):
        self.root.mainloop()


def carregar_config():
    """Lê tradutor_config.json (opcional) ao lado do programa."""
    arq = PASTA_APP / "tradutor_config.json"
    if not arq.exists():
        return {}
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    cfg = carregar_config()
    ap = argparse.ArgumentParser(description="Tradutor de áudio do Windows para PT-BR")
    ap.add_argument("--model", default=cfg.get("model", "small"),
                    help="tiny, base, small, medium, large-v3 (padrão: small)")
    ap.add_argument("--device", default=cfg.get("device", "cpu"), choices=["cpu", "cuda"])
    ap.add_argument("--offline", action="store_true", default=cfg.get("offline", False),
                    help="usa Argos Translate em vez do Google (só na versão Python)")
    ap.add_argument("--limiar", type=float, default=cfg.get("limiar", 0.008),
                    help="sensibilidade da detecção de fala (RMS)")
    ap.add_argument("--max-seg", type=float, default=cfg.get("max_seg", 12.0),
                    help="duração máxima de cada trecho, em segundos")
    ap.add_argument("--log", default=cfg.get("log"), help="arquivo para salvar original e tradução")
    ap.add_argument("--pasta-modelos", default=cfg.get("pasta_modelos", str(PASTA_APP / "modelos")),
                    help="onde guardar os modelos baixados (padrão: pasta 'modelos' ao lado do programa)")
    args = ap.parse_args()

    try:  # nitidez em telas com escala > 100% (comum em notebooks)
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    try:
        App(args).rodar()
    except Exception:
        (PASTA_APP / "erro.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
