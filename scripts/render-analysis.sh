#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

Rscript -e "rmarkdown::render('analysis/table2.Rmd')"
Rscript -e "rmarkdown::render('analysis/stratified_ci_plot.Rmd')"
