"""Captura do áudio que sai do computador (WASAPI loopback) e segmentação por silêncio."""
import collections
import queue
import threading
import time

import numpy as np
import pyaudiowpatch as pyaudio

TARGET_RATE = 16000

# Valores possíveis de cfg["dispositivo_audio"]; qualquer outro texto é o nome de um dispositivo.
AUTO = "auto"            # escuta todas as saídas e usa a que estiver com som
PADRAO_WIN = "padrao"    # só a saída padrão do Windows


def nome_curto(nome, limite=34):
    nome = nome.replace(" [Loopback]", "")
    return nome if len(nome) <= limite else nome[: limite - 1] + "…"


def listar_loopbacks(p):
    return list(p.get_loopback_device_info_generator())


def achar_loopback(p):
    """Devolve o dispositivo loopback correspondente à saída padrão atual."""
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    saida = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    if saida.get("isLoopbackDevice"):
        return saida
    for lb in listar_loopbacks(p):
        if saida["name"] in lb["name"]:
            return lb
    raise RuntimeError("Nenhum dispositivo loopback encontrado para a saída padrão.")


def nome_saida_padrao():
    p = pyaudio.PyAudio()
    try:
        return achar_loopback(p)["name"]
    finally:
        p.terminate()


def nomes_loopback():
    """Nomes de todas as saídas de áudio ativas (para a tela de configurações)."""
    p = pyaudio.PyAudio()
    try:
        return [d["name"] for d in listar_loopbacks(p)]
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
    """Captura o loopback. Em modo automático abre todas as saídas ativas e segue a que
    estiver tocando, o que cobre o Teams usando um dispositivo diferente do padrão do
    Windows e o fone Bluetooth que troca para o perfil de chamada (mãos-livres)."""

    def __init__(self, audio_q, ui_q, parar, cfg=None):
        super().__init__(daemon=True)
        self.audio_q, self.ui_q, self.parar = audio_q, ui_q, parar
        self.cfg = cfg if cfg is not None else {}
        self.nivel = 0.0  # volume recente (RMS), lido pela interface
        self._trava = threading.Lock()
        self._niveis = {}   # índice do dispositivo -> (nível suavizado, instante)
        self._ativo = None  # índice do dispositivo cujo áudio segue para o reconhecimento

    def _modo(self):
        return self.cfg.get("dispositivo_audio") or AUTO

    def _dispositivos(self, p):
        """Dispositivos a abrir e mensagem opcional, conforme o modo escolhido."""
        modo = self._modo()
        todos = listar_loopbacks(p)
        if modo == PADRAO_WIN:
            return [achar_loopback(p)], None
        if modo != AUTO:
            sel = [d for d in todos if d["name"] == modo]
            if sel:
                return sel, None
            msg = f"Dispositivo '{modo}' não está disponível, usando o modo automático"
            return todos, msg
        return todos, None

    def _assinatura(self):
        """Muda quando o conjunto de saídas ou o modo muda (precisa de uma instância nova do PyAudio)."""
        p = pyaudio.PyAudio()
        try:
            devs, _ = self._dispositivos(p)
            padrao = achar_loopback(p)["name"] if self._modo() == PADRAO_WIN else ""
            return (self._modo(), padrao, tuple(sorted(d["name"] for d in devs)))
        finally:
            p.terminate()

    def _callback(self, idx, canais, taxa):
        def cb(dados, frames, tempo, status):
            try:
                x = para_16k_mono(dados, canais, taxa)
                rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
                with self._trava:
                    ant = self._niveis.get(idx, (0.0, 0))[0]
                    self._niveis[idx] = (0.6 * ant + 0.4 * rms, time.time())
                if idx == self._ativo:
                    self.nivel = rms
                    self.audio_q.put_nowait(x)
            except queue.Full:
                pass
            except Exception:
                pass
            return (None, pyaudio.paContinue)
        return cb

    def _escolher_ativo(self, nomes):
        agora = time.time()
        with self._trava:
            recentes = {i: n for i, (n, t) in self._niveis.items() if agora - t < 0.6}
        if not recentes:
            return
        melhor = max(recentes, key=recentes.get)
        atual = recentes.get(self._ativo, 0.0)
        if melhor != self._ativo and recentes[melhor] > max(0.003, atual * 2):
            self._ativo = melhor
            self.ui_q.put(("detalhe", f"Áudio detectado em: {nomes.get(melhor, melhor)}"))
            self.ui_q.put(("estado", "ok", "Capturando · " + nome_curto(nomes.get(melhor, ""))))

    def run(self):
        while not self.parar.is_set():
            p = pyaudio.PyAudio()
            streams = []
            try:
                devs, aviso = self._dispositivos(p)
                if aviso:
                    self.ui_q.put(("detalhe", aviso))
                if not devs:
                    raise RuntimeError("Nenhuma saída de áudio ativa encontrada.")
                try:
                    padrao_idx = achar_loopback(p)["index"]
                except Exception:
                    padrao_idx = devs[0]["index"]
                indices = [d["index"] for d in devs]
                self._ativo = padrao_idx if padrao_idx in indices else indices[0]
                self._niveis.clear()
                nomes = {d["index"]: d["name"] for d in devs}
                erros = []
                for d in devs:
                    try:
                        streams.append(p.open(
                            format=pyaudio.paInt16, channels=int(d["maxInputChannels"]),
                            rate=int(d["defaultSampleRate"]), input=True, input_device_index=d["index"],
                            frames_per_buffer=2048,
                            stream_callback=self._callback(d["index"], int(d["maxInputChannels"]),
                                                           int(d["defaultSampleRate"]))))
                    except Exception as e:
                        erros.append(f"{d['name']}: {e}")
                if not streams:
                    raise RuntimeError("Não foi possível abrir nenhuma saída de áudio. " + "; ".join(erros))
                if len(devs) == 1:
                    self.ui_q.put(("detalhe", f"Dispositivo de áudio: {devs[0]['name']}"))
                else:
                    self.ui_q.put(("detalhe", f"Monitorando {len(streams)} saídas de áudio; "
                                              "seguindo a que estiver tocando"))
                self.ui_q.put(("estado", "ok", "Capturando · " + nome_curto(nomes[self._ativo])))
                inicial = self._assinatura()
                ultimo = time.time()
                while not self.parar.is_set():
                    time.sleep(0.25)
                    if len(streams) > 1:
                        self._escolher_ativo(nomes)
                    if time.time() - ultimo >= 1.5:
                        ultimo = time.time()
                        try:
                            mudou = self._assinatura() != inicial
                        except Exception:
                            mudou = True
                        if mudou:
                            self.ui_q.put(("estado", "carregando", "Reconectando"))
                            self.ui_q.put(("detalhe", "As saídas de áudio mudaram, reconectando..."))
                            break
            except Exception as e:
                self.ui_q.put(("estado", "erro", "Sem captura"))
                self.ui_q.put(("detalhe", f"Erro na captura de áudio: {e}"))
                time.sleep(2)
            finally:
                self.nivel = 0.0
                for s in streams:
                    try:
                        s.stop_stream()
                        s.close()
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
