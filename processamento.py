"""Thread que transforma trechos de áudio em texto traduzido."""
import queue
import threading
import time

from captura import TARGET_RATE


class Transcritor(threading.Thread):
    def __init__(self, fala, traducao, seg_q, ui_q, parar, idioma):
        super().__init__(daemon=True)
        self.fala, self.traducao = fala, traducao
        self.seg_q, self.ui_q, self.parar, self.idioma = seg_q, ui_q, parar, idioma

    def run(self):
        if self.fala.api is None:
            self.ui_q.put(("estado", "carregando", "Carregando modelo"))
            try:
                self.fala.local.carregar()
            except Exception as e:
                self.ui_q.put(("estado", "erro", "Erro no modelo"))
                self.ui_q.put(("detalhe", f"Não foi possível carregar o modelo: {str(e)[:200]}"))
        self.ui_q.put(("detalhe", "Pronto. Toque algum áudio no computador."))
        self.ui_q.put(("estado", "ok", "Pronto"))

        while not self.parar.is_set():
            try:
                audio = self.seg_q.get(timeout=0.2)
            except queue.Empty:
                continue
            t0 = time.time()
            try:
                texto, lang, prov_fala = self.fala.transcrever(audio, self.idioma["codigo"])
            except Exception as e:
                self.ui_q.put(("detalhe", f"Falha no reconhecimento da fala: {str(e)[:200]}"))
                continue
            if not texto or lang is None:
                continue
            t1 = time.time()
            trad, prov_tr = None, ""
            if lang == "pt":
                trad, prov_tr = texto, "—"
            else:
                try:
                    trad, prov_tr = self.traducao.traduzir(texto, lang)
                except Exception as e:
                    self.ui_q.put(("detalhe", f"Falha na tradução: {str(e)[:220]}"))
            self.ui_q.put(("linha", lang, texto, trad, prov_tr))
            if trad is not None:
                self.ui_q.put(("detalhe",
                               f"Último trecho: {len(audio) / TARGET_RATE:.1f}s de áudio · "
                               f"{prov_fala} {t1 - t0:.1f}s · {prov_tr} {time.time() - t1:.1f}s"))
