# MCPTox replication

Reprodução adaptada do benchmark MCPTox para `gpt-4o-mini`,
`gemini-2.5-flash` e `deepseek-v4-flash`, usando Kubernetes, FastMCP e
Envoy AI Gateway. O experimento avalia as chamadas produzidas pelos modelos,
mas não executa as ações maliciosas.

## Conteúdo

```text
.
├── analysis/
│   ├── stratified_ci_plot.Rmd
│   └── table2.Rmd
├── data/reports/
│   ├── full-benchmark/
│   └── stratified-repeats-k30-r5/
├── manifests/
├── mcptox-k8s/
│   ├── analysis/
│   ├── k8s/
│   ├── tests/
│   ├── wrapper/
│   ├── rerun_invalid_results.py
│   ├── run_experiment.py
│   └── run_stratified_repeats.py
└── scripts/
```

O benchmark oficial não é duplicado neste repositório. Clone-o ao lado de
`mcptox-k8s`:

```bash
git clone https://github.com/zhiqiangwang4/MCPTox-Benchmark.git
```

## Credenciais dos modelos

Os manifests usam variáveis de ambiente e devem ser processados com
`envsubst`. Nenhuma chave real deve ser gravada no Git.

```bash
cp .env.example .env
# Edite .env com suas credenciais.
set -a
source .env
set +a
./scripts/apply-model-manifests.sh
```

Variáveis exigidas:

- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `DEEPSEEK_API_KEY`

O script renderiza os manifests em um diretório temporário, aplica-os com
`kubectl` e remove os arquivos renderizados ao terminar.

## Ambiente

Pré-requisitos:

- Python 3.11 ou superior;
- Docker e um cluster Kubernetes;
- `kubectl`, Helm, Kind e `envsubst`;
- Envoy AI Gateway com suporte à CRD `MCPRoute`;
- R com os pacotes `rmarkdown`, `jsonlite` e `knitr`.

Os manifests `redis.yaml` e `inferencepool-role.yaml`, bem como os manifests
dos três provedores, estão em `manifests/`. A implantação do MCP Wrapper está
em `mcptox-k8s/k8s/`.

O procedimento completo, incluindo a instalação das dependências, criação do
cluster Kind, implantação do Envoy AI Gateway, configuração dos modelos e
teste das rotas, está em
[`docs/montagem-ambiente.md`](docs/montagem-ambiente.md).

## Execução do benchmark completo

Defina o endereço local do Envoy AI Gateway:

```bash
export GATEWAY_URL=http://localhost:8080
```

Execute os 485 casos, nas três configurações de apresentação, para os três
modelos:

```bash
python3 mcptox-k8s/run_experiment.py \
  --all \
  --model gpt-4o-mini gemini-2.5-flash deepseek-v4-flash \
  --setting base enhanced-important enhanced-ignore \
  --output-dir mcptox-k8s/reports/full-benchmark
```

## Amostra estratificada com repetições

O experimento estatístico seleciona 30 casos por paradigma, com `seed=42`,
e executa cinco repetições:

```bash
python3 mcptox-k8s/run_stratified_repeats.py \
  --k 30 \
  --repetitions 5 \
  --seed 42 \
  --output-dir mcptox-k8s/reports/stratified-repeats-k30-r5
```

Para reexecutar somente resultados `None` ou `Error`:

```bash
python3 mcptox-k8s/rerun_invalid_results.py \
  --input mcptox-k8s/reports/stratified-repeats-k30-r5/consolidated_results.csv \
  --output mcptox-k8s/reports/stratified-repeats-k30-r5/consolidated_results_patched.csv \
  --output-dir mcptox-k8s/reports/stratified-repeats-k30-r5/invalid-reruns
```

Para gerar as estatísticas:

```bash
python3 mcptox-k8s/analysis/statistical_analysis.py \
  --input mcptox-k8s/reports/stratified-repeats-k30-r5/consolidated_results_patched.csv \
  --output-dir mcptox-k8s/reports/stratified-repeats-k30-r5/stats-patched
```

## Dados incluídos

Os artefatos utilizados no artigo estão em:

- `data/reports/full-benchmark`: resultados consolidados das 4.365 unidades
  experimentais do benchmark completo;
- `data/reports/stratified-repeats-k30-r5`: seleção estratificada,
  resultados brutos das repetições, arquivo consolidado corrigido e tabelas
  estatísticas.

Esses diretórios são somente leitura para as análises. Novas execuções devem
ser gravadas em `mcptox-k8s/reports/`.

## R Markdown

Os documentos em `analysis/` transformam os resultados consolidados em tabelas
e figuras utilizadas no artigo. Eles não executam os modelos nem modificam a
classificação das respostas.

### Tabela do benchmark completo

O arquivo `analysis/table2.Rmd` lê `results.csv` ou `results.json` de
`data/reports/full-benchmark/`. Ele verifica a cobertura dos casos, exclui os
rótulos `None` e `Error` do denominador e calcula a ASR por modelo, paradigma e
configuração de apresentação. Como saída, gera:

- `table2.png`, para inspeção visual;
- `table2.tex`, com a tabela pronta para inclusão no Overleaf;
- `table2.md`, relatório produzido pelo `rmarkdown`.

Os principais parâmetros são `report_dir`, `expected_cases_per_model`,
`strict_full_benchmark`, `models`, `drop_models_without_valid_outputs`,
`table_image_path` e `table_tex_path`.

### Intervalos de confiança

O arquivo `analysis/stratified_ci_plot.Rmd` lê por padrão
`data/reports/stratified-repeats-k30-r5/consolidated_results_patched.csv`. O
documento agrega as repetições por modelo, paradigma e configuração, calcula a
ASR e seus intervalos de confiança de 95\% pelo método de Wilson e gera duas
visualizações: uma comparação geral e outra separada por configuração. As
saídas padrão são:

- `stratified_asr_ci.png`;
- `stratified_asr_ci_by_setting.png`;
- `stratified_asr_ci_figure.tex`;
- `stratified_asr_ci_by_setting_figure.tex`;
- `stratified_ci_plot.md`.

Seus parâmetros são `report_dir`, `consolidated_path`, `image_path` e
`tex_path`. Os caminhos das versões separadas por configuração são derivados
automaticamente de `report_dir`.

### Renderização

Instale previamente os pacotes necessários:

```bash
Rscript -e "install.packages(c('rmarkdown', 'jsonlite', 'knitr'))"
```

Para renderizar os dois documentos com os dados versionados:

```bash
./scripts/render-analysis.sh
```

Para analisar uma execução diferente, informe os parâmetros diretamente. Como
os documentos são executados a partir de `analysis/`, caminhos relativos devem
ser definidos a partir desse diretório:

```bash
Rscript -e "rmarkdown::render(\
  'analysis/table2.Rmd', \
  params=list(report_dir='../mcptox-k8s/reports/full-benchmark'))"

Rscript -e "rmarkdown::render(\
  'analysis/stratified_ci_plot.Rmd', \
  params=list(\
    report_dir='../mcptox-k8s/reports/stratified-repeats-k30-r5', \
    consolidated_path='../mcptox-k8s/reports/stratified-repeats-k30-r5/consolidated_results_patched.csv'))"
```

## Validação

```bash
python3 -m unittest discover -s mcptox-k8s/tests -v
python3 -m py_compile \
  mcptox-k8s/run_experiment.py \
  mcptox-k8s/run_stratified_repeats.py \
  mcptox-k8s/rerun_invalid_results.py \
  mcptox-k8s/analysis/statistical_analysis.py \
  mcptox-k8s/wrapper/app.py
```

Referências:

- [artigo MCPTox](https://arxiv.org/abs/2508.14925);
- [benchmark oficial](https://github.com/zhiqiangwang4/MCPTox-Benchmark);
- [MCP Gateway do Envoy AI Gateway](https://aigateway.envoyproxy.io/docs/capabilities/mcp/).
