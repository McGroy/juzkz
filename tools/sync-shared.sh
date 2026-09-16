#!/usr/bin/env bash
# Раскладывает общее ядро (shared/) по обоим сайтам.
#
# Зачем: каждый сайт должен быть самодостаточной папкой, которую можно
# просто залить на хостинг — без сборки и без общих путей между доменами.
# Источник правды при этом один: shared/. Правьте там, потом запускайте:
#
#   ./tools/sync-shared.sh
#
# Файлы, НЕ затрагиваемые синхронизацией (у каждого сайта свои):
#   assets/css/theme.css, assets/js/config.js, assets/js/brand.js
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

sites=(juz ortajuz)
copied=0

for site in "${sites[@]}"; do
  dest="$site/assets"
  [ -d "$dest" ] || { echo "пропускаю: нет $dest" >&2; continue; }

  mkdir -p "$dest/css" "$dest/js"
  cp shared/css/core.css        "$dest/css/core.css"
  cp shared/js/core.js          "$dest/js/core.js"
  cp shared/js/i18n.js          "$dest/js/i18n.js"
  cp shared/js/i18n-common.js   "$dest/js/i18n-common.js"
  copied=$((copied + 4))
  echo "  → $site/: core.css, core.js, i18n.js, i18n-common.js"
done

echo "Готово. Скопировано файлов: $copied"
