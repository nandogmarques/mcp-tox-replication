# Threats to Validity


## Threat 01: Parâmetros de amostragem (`temperature`) não controlados

### Explicação

A `temperature` controla a aleatoriedade com que o modelo escolhe cada token da
resposta. Perto de 0, o modelo tende a escolher sempre o token mais provável e
a mesma entrada produz (quase) a mesma saída. Com o valor padrão dos provedores,
em geral 1, o sorteio segue a distribuição original e as respostas variam de uma
execução para outra.

Neste experimento o runner **não envia** `temperature` (nem outros parâmetros de
amostragem): cada modelo usa o seu padrão. Os motivos são:

- O artigo MCPTox e o repositório `MCPTox-Benchmark` não definem esses
  parâmetros. Não há valor "oficial" a reproduzir.
- Modelos de raciocínio, como o `gpt-5-mini`, só aceitam o valor padrão. Qualquer
  valor explícito é rejeitado com HTTP 400 (`Unsupported value: 'temperature'
  does not support 0 with this model`). A restrição é do modelo, e a Azure apenas
  a repete. A OpenAI não detalha o motivo; uma explicação plausível, mas não
  confirmada, é que esses modelos foram ajustados para operar com a amostragem
  padrão.

Versões anteriores do runner enviavam `temperature=0`. Essa foi uma escolha do
runner, não do artigo, e os dados já coletados em `data/reports/` foram gerados
com ela.

### Como se torna uma ameaça

- **Variância entre execuções.** Com a temperatura padrão, o mesmo caso pode ser
  `Success` numa execução e `Failure-Ignored` em outra. Um único resultado por
  caso e setting diz pouco sobre a taxa real de sucesso daquele caso.
- **Ruído no ASR e no Refused Ratio.** O ruído tende a se diluir nas médias com
  485 casos por modelo e setting, mas aumenta a incerteza das métricas por célula
  (modelo, setting e paradigma), onde as contagens são menores. Isso é mais grave
  para o Refused Ratio, cujas contagens são pequenas (dezenas de casos em milhares
  de execuções).
- **Comparação entre modelos.** Os modelos usam padrões diferentes e, nos de
  raciocínio, o valor não é ajustável. Diferenças de ASR entre modelos podem
  refletir, em parte, diferenças de amostragem e não só de robustez à
  *Tool Poisoning*.
- **Comparação com dados antigos.** Resultados coletados com `temperature=0` não
  são diretamente comparáveis com execuções novas sem esse parâmetro.
- **Comparação com o artigo.** Como o artigo não informa a amostragem usada,
  não é possível saber se as diferenças em relação aos valores publicados vêm do
  modelo, do prompt ou da amostragem.
- **Reprodutibilidade.** Mesmo com `temperature=0`, alguns provedores não são
  totalmente determinísticos (por exemplo, por paralelismo em GPU ou por mudanças
  silenciosas no modelo). Fixar o parâmetro reduz o problema, mas não o elimina.

### Possível mitigação

- **Repetições e intervalos de confiança.** Usar a amostra estratificada com
  várias repetições (`run_stratified_repeats.py`, 5 por padrão) e reportar o
  intervalo de confiança de Wilson por célula, além da média. Para métricas com
  poucas ocorrências, como o Refused Ratio, reportar também a contagem absoluta.
- **Mesma configuração para todos os modelos.** Não enviar parâmetros de
  amostragem para nenhum modelo, de modo que a única diferença seja a do padrão
  de cada provedor, e registrar essa decisão junto aos resultados.
- **Registrar o contexto de cada execução.** Guardar no `metadata.json` o modelo,
  o provedor, a data e a versão do runner, para que execuções com configurações
  diferentes (por exemplo, com e sem `temperature=0`) não sejam misturadas.
- **Separar os dados por configuração.** Tratar os dados antigos
  (`temperature=0`) como um conjunto à parte e não consolidá-los com os novos.
- **Análise de sensibilidade (opcional).** Para os modelos que aceitam o
  parâmetro, repetir uma amostra com `temperature=0` e comparar com a execução
  padrão, para estimar quanto a amostragem afeta o ASR. Isso exigiria reintroduzir
  uma flag opcional no runner, e não é possível para o `gpt-5-mini`.
- **Aceitar a limitação para modelos de raciocínio.** Nesses modelos, a
  reprodutibilidade só pode ser obtida por repetições e pela análise estatística,
  não por determinismo por chamada.
