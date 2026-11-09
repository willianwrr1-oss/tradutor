"""
Tradutor de áudio do Windows -> Português (Brasil)

Captura o que está tocando no computador (alto-falante, fone com fio, Bluetooth,
HDMI...) via WASAPI loopback, transcreve (Whisper local ou API) e mostra a
tradução em tempo quase real. Idiomas de origem: espanhol, inglês e japonês.

Uso:
    python tradutor_audio.py
    python tradutor_audio.py --model base      # modelo local mais rápido
    python tradutor_audio.py --device cuda     # placa NVIDIA
    python tradutor_audio.py --offline         # tradução offline (Argos)
    python tradutor_audio.py --log saida.txt   # grava original e tradução

Provedores de API, modelo e demais ajustes ficam em Configurações (⚙).
"""
import argparse
import os
import sys
import traceback

# No .exe sem console, stdout/stderr são None e bibliotecas que escrevem
# barras de progresso (download do modelo) quebrariam. Redireciona para o nada.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import configuracao as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Tradutor de áudio do Windows para PT-BR")
    ap.add_argument("--model", help="tiny, base, small, medium, large-v3 (padrão: small)")
    ap.add_argument("--device", choices=["cpu", "cuda"])
    ap.add_argument("--offline", action="store_true", help="usa Argos Translate (só na versão Python)")
    ap.add_argument("--log", help="arquivo para salvar original e tradução")
    ap.add_argument("--pasta-modelos", help="onde guardar os modelos baixados (padrão: pasta 'modelos')")
    args = ap.parse_args()

    cfg = C.carregar()
    if args.model:
        cfg["model"] = args.model
    if args.device:
        cfg["device"] = args.device
    if args.offline:
        cfg["offline"] = True
    if args.log:
        cfg["log"] = args.log
    if args.pasta_modelos:
        cfg["pasta_modelos"] = args.pasta_modelos

    try:  # nitidez em telas com escala acima de 100% (comum em notebooks)
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    try:
        from interface import App

        App(cfg).rodar()
    except Exception:
        (C.PASTA_APP / "erro.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
