"""Interface gráfica (tkinter/ttk) com tema escuro."""
import copy
import datetime
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import configuracao as C
from captura import AUTO, PADRAO_WIN, Captura, Segmentador, nomes_loopback
from processamento import Transcritor
from provedores import GerenciadorFala, GerenciadorTraducao, testar_provedor

# Paleta
BG = "#0f1115"
PAINEL = "#171a21"
PAINEL2 = "#20242d"
BORDA = "#2a303c"
TXT = "#e6e9ef"
MUDO = "#8b93a3"
ACENTO = "#4c8dff"
OK = "#3ecf8e"
AVISO = "#f5a524"
ERRO = "#f2555a"
FONTE = ("Segoe UI", 10)
CORES_ESTADO = {"ok": OK, "carregando": AVISO, "erro": ERRO, "pausado": MUDO}
CORES_IDIOMA = {"en": "#3b6fd4", "es": "#c2542d", "ja": "#b03a6e", "pt": "#2f8f5b", "x": "#555d6e"}


def aplicar_tema(root):
    root.configure(bg=BG)
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", background=BG, foreground=TXT, fieldbackground=PAINEL, bordercolor=BORDA,
                 lightcolor=BORDA, darkcolor=BORDA, troughcolor=PAINEL, focuscolor=BG, font=FONTE)
    st.configure("TFrame", background=BG)
    st.configure("Painel.TFrame", background=PAINEL)
    st.configure("TLabel", background=BG, foreground=TXT)
    st.configure("Mudo.TLabel", background=BG, foreground=MUDO)
    st.configure("PainelMudo.TLabel", background=PAINEL, foreground=MUDO)
    st.configure("Titulo.TLabel", background=PAINEL, foreground=TXT, font=("Segoe UI Semibold", 13))
    st.configure("Aviso.TLabel", background=BG, foreground=AVISO)
    st.configure("TButton", background=PAINEL2, foreground=TXT, padding=(12, 6), borderwidth=1, relief="flat")
    st.map("TButton", background=[("active", "#2a303c"), ("pressed", "#323948")])
    st.configure("Acento.TButton", background=ACENTO, foreground="white")
    st.map("Acento.TButton", background=[("active", "#6aa0ff"), ("pressed", "#3a78e8")])
    st.configure("Pequeno.TButton", padding=(8, 6))
    st.configure("TCombobox", fieldbackground=PAINEL, background=PAINEL2, foreground=TXT, arrowcolor=TXT,
                 selectbackground=PAINEL, selectforeground=TXT, padding=4)
    st.map("TCombobox", fieldbackground=[("readonly", PAINEL)], foreground=[("readonly", TXT)],
           background=[("readonly", PAINEL2)])
    root.option_add("*TCombobox*Listbox.background", PAINEL)
    root.option_add("*TCombobox*Listbox.foreground", TXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACENTO)
    root.option_add("*TCombobox*Listbox.selectForeground", "white")
    st.configure("TCheckbutton", background=BG, foreground=TXT)
    st.map("TCheckbutton", background=[("active", BG)], foreground=[("active", TXT)])
    st.configure("TEntry", fieldbackground=PAINEL, foreground=TXT, insertcolor=TXT, padding=4)
    st.configure("TSpinbox", fieldbackground=PAINEL, foreground=TXT, insertcolor=TXT, arrowcolor=TXT, padding=4)
    st.configure("Treeview", background=PAINEL, fieldbackground=PAINEL, foreground=TXT, rowheight=28,
                 borderwidth=0)
    st.configure("Treeview.Heading", background=PAINEL2, foreground=MUDO, relief="flat", padding=6)
    st.map("Treeview", background=[("selected", ACENTO)], foreground=[("selected", "white")])
    st.configure("TNotebook", background=BG, borderwidth=0)
    st.configure("TNotebook.Tab", padding=(14, 8), background=PAINEL, foreground=MUDO)
    st.map("TNotebook.Tab", background=[("selected", PAINEL2)], foreground=[("selected", TXT)])
    st.configure("Nivel.Horizontal.TProgressbar", background=OK, troughcolor=PAINEL2, borderwidth=0)
    st.configure("Vertical.TScrollbar", background=PAINEL2, troughcolor=BG, arrowcolor=MUDO, borderwidth=0)


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.parar = threading.Event()
        self.pausado = threading.Event()
        self.ui_q = queue.Queue()
        self.audio_q = queue.Queue(maxsize=400)
        self.seg_q = queue.Queue(maxsize=3)
        self.idioma = {"codigo": C.IDIOMAS.get(cfg["idioma_origem"])}
        self.historico = []
        self.modo_legenda = False
        self._nivel = 0.0

        self.root = tk.Tk()
        self.root.title("Tradutor de áudio → Português (Brasil)")
        self.root.geometry("1000x660+80+50")
        self.root.minsize(900, 420)
        self.root.attributes("-topmost", bool(cfg.get("sempre_no_topo", True)))
        aplicar_tema(self.root)

        self.traducao = GerenciadorTraducao(cfg)
        self.fala = GerenciadorFala(cfg, lambda m: self.ui_q.put(("detalhe", m)))

        self.construir()
        self.atualizar_combos()
        self.configurar_tags()

        self.captura = Captura(self.audio_q, self.ui_q, self.parar, cfg)
        self.segmentador = Segmentador(self.audio_q, self.seg_q, self.ui_q, self.parar, self.pausado,
                                       cfg["limiar"], cfg["max_seg"], cfg["silencio"])
        self.transcritor = Transcritor(self.fala, self.traducao, self.seg_q, self.ui_q, self.parar, self.idioma)
        for t in (self.captura, self.segmentador, self.transcritor):
            t.start()

        self.root.protocol("WM_DELETE_WINDOW", self.fechar)
        self.root.bind("<Escape>", lambda e: self.alternar_legenda() if self.modo_legenda else None)
        self.root.after(100, self.consumir)

    # ------------------------------------------------------------------ layout
    def construir(self):
        root = self.root

        # Cabeçalho
        self.cab = ttk.Frame(root, style="Painel.TFrame")
        self.cab.pack(fill="x")
        interno = ttk.Frame(self.cab, style="Painel.TFrame")
        interno.pack(fill="x", padx=18, pady=12)
        ttk.Label(interno, text="Tradutor de áudio", style="Titulo.TLabel").pack(side="left")
        ttk.Label(interno, text="   →  Português (Brasil)", style="PainelMudo.TLabel").pack(side="left")
        self.nivel_bar = ttk.Progressbar(interno, style="Nivel.Horizontal.TProgressbar", length=90, maximum=100)
        self.nivel_bar.pack(side="right")
        ttk.Label(interno, text="Nível  ", style="PainelMudo.TLabel").pack(side="right", padx=(18, 0))
        self.lbl_estado = ttk.Label(interno, text="Iniciando", style="PainelMudo.TLabel")
        self.lbl_estado.pack(side="right", padx=(6, 0))
        self.ponto = tk.Canvas(interno, width=12, height=12, bg=PAINEL, highlightthickness=0)
        self.ponto.pack(side="right")
        self.ponto_item = self.ponto.create_oval(2, 2, 11, 11, fill=AVISO, outline="")

        # Barra de ferramentas
        self.barra = ttk.Frame(root)
        self.barra.pack(fill="x", padx=18, pady=(14, 8))
        self.cb_idioma = self.campo(self.barra, "Idioma de origem", 12)
        self.cb_idioma["values"] = list(C.IDIOMAS)
        self.cb_idioma.set(self.cfg["idioma_origem"] if self.cfg["idioma_origem"] in C.IDIOMAS else "Automático")
        self.cb_idioma.bind("<<ComboboxSelected>>", self.mudou_idioma)
        self.cb_fala = self.campo(self.barra, "Reconhecimento de fala", 22)
        self.cb_fala.bind("<<ComboboxSelected>>", self.mudou_fala)
        self.cb_trad = self.campo(self.barra, "Tradução", 26)
        self.cb_trad.bind("<<ComboboxSelected>>", self.mudou_traducao)

        direita = ttk.Frame(self.barra)
        direita.pack(side="right", anchor="s")
        ttk.Button(direita, text="⚙  Configurações", command=self.abrir_config).pack(side="right", padx=(8, 0))
        self.btn_pausa = ttk.Button(direita, text="Pausar", style="Acento.TButton", command=self.alternar_pausa)
        self.btn_pausa.pack(side="right", padx=(8, 0))

        # Segunda linha: ações secundárias
        self.barra2 = ttk.Frame(root)
        self.barra2.pack(fill="x", padx=18, pady=(0, 10))
        self.var_original = tk.BooleanVar(value=self.cfg["mostrar_original"])
        ttk.Checkbutton(self.barra2, text="Mostrar original", variable=self.var_original,
                        command=self.mudou_original).pack(side="left")
        self.var_topo = tk.BooleanVar(value=bool(self.cfg.get("sempre_no_topo", True)))
        ttk.Checkbutton(self.barra2, text="Sempre no topo", variable=self.var_topo,
                        command=self.mudou_topo).pack(side="left", padx=(18, 0))
        acoes = ttk.Frame(self.barra2)
        acoes.pack(side="right")
        ttk.Button(acoes, text="Legenda", command=self.alternar_legenda).pack(side="right", padx=(8, 0))
        ttk.Button(acoes, text="A+", style="Pequeno.TButton", width=3,
                   command=lambda: self.mudar_fonte(+1)).pack(side="right", padx=(8, 0))
        ttk.Button(acoes, text="A−", style="Pequeno.TButton", width=3,
                   command=lambda: self.mudar_fonte(-1)).pack(side="right", padx=(8, 0))
        ttk.Button(acoes, text="Exportar", command=self.exportar).pack(side="right", padx=(8, 0))
        ttk.Button(acoes, text="Copiar", command=self.copiar).pack(side="right", padx=(8, 0))
        ttk.Button(acoes, text="Limpar", command=self.limpar).pack(side="right", padx=(8, 0))

        # Rodapé (empacotado antes da área de texto para manter a posição)
        self.rodape = ttk.Frame(root, style="Painel.TFrame")
        self.rodape.pack(side="bottom", fill="x")
        self.detalhe = ttk.Label(self.rodape, text="Iniciando...", style="PainelMudo.TLabel", anchor="w")
        self.detalhe.pack(fill="x", padx=18, pady=7)

        # Área de texto
        self.area = ttk.Frame(root)
        self.area.pack(fill="both", expand=True, padx=(18, 8), pady=(0, 10))
        self.txt = tk.Text(self.area, bg=PAINEL, fg=TXT, wrap="word", bd=0, highlightthickness=1,
                           highlightbackground=BORDA, highlightcolor=BORDA, padx=18, pady=14,
                           state="disabled", cursor="arrow", insertwidth=0, selectbackground=ACENTO)
        sb = ttk.Scrollbar(self.area, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(4, 0))
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt.bind("<Double-Button-1>", lambda e: self.alternar_legenda() if self.modo_legenda else None)

    @staticmethod
    def campo(pai, rotulo, largura):
        f = ttk.Frame(pai)
        f.pack(side="left", padx=(0, 14))
        ttk.Label(f, text=rotulo, style="Mudo.TLabel").pack(anchor="w", pady=(0, 3))
        cb = ttk.Combobox(f, state="readonly", width=largura)
        cb.pack()
        return cb

    def configurar_tags(self):
        tam = int(self.cfg["tamanho_fonte"]) + (5 if self.modo_legenda else 0)
        t = self.txt
        t.tag_config("hora", foreground=MUDO, font=("Segoe UI", 9), spacing1=2)
        for cod, cor in CORES_IDIOMA.items():
            t.tag_config(f"b_{cod}", foreground="white", background=cor, font=("Segoe UI Semibold", 9))
        t.tag_config("orig", foreground=MUDO, font=("Segoe UI", max(9, tam - 6)), spacing1=4)
        t.tag_config("trad", foreground=TXT, font=("Segoe UI Semibold", tam), spacing1=3)
        t.tag_config("aviso", foreground=AVISO, font=("Segoe UI", max(9, tam - 5)), spacing1=3)
        t.tag_config("esp", font=("Segoe UI", 6))

    # ----------------------------------------------------------------- estado
    def definir_estado(self, nivel, texto):
        self.ponto.itemconfig(self.ponto_item, fill=CORES_ESTADO.get(nivel, MUDO))
        self.lbl_estado.config(text=texto)

    def consumir(self):
        try:
            while True:
                msg = self.ui_q.get_nowait()
                if msg[0] == "estado":
                    if msg[1] == "ok" and msg[2].startswith("Capturando"):
                        self.texto_captura = msg[2]
                    if not self.pausado.is_set():
                        self.definir_estado(msg[1], msg[2])
                elif msg[0] == "detalhe":
                    self.detalhe.config(text=msg[1])
                elif msg[0] == "linha":
                    self.adicionar(*msg[1:])
        except queue.Empty:
            pass
        v = min(100.0, self.captura.nivel * 600.0)
        self._nivel = max(v, self._nivel * 0.75)
        self.nivel_bar["value"] = self._nivel
        if not self.parar.is_set():
            self.root.after(100, self.consumir)

    # ------------------------------------------------------------- transcrição
    def adicionar(self, lang, original, trad, prov):
        item = (datetime.datetime.now().strftime("%H:%M:%S"), lang, original, trad, prov)
        self.historico.append(item)
        del self.historico[:-500]
        if self.modo_legenda:
            self.renderizar()
        else:
            self.inserir_item(item)
        if self.cfg.get("log"):
            try:
                with open(self.cfg["log"], "a", encoding="utf-8") as f:
                    f.write(f"{item[0]} [{lang}] {original}\n{item[0]} [pt] {trad or '(sem tradução)'}\n\n")
            except OSError:
                pass

    def inserir_item(self, item):
        hora, lang, original, trad, prov = item
        t = self.txt
        no_fim = t.yview()[1] >= 0.98
        t.config(state="normal")
        if not self.modo_legenda:
            t.insert("end", f" {lang.upper()} ", f"b_{lang}" if lang in CORES_IDIOMA else "b_x")
            extra = f"  ·  {prov}" if prov and prov != "—" else ""
            t.insert("end", f"  {hora}{extra}\n", "hora")
            if self.var_original.get():
                t.insert("end", original + "\n", "orig")
        if trad is None:
            t.insert("end", "[sem tradução no momento — veja a barra inferior]\n", "aviso")
        else:
            t.insert("end", trad + "\n", "trad")
        t.insert("end", "\n", "esp")
        if no_fim or self.modo_legenda:
            t.see("end")
        t.config(state="disabled")

    def renderizar(self):
        self.txt.config(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.config(state="disabled")
        itens = self.historico[-3:] if self.modo_legenda else self.historico[-200:]
        for item in itens:
            self.inserir_item(item)
        self.txt.see("end")

    # ------------------------------------------------------------------ ações
    def alternar_pausa(self):
        if self.pausado.is_set():
            self.pausado.clear()
            self.btn_pausa.config(text="Pausar")
            self.definir_estado("ok", getattr(self, "texto_captura", "Capturando"))
        else:
            self.pausado.set()
            self.btn_pausa.config(text="Retomar")
            self.definir_estado("pausado", "Pausado")

    def limpar(self):
        self.historico.clear()
        self.renderizar()

    def texto_completo(self):
        blocos = []
        for hora, lang, original, trad, prov in self.historico:
            blocos.append(f"[{hora}] ({lang.upper()}) {original}\n{trad or '(sem tradução)'}")
        return "\n\n".join(blocos)

    def copiar(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.texto_completo())
        self.detalhe.config(text=f"{len(self.historico)} trechos copiados para a área de transferência.")

    def exportar(self):
        if not self.historico:
            messagebox.showinfo("Exportar", "Ainda não há nada para exportar.", parent=self.root)
            return
        nome = datetime.datetime.now().strftime("traducao_%Y%m%d_%H%M%S.txt")
        arq = filedialog.asksaveasfilename(parent=self.root, defaultextension=".txt", initialfile=nome,
                                           filetypes=[("Texto", "*.txt")])
        if arq:
            with open(arq, "w", encoding="utf-8") as f:
                f.write(self.texto_completo())
            self.detalhe.config(text=f"Salvo em {arq}")

    def mudar_fonte(self, delta):
        self.cfg["tamanho_fonte"] = max(10, min(40, int(self.cfg["tamanho_fonte"]) + delta))
        self.configurar_tags()
        self.salvar_silencioso()

    def mudou_original(self):
        self.cfg["mostrar_original"] = self.var_original.get()
        self.renderizar()
        self.salvar_silencioso()

    def mudou_topo(self):
        self.cfg["sempre_no_topo"] = self.var_topo.get()
        self.root.attributes("-topmost", self.var_topo.get())
        self.salvar_silencioso()

    def alternar_legenda(self):
        self.modo_legenda = not self.modo_legenda
        if self.modo_legenda:
            for w in (self.cab, self.barra, self.barra2, self.rodape):
                w.pack_forget()
            self.root.attributes("-alpha", 0.93)
            self.detalhe.config(text="")
        else:
            self.cab.pack(fill="x", before=self.area)
            self.barra.pack(fill="x", padx=18, pady=(14, 8), before=self.area)
            self.barra2.pack(fill="x", padx=18, pady=(0, 10), before=self.area)
            self.rodape.pack(side="bottom", fill="x", before=self.area)
            self.root.attributes("-alpha", 1.0)
        self.configurar_tags()
        self.renderizar()

    # ---------------------------------------------------------------- seleções
    def atualizar_combos(self):
        self.mapa_fala = [(p["nome"], p["id"]) for p in C.lista_provedores(self.cfg, "fala")]
        self.cb_fala["values"] = [n for n, _ in self.mapa_fala]
        self.mapa_trad = [("Automático (melhor disponível)", "auto")] + \
                         [(p["nome"], p["id"]) for p in C.lista_provedores(self.cfg, "traducao")]
        self.cb_trad["values"] = [n for n, _ in self.mapa_trad]
        self.cb_fala.set(self._nome_de(self.mapa_fala, self.cfg["fala_ativa"], "Whisper local"))
        self.cb_trad.set(self._nome_de(self.mapa_trad, self.cfg["traducao_ativa"], "Automático (melhor disponível)"))

    @staticmethod
    def _nome_de(mapa, pid, padrao):
        return next((n for n, i in mapa if i == pid), padrao)

    @staticmethod
    def _id_de(mapa, nome):
        return next((i for n, i in mapa if n == nome), None)

    def mudou_idioma(self, _=None):
        nome = self.cb_idioma.get()
        self.idioma["codigo"] = C.IDIOMAS[nome]
        self.cfg["idioma_origem"] = nome
        self.salvar_silencioso()

    def mudou_fala(self, _=None):
        pid = self._id_de(self.mapa_fala, self.cb_fala.get()) or "whisper_local"
        self.cfg["fala_ativa"] = pid
        self.fala.reconfigurar(self.cfg)
        self.salvar_silencioso()
        self.detalhe.config(text=f"Reconhecimento de fala: {self.cb_fala.get()}")

    def mudou_traducao(self, _=None):
        pid = self._id_de(self.mapa_trad, self.cb_trad.get()) or "auto"
        self.cfg["traducao_ativa"] = pid
        self.traducao.reconfigurar(self.cfg)
        self.salvar_silencioso()
        self.detalhe.config(text=f"Tradução: {self.cb_trad.get()}")

    def salvar_silencioso(self):
        try:
            C.salvar(self.cfg)
        except OSError as e:
            self.detalhe.config(text=f"Não foi possível salvar as configurações: {e}")

    # ------------------------------------------------------------ configurações
    def abrir_config(self):
        JanelaConfig(self)

    def aplicar_config(self, novo):
        reiniciar = (novo["model"], novo["device"]) != (self.cfg["model"], self.cfg["device"])
        self.cfg.clear()
        self.cfg.update(novo)
        self.segmentador.limiar = self.cfg["limiar"]
        self.segmentador.max_seg = self.cfg["max_seg"]
        self.segmentador.silencio = self.cfg["silencio"]
        self.traducao.reconfigurar(self.cfg)
        self.fala.reconfigurar(self.cfg)
        self.atualizar_combos()
        self.renderizar()
        self.salvar_silencioso()
        if reiniciar:
            messagebox.showinfo("Configurações", "O modelo e o processador só mudam depois de fechar e "
                                                 "abrir o programa de novo.", parent=self.root)

    def fechar(self):
        self.parar.set()
        self.root.destroy()

    def rodar(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Janela de configurações
# ---------------------------------------------------------------------------
def rodar_em_thread(janela, funcao, depois):
    """Executa `funcao` fora da interface e chama `depois(ok, valor)` na interface."""
    fila = queue.Queue()

    def alvo():
        try:
            fila.put((True, funcao()))
        except Exception as e:
            fila.put((False, str(e)))

    def vigiar():
        try:
            ok, valor = fila.get_nowait()
        except queue.Empty:
            janela.after(150, vigiar)
            return
        depois(ok, valor)

    threading.Thread(target=alvo, daemon=True).start()
    janela.after(150, vigiar)


class JanelaConfig(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.cfg = copy.deepcopy(app.cfg)
        self.title("Configurações")
        self.configure(bg=BG)
        self.geometry("820x560")
        self.minsize(700, 480)
        self.transient(app.root)
        self.attributes("-topmost", True)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=16, pady=(16, 8))
        aba1 = ttk.Frame(nb, padding=16)
        aba2 = ttk.Frame(nb, padding=16)
        nb.add(aba1, text="Provedores de API")
        nb.add(aba2, text="Áudio e desempenho")
        self.montar_provedores(aba1)
        self.montar_desempenho(aba2)

        rod = ttk.Frame(self)
        rod.pack(fill="x", padx=16, pady=(0, 16))
        ttk.Button(rod, text="Salvar", style="Acento.TButton", command=self.salvar).pack(side="right")
        ttk.Button(rod, text="Cancelar", command=self.destroy).pack(side="right", padx=(0, 8))
        self.wait_visibility()
        self.grab_set()

    # --------------------------------------------------------------- provedores
    def montar_provedores(self, aba):
        ttk.Label(aba, text="Adicione serviços de tradução e de reconhecimento de fala. Depois escolha qual usar "
                            "na janela principal.", style="Mudo.TLabel", wraplength=720,
                  justify="left").pack(anchor="w", pady=(0, 10))
        corpo = ttk.Frame(aba)
        corpo.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(corpo, columns=("nome", "funcao", "origem"), show="headings", height=9)
        self.tree.heading("nome", text="Nome")
        self.tree.heading("funcao", text="Função")
        self.tree.heading("origem", text="Origem")
        self.tree.column("nome", width=300)
        self.tree.column("funcao", width=170)
        self.tree.column("origem", width=130)
        self.tree.tag_configure("padrao", foreground=MUDO)
        self.tree.pack(side="left", fill="both", expand=True)
        botoes = ttk.Frame(corpo)
        botoes.pack(side="left", fill="y", padx=(12, 0))
        for texto, cmd in (("Adicionar…", self.adicionar), ("Editar…", self.editar),
                           ("Remover", self.remover), ("Testar", self.testar)):
            ttk.Button(botoes, text=texto, command=cmd, width=12).pack(pady=(0, 8))
        self.msg = ttk.Label(aba, text="", style="Mudo.TLabel")
        self.msg.pack(anchor="w", pady=(8, 0))
        ttk.Label(aba, text="As chaves ficam gravadas em texto simples no arquivo tradutor_config.json, ao lado do "
                            "programa. Não compartilhe esse arquivo.", style="Aviso.TLabel", wraplength=720,
                  justify="left").pack(anchor="w", pady=(6, 0))
        self.recarregar_lista()

    def recarregar_lista(self):
        self.tree.delete(*self.tree.get_children())
        for funcao in ("traducao", "fala"):
            for p in C.lista_provedores(self.cfg, funcao):
                usuario = p["tipo"] in C.TIPOS
                self.tree.insert("", "end", iid=p["id"], tags=() if usuario else ("padrao",),
                                 values=(p["nome"], C.FUNCOES[funcao], "Adicionado por você" if usuario
                                         else "Já incluído"))

    def _selecionado(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Provedores", "Selecione um item da lista.", parent=self)
            return None
        iid = sel[0]
        for funcao in ("traducao", "fala"):
            for p in C.lista_provedores(self.cfg, funcao):
                if p["id"] == iid:
                    return p
        return None

    def adicionar(self):
        dlg = DialogoProvedor(self, None)
        self.wait_window(dlg)
        self.grab_set()
        if dlg.resultado:
            self.cfg["provedores"].append(dlg.resultado)
            self.recarregar_lista()

    def editar(self):
        p = self._selecionado()
        if p is None:
            return
        if p["tipo"] not in C.TIPOS:
            messagebox.showinfo("Provedores", "Os provedores já incluídos no programa não são editáveis.", parent=self)
            return
        dlg = DialogoProvedor(self, p)
        self.wait_window(dlg)
        self.grab_set()
        if dlg.resultado:
            p.clear()
            p.update(dlg.resultado)
            self.recarregar_lista()

    def remover(self):
        p = self._selecionado()
        if p is None:
            return
        if p["tipo"] not in C.TIPOS:
            messagebox.showinfo("Provedores", "Os provedores já incluídos no programa não podem ser removidos.", parent=self)
            return
        if messagebox.askyesno("Remover", f"Remover “{p['nome']}”?", parent=self):
            self.cfg["provedores"] = [x for x in self.cfg["provedores"] if x["id"] != p["id"]]
            for chave in ("fala_ativa", "traducao_ativa"):
                if self.cfg[chave] == p["id"]:
                    self.cfg[chave] = "whisper_local" if chave == "fala_ativa" else "auto"
            self.recarregar_lista()

    def testar(self):
        p = self._selecionado()
        if p is None:
            return
        self.msg.config(text=f"Testando “{p['nome']}”...")

        def depois(ok, valor):
            self.msg.config(text="")
            if ok:
                messagebox.showinfo("Teste", valor, parent=self)
            else:
                messagebox.showerror("Teste falhou", valor, parent=self)

        rodar_em_thread(self, lambda: testar_provedor(p), depois)

    # --------------------------------------------------------------- desempenho
    def montar_desempenho(self, aba):
        aba.columnconfigure(1, weight=1)
        self.v_model = tk.StringVar(value=self.cfg["model"])
        self.v_device = tk.StringVar(value=self.cfg["device"])
        self.v_limiar = tk.StringVar(value=f"{self.cfg['limiar']:.3f}")
        self.v_max = tk.StringVar(value=f"{self.cfg['max_seg']:.1f}")
        self.v_sil = tk.StringVar(value=f"{self.cfg['silencio']:.1f}")
        self.v_log = tk.StringVar(value=self.cfg.get("log") or "")
        self.v_reserva = tk.BooleanVar(value=self.cfg["reserva_gratis"])

        self.rot_auto = "Automático (o que estiver tocando)"
        self.rot_padrao = "Padrão do Windows"
        try:
            nomes = nomes_loopback()
        except Exception:
            nomes = []
        atual = self.cfg.get("dispositivo_audio") or AUTO
        self.v_disp = tk.StringVar(value=self.rot_auto if atual == AUTO else
                                   self.rot_padrao if atual == PADRAO_WIN else atual)

        def linha(i, rotulo, widget, dica=""):
            ttk.Label(aba, text=rotulo).grid(row=i * 2, column=0, sticky="w", pady=(10, 0), padx=(0, 20))
            widget.grid(row=i * 2, column=1, sticky="w", pady=(10, 0))
            if dica:
                ttk.Label(aba, text=dica, style="Mudo.TLabel").grid(row=i * 2 + 1, column=1, sticky="w")

        linha(0, "Dispositivo de áudio",
              ttk.Combobox(aba, textvariable=self.v_disp, state="readonly", width=44,
                           values=[self.rot_auto, self.rot_padrao] + nomes),
              "Automático acompanha o Teams mesmo que ele use outro fone ou alto-falante.")
        linha(1, "Modelo do Whisper local",
              ttk.Combobox(aba, textvariable=self.v_model, state="readonly", width=14,
                           values=["tiny", "base", "small", "medium", "large-v3"]),
              "Maior = mais preciso e mais lento. Vale depois de reabrir o programa.")
        linha(2, "Processador", ttk.Combobox(aba, textvariable=self.v_device, state="readonly", width=14,
                                             values=["cpu", "cuda"]),
              "cuda exige placa NVIDIA. Vale depois de reabrir o programa.")
        linha(3, "Sensibilidade à voz", ttk.Spinbox(aba, textvariable=self.v_limiar, from_=0.001, to=0.1,
                                                    increment=0.001, width=10, format="%.3f"),
              "Diminua se falas baixas não forem captadas.")
        linha(4, "Duração máxima do trecho (s)", ttk.Spinbox(aba, textvariable=self.v_max, from_=3, to=20,
                                                             increment=0.5, width=10, format="%.1f"),
              "Menor = menos atraso, mas frases mais cortadas.")
        linha(5, "Pausa que fecha um trecho (s)", ttk.Spinbox(aba, textvariable=self.v_sil, from_=0.2, to=2,
                                                              increment=0.1, width=10, format="%.1f"),
              "Menor = menos atraso.")
        linha(6, "Arquivo de registro", ttk.Entry(aba, textvariable=self.v_log, width=44),
              "Opcional. Ex.: transcricoes.txt (guarda original e tradução).")
        linha(7, "Reserva automática", ttk.Checkbutton(
            aba, text="Se o serviço escolhido falhar, usar os gratuitos", variable=self.v_reserva))

    def salvar(self):
        try:
            limiar, maxs, sil = float(self.v_limiar.get().replace(",", ".")), \
                float(self.v_max.get().replace(",", ".")), float(self.v_sil.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Valor inválido", "Use números nos campos de sensibilidade e duração.", parent=self)
            return
        disp = self.v_disp.get()
        disp = AUTO if disp == self.rot_auto else PADRAO_WIN if disp == self.rot_padrao else disp
        self.cfg.update(dispositivo_audio=disp, model=self.v_model.get(), device=self.v_device.get(), limiar=limiar, max_seg=maxs,
                        silencio=sil, log=self.v_log.get().strip() or None, reserva_gratis=self.v_reserva.get())
        self.app.aplicar_config(self.cfg)
        self.destroy()


class DialogoProvedor(tk.Toplevel):
    """Formulário para adicionar ou editar um provedor."""

    def __init__(self, pai, provedor):
        super().__init__(pai)
        self.pai, self.original = pai, provedor
        self.resultado = None
        self.title("Editar provedor" if provedor else "Adicionar provedor")
        self.configure(bg=BG)
        self.geometry("560x460")
        self.transient(pai)
        self.attributes("-topmost", True)
        self.columnconfigure(1, weight=1)

        self.funcoes = {v: k for k, v in C.FUNCOES.items()}
        self.v_funcao = tk.StringVar(value=C.FUNCOES[C.funcao_do(provedor)] if provedor
                                     else C.FUNCOES["traducao"])
        self.v_tipo = tk.StringVar()
        self.vars = {c: tk.StringVar() for c in C.CAMPOS}
        self.v_nome = tk.StringVar()
        self._nome_padrao = ""

        ttk.Label(self, text="Função").grid(row=0, column=0, sticky="w", padx=18, pady=(18, 4))
        self.cb_funcao = ttk.Combobox(self, textvariable=self.v_funcao, state="readonly",
                                      values=list(self.funcoes))
        self.cb_funcao.grid(row=0, column=1, sticky="ew", padx=(0, 18), pady=(18, 4))
        self.cb_funcao.bind("<<ComboboxSelected>>", lambda e: self.filtrar_tipos())
        ttk.Label(self, text="Tipo de serviço").grid(row=1, column=0, sticky="w", padx=18, pady=4)
        self.cb_tipo = ttk.Combobox(self, textvariable=self.v_tipo, state="readonly")
        self.cb_tipo.grid(row=1, column=1, sticky="ew", padx=(0, 18), pady=4)
        self.cb_tipo.bind("<<ComboboxSelected>>", lambda e: self.mudou_tipo())
        ttk.Label(self, text="Nome").grid(row=2, column=0, sticky="w", padx=18, pady=4)
        ttk.Entry(self, textvariable=self.v_nome).grid(row=2, column=1, sticky="ew", padx=(0, 18), pady=4)

        self.quadro = ttk.Frame(self)
        self.quadro.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=18)
        self.quadro.columnconfigure(1, weight=1)
        self.dica = ttk.Label(self, text="", style="Mudo.TLabel", wraplength=500, justify="left")
        self.dica.grid(row=4, column=0, columnspan=2, sticky="w", padx=18, pady=(8, 0))
        self.rowconfigure(5, weight=1)

        rod = ttk.Frame(self)
        rod.grid(row=6, column=0, columnspan=2, sticky="ew", padx=18, pady=18)
        ttk.Button(rod, text="OK", style="Acento.TButton", command=self.confirmar).pack(side="right")
        ttk.Button(rod, text="Cancelar", command=self.destroy).pack(side="right", padx=(0, 8))

        self.filtrar_tipos(inicial=provedor)
        self.wait_visibility()
        self.grab_set()

    def _tipos_da_funcao(self):
        f = self.funcoes[self.v_funcao.get()]
        return {info["nome"]: t for t, info in C.TIPOS.items() if info["funcao"] == f}

    def filtrar_tipos(self, inicial=None):
        tipos = self._tipos_da_funcao()
        self.cb_tipo["values"] = list(tipos)
        if inicial:
            self.cb_funcao.state(["disabled"])
            self.cb_tipo.state(["disabled"])
            self.v_tipo.set(C.TIPOS[inicial["tipo"]]["nome"])
            self.v_nome.set(inicial["nome"])
            self._nome_padrao = C.TIPOS[inicial["tipo"]]["nome"]
            self.montar_campos(inicial["tipo"], inicial)
        else:
            self.v_tipo.set(next(iter(tipos)))
            self.mudou_tipo()

    def mudou_tipo(self):
        tipo = self._tipos_da_funcao()[self.v_tipo.get()]
        info = C.TIPOS[tipo]
        if not self.v_nome.get() or self.v_nome.get() == self._nome_padrao:
            self.v_nome.set(info["nome"])
        self._nome_padrao = info["nome"]
        self.montar_campos(tipo, info["padrao"])

    def montar_campos(self, tipo, valores):
        for w in self.quadro.winfo_children():
            w.destroy()
        info = C.TIPOS[tipo]
        self.tipo_atual = tipo
        for i, campo in enumerate(info["campos"]):
            self.vars[campo].set(valores.get(campo, ""))
            rotulo = C.CAMPOS[campo] + (" *" if campo in info["obrig"] else "")
            ttk.Label(self.quadro, text=rotulo).grid(row=i, column=0, sticky="w", pady=4, padx=(0, 28))
            if campo == "chave":
                ent = ttk.Entry(self.quadro, textvariable=self.vars[campo], show="•")
                ent.grid(row=i, column=1, sticky="ew", pady=4)
                mostrar = tk.BooleanVar(value=False)
                ttk.Checkbutton(self.quadro, text="Mostrar", variable=mostrar,
                                command=lambda e=ent, m=mostrar: e.config(show="" if m.get() else "•")
                                ).grid(row=i, column=2, padx=(8, 0))
            else:
                ttk.Entry(self.quadro, textvariable=self.vars[campo]).grid(row=i, column=1, sticky="ew", pady=4)
        self.dica.config(text=info["dica"])

    def confirmar(self):
        info = C.TIPOS[self.tipo_atual]
        nome = self.v_nome.get().strip()
        if not nome:
            messagebox.showerror("Provedor", "Dê um nome ao provedor.", parent=self)
            return
        faltando = [C.CAMPOS[c] for c in info["obrig"] if not self.vars[c].get().strip()]
        if faltando:
            messagebox.showerror("Provedor", "Preencha: " + ", ".join(faltando) + ".", parent=self)
            return
        usados = {p["nome"] for p in C.lista_provedores(self.pai.cfg, info["funcao"])
                  if not self.original or p["id"] != self.original["id"]}
        base, n = nome, 2
        while nome in usados:
            nome, n = f"{base} ({n})", n + 1
        p = C.novo_provedor(self.tipo_atual, nome=nome)
        if self.original:
            p["id"] = self.original["id"]
        for campo in info["campos"]:
            p[campo] = self.vars[campo].get().strip()
        self.resultado = p
        self.destroy()
