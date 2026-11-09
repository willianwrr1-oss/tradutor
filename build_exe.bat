@echo off
rem Gera dist\TradutorAudio\TradutorAudio.exe neste computador (precisa de Python 3.10+).
rem Alternativa sem instalar nada: use o GitHub Actions (veja o README).

python -m venv .venv || goto erro
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller || goto erro

pyinstaller --noconfirm --clean --windowed ^
  --name TradutorAudio ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all onnxruntime ^
  --collect-all av ^
  --collect-all tokenizers ^
  --hidden-import pyaudiowpatch ^
  tradutor_audio.py || goto erro

copy /Y tradutor_config.exemplo.json dist\TradutorAudio\ >nul
echo.
echo Pronto: dist\TradutorAudio\TradutorAudio.exe
goto fim

:erro
echo.
echo Algo deu errado. Veja as mensagens acima.
:fim
pause
