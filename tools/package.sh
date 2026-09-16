#!/usr/bin/env bash
# Собирает по архиву на каждый сайт — то, что заливается на хостинг.
#
#   ./tools/package.sh
#
# На выходе:
#   dist/juz.zip       содержимое корня juz.kz
#   dist/ortajuz.zip   содержимое корня ortajuz.kz
#
# Внутри архива файлы лежат БЕЗ общей папки: распаковали — и сразу
# index.html, assets/, services/. Именно это ждёт файловый менеджер
# хостинга и большинство панелей управления.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

command -v zip >/dev/null || { echo "нужен zip: apt install zip" >&2; exit 1; }

# Сначала раскладываем общее ядро, чтобы в архив не уехала устаревшая копия
./tools/sync-shared.sh >/dev/null

mkdir -p dist
rm -f dist/juz.zip dist/ortajuz.zip

for site in juz ortajuz; do
  [ -d "$site" ] || { echo "нет папки $site" >&2; exit 1; }
  # README.md — инструкция для разработки, на хостинге он лежал бы
  # в открытом доступе по адресу вида example.kz/README.md
  ( cd "$site" && zip -qr "../dist/$site.zip" . -x 'README.md' '.DS_Store' '*/.DS_Store' )
  size=$(du -h "dist/$site.zip" | cut -f1)
  files=$(unzip -Z1 "dist/$site.zip" | grep -vc '/$')
  echo "dist/$site.zip — $files файлов, $size"
done

echo
echo "Залейте содержимое архива в корень домена:"
echo "  dist/juz.zip      → juz.kz"
echo "  dist/ortajuz.zip  → ortajuz.kz"
