# Tradutor de áudio para Windows → Português (Brasil)

Captura o áudio que está tocando no computador (alto-falante, fone com fio ou
Bluetooth, HDMI) e mostra a tradução para português do Brasil em uma janela,
quase em tempo real. Entende **espanhol, inglês e japonês**, com detecção
automática do idioma.

- Reconhecimento de fala: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), roda no próprio computador, sem custo.
- Captura: WASAPI loopback ([PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch)). Acompanha a troca do dispositivo de saída (plugar ou tirar o fone).
- Tradução: tenta em sequência Google Cloud (se houver chave), Google gratuito, Lingva e MyMemory, e troca sozinho quando um deles falha. Precisa de internet. Na versão Python também há a opção offline `--offline` (Argos Translate).

Funciona em qualquer notebook ou PC com Windows 10/11, de qualquer marca.

## Usar o programa pronto (.exe, sem instalar nada)

1. Baixe `TradutorAudio-windows.zip` na aba **Releases** deste repositório (ou como *artifact* em **Actions**).
2. Extraia a pasta completa (não rode de dentro do zip).
3. Abra `TradutorAudio.exe`.
4. Na primeira vez ele baixa o modelo de reconhecimento (~500 MB para o `small`) para a pasta `modelos`, ao lado do programa. Precisa de internet nessa hora.
5. Toque qualquer áudio no computador. A tradução aparece na janela depois de 2 a 5 segundos.

O Windows SmartScreen pode avisar sobre "aplicativo não reconhecido", porque o
programa não tem assinatura digital. Clique em *Mais informações → Executar assim mesmo*.

### Ajustes opcionais

Copie `tradutor_config.exemplo.json` para `tradutor_config.json` (na mesma pasta do `.exe`) e edite:

| Campo | Para que serve |
|---|---|
| `model` | `tiny`, `base`, `small` (padrão), `medium`, `large-v3`. Maior = mais preciso e mais lento. Se atrasar, use `base`. |
| `device` | `cpu` (padrão) ou `cuda` (placa NVIDIA). |
| `limiar` | Sensibilidade à voz. Diminua (ex.: `0.004`) se falas baixas não forem captadas. |
| `max_seg` | Duração máxima de cada trecho, em segundos. |
| `log` | Arquivo onde salvar original e tradução. |
| `google_api_key` | Chave do Google Cloud Translation (500 mil caracteres grátis por mês). É o jeito mais estável de traduzir. Opcional. |

Se algo travar na abertura, o motivo fica registrado em `erro.log`.

## Gerar o .exe você mesmo

**Pelo GitHub (não precisa instalar nada):**
1. Suba este projeto para um repositório seu.
2. Aba **Actions → Gerar .exe (Windows) → Run workflow**. Em alguns minutos o zip aparece em *Artifacts*.
3. Para publicar uma Release com o zip: crie uma tag, por exemplo `git tag v1.0.0 && git push --tags`.

**No seu computador:** com Python 3.10 ou mais novo, execute `build_exe.bat`. O resultado fica em `dist\TradutorAudio\`.

## Rodar pelo Python

```
pip install -r requirements.txt
python tradutor_audio.py
```

Opções: `--model base`, `--device cuda`, `--offline`, `--log saida.txt`, `--limiar 0.005`.
Para `--offline`, instale também `argostranslate` e os pacotes de idioma (es/en/ja → pt).

## Limitações

- O Google gratuito pode responder "too many requests" em redes compartilhadas (empresa, VPN). O programa usa os serviços de reserva, mas eles são menos precisos e têm limites diários. Para uso contínuo, configure `google_api_key`.
- O atraso de 2 a 5 segundos vem de esperar uma pausa na fala para fechar cada trecho.
- Música ou ruído de fundo podem gerar frases estranhas.
- Alguns players com proteção de cópia entregam áudio mudo ao loopback.
- Notebooks sem placa de vídeo dedicada podem não acompanhar o modelo `small` em tempo real. Use `base`.
- Só Windows (usa WASAPI).
