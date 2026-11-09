"""Captura do áudio que sai do computador (WASAPI loopback) e segmentação por silêncio."""
import collections
import queue
import threading
import time

import numpy as np
import pyaudiowpatch as pyaudio

TARGET_RATE = 16000


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
        self.nivel = 0.0  # volume recente (RMS), lido pela interface

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
                        x = para_16k_mono(dados, canais, taxa)
                        self.nivel = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
                        self.audio_q.put_nowait(x)
                    except queue.Full:
                        pass
                    return (None, pyaudio.paContinue)

                stream = p.open(
                    format=pyaudio.paInt16, channels=canais, rate=taxa, input=True,
                    input_device_index=dev["index"], frames_per_buffer=2048,
                    stream_callback=callback,
                )
                self.ui_q.put(("estado", "ok", "Capturando"))
                self.ui_q.put(("detalhe", f"Dispositivo de áudio: {dev['name']}"))
                while not self.parar.is_set():
                    time.sleep(1.5)
                    try:
                        if nome_saida_padrao() != dev["name"]:
                            self.ui_q.put(("estado", "carregando", "Reconectando"))
                            self.ui_q.put(("detalhe", "A saída de áudio mudou, reconectando..."))
                            break
                    except Exception:
                        break
            except Exception as e:
                self.ui_q.put(("estado", "erro", "Sem captura"))
                self.ui_q.put(("detalhe", f"Erro na captura de áudio: {e}"))
                time.sleep(2)
            finally:
                self.nivel = 0.0
                if stream is not None:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
                p.terminate()


class Segmentador(threading.Thread):
    """Agrupa o áudio em trechos de fala, fechando cada um numa pausa."""

    def __init__(self, audio_q, seg_q, ui_q, parar, pausado, limiar, max_seg, silencio):
        super().__init__(daemon=True)
        self.audio_q, self.seg_q, self.ui_q = audio_q, seg_q, ui_q
        self.parar, self.pausado = parar, pausado
        # Estes três podem ser alterados com o programa aberto
        self.limiar, self.max_seg, self.silencio = limiar, max_seg, silencio

    def emitir(self, buf, dur_fala):
        if dur_fala < 0.5:
            return
        audio = np.concatenate(buf)
        if self.seg_q.full():
            try:
                self.seg_q.get_nowait()  # descarta o mais antigo se o reconhecimento não acompanha
                self.ui_q.put(("detalhe", "Processamento atrasado: descartando um trecho antigo"))
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
            if falando and (silencio >= self.silencio or total >= self.max_seg):
                self.emitir(buf, total - silencio)
                buf, falando, silencio, total = [], False, 0.0, 0.0
                pre.clear()
