# Tradutor de áudio para Windows → Português (Brasil)

Captura o áudio que está tocando no computador (alto-falante, fone com fio ou
Bluetooth, HDMI) e mostra a tradução para português do Brasil em uma janela,
quase em tempo real. Entende **espanhol, inglês e japonês**, com detecção
automática do idioma. Funciona em qualquer notebook ou PC com Windows 10/11.

- **Captura:** WASAPI loopback ([PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch)). Acompanha a troca do dispositivo de saída (plugar ou tirar o fone).
- **Reconhecimento de fala:** Whisper local ([faster-whisper](https://github.com/SYSTRAN/faster-whisper), sem custo) ou uma API de transcrição à sua escolha.
- **Tradução:** Google, Lingva e MyMemory (gratuitos) ou as APIs que você adicionar: Google Cloud, DeepL, Azure, LibreTranslate, Claude e qualquer modelo de linguagem compatível com OpenAI.

## Usar o programa pronto (.exe, sem instalar nada)

1. Baixe `TradutorAudio-windows.zip` na aba **Releases** deste repositório (ou como *artifact* em **Actions**).
2. Extraia a pasta completa (não rode de dentro do zip).
3. Abra `TradutorAudio.exe`.
4. Na primeira vez ele baixa o modelo do Whisper (~500 MB para o `small`) para a pasta `modelos`, ao lado do programa. Precisa de internet nessa hora.
5. Toque qualquer áudio no computador. A tradução aparece na janela depois de alguns segundos.

O Windows SmartScreen pode avisar sobre "aplicativo não reconhecido", porque o
programa não tem assinatura digital. Clique em *Mais informações → Executar assim mesmo*.

## A janela

| Controle | Para que serve |
|---|---|
| Idioma de origem | Automático, Espanhol, Inglês ou Japonês. Fixar o idioma evita erros de detecção. |
| Reconhecimento de fala | Whisper local ou uma API de transcrição que você tenha adicionado. |
| Tradução | "Automático" tenta os serviços em sequência. Ou fixe um serviço específico. |
| Pausar / Retomar | Interrompe a captura. |
| Mostrar original | Exibe o texto reconhecido acima da tradução. |
| A− / A+ | Tamanho da letra. |
| Legenda | Modo compacto e levemente transparente, só com a tradução, ideal sobre vídeos. Para sair: duplo clique no texto ou tecla Esc. |
| Copiar / Exportar | Copia ou salva em `.txt` tudo o que foi traduzido na sessão. |
| ⚙ Configurações | Provedores de API e ajustes de desempenho. |

O indicador no topo mostra o estado (capturando, pausado, erro) e o nível do áudio
captado. A barra inferior mostra o dispositivo em uso e quanto tempo cada etapa
levou no último trecho.

## Adicionar uma API

Em **⚙ Configurações → Provedores de API → Adicionar…**, escolha a função, o tipo de
serviço e preencha os campos. O botão **Testar** confirma que a chave funciona.
Depois, selecione o serviço nas listas da janela principal.

| Tipo | Função | Observações |
|---|---|---|
| Google Cloud Translation | Tradução | 500 mil caracteres grátis por mês. |
| DeepL | Tradução | Chaves terminadas em `:fx` usam a API gratuita automaticamente. |
| Microsoft Azure Translator | Tradução | Informe a região do recurso. |
| LibreTranslate | Tradução | Servidor próprio ou público. |
| Modelo de linguagem (compatível com OpenAI) | Tradução | OpenAI, Groq, OpenRouter, LM Studio, Ollama etc. O modelo recebe a frase anterior como contexto. |
| Claude (Anthropic) | Tradução | Um modelo menor responde mais rápido. |
| Transcrição (compatível com OpenAI) | Reconhecimento de fala | OpenAI, Groq e outros com `/audio/transcriptions`. Modelos `whisper-*` informam o idioma detectado. |

Quando um serviço falha (limite, erro de rede), o programa passa para o próximo e
volta a tentar o primeiro depois de um tempo. Se escolher um serviço específico e
quiser que ele nunca seja substituído, desmarque "Reserva automática" em
*Áudio e desempenho*.

> **Segurança:** as chaves ficam em texto simples no arquivo `tradutor_config.json`,
> ao lado do `.exe`. Não compartilhe esse arquivo nem o suba para o GitHub (ele já
> está no `.gitignore`). Se a pasta estiver sincronizada (OneDrive, por exemplo), a
> chave também será sincronizada.

## Desempenho e atraso

O atraso de 2 a 6 segundos vem de três etapas: esperar uma pausa na fala para fechar
o trecho, reconhecer a fala e traduzir. Em **Áudio e desempenho**:

- diminua *Duração máxima do trecho* e *Pausa que fecha um trecho* para reduzir o atraso (as frases ficam mais cortadas);
- use o modelo `base` no lugar do `small` se o notebook não acompanhar, ou uma API de transcrição;
- *Sensibilidade à voz*: diminua se falas baixas não forem captadas.

Se algo travar na abertura, o motivo fica registrado em `erro.log`.

## Gerar o .exe você mesmo

**Pelo GitHub (não precisa instalar nada):**
1. Suba este projeto para um repositório seu.
2. O fluxo **Gerar .exe (Windows)** roda sozinho a cada envio para a branch `main` (ou manualmente em **Actions → Run workflow**). O zip fica em *Artifacts*.
3. Para publicar uma Release com o zip: `git tag v1.0.0 && git push --tags`.

**No seu computador:** com Python 3.10 ou mais novo, execute `build_exe.bat`. O resultado fica em `dist\TradutorAudio\`.

## Rodar pelo Python

```
pip install -r requirements.txt
python tradutor_audio.py
```

Opções: `--model base`, `--device cuda`, `--offline`, `--log saida.txt`.
Para `--offline`, instale também `argostranslate` e os pacotes de idioma (es/en/ja → pt).

## Estrutura

| Arquivo | Conteúdo |
|---|---|
| `tradutor_audio.py` | Ponto de entrada. |
| `interface.py` | Janela principal, configurações e tema. |
| `provedores.py` | Serviços de tradução e de reconhecimento de fala. |
| `captura.py` | Captura do áudio e divisão em trechos. |
| `processamento.py` | Fluxo áudio → texto → tradução. |
| `configuracao.py` | Leitura e gravação das configurações e catálogo de provedores. |

## Limitações

- Música ou ruído de fundo podem gerar frases estranhas.
- O Google gratuito pode recusar pedidos ("too many requests") em redes compartilhadas ou VPN. Os serviços gratuitos de reserva têm limites diários. Para uso contínuo, adicione uma API.
- Alguns players com proteção de cópia entregam áudio mudo ao loopback.
- Só Windows (usa WASAPI).
