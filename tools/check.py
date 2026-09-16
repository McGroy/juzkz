#!/usr/bin/env python3
"""
Быстрая проверка обоих сайтов без внешних зависимостей.

  python3 tools/check.py

Что проверяет:
  * все внутренние ссылки ведут на существующие файлы;
  * все якоря (#id) существуют на целевой странице;
  * каждая страница подключает нужные скрипты и свой отдельный словарь;
  * один словарь не обслуживает несколько страниц;
  * общие файлы внутри сайтов совпадают с источником в shared/.
"""
import pathlib, sys, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITES = ("juz", "ortajuz")
SKIP = ("http://", "https://", "mailto:", "tel:", "data:", "#")

REQUIRED_SCRIPTS = ["config.js", "i18n-common.js", "i18n-brand.js", "i18n.js", "core.js"]

# Слева — источник правды, справа — путь внутри каждого сайта
SHARED = {
    "shared/css/core.css": "assets/css/core.css",
    "shared/js/core.js": "assets/js/core.js",
    "shared/js/i18n.js": "assets/js/i18n.js",
    "shared/js/i18n-common.js": "assets/js/i18n-common.js",
}

problems = []
page_dicts = {}


def report(page, message):
    problems.append(f"{page.relative_to(ROOT)}: {message}")


def check_links(site_root, page):
    html = page.read_text()
    for _attr, value in re.findall(r'(href|src)="([^"]+)"', html):
        if value.startswith(SKIP):
            continue
        path, _, anchor = value.partition("#")
        if not path:
            continue
        target = site_root / path.lstrip("/") if value.startswith("/") else page.parent / path
        target = target.resolve()
        if not target.exists():
            report(page, f"битая ссылка {value}")
        elif anchor and target.suffix == ".html" and f'id="{anchor}"' not in target.read_text():
            report(page, f"нет якоря #{anchor} в {path}")


def check_scripts(site, site_root, page):
    html = page.read_text()
    for name in REQUIRED_SCRIPTS:
        if f"assets/js/{name}" not in html:
            report(page, f"не подключён {name}")

    # У страницы должен быть ровно один собственный словарь
    dicts = set(re.findall(r'assets/js/(i18n-(?!common|brand)[a-z0-9-]+\.js)', html))
    if len(dicts) != 1:
        report(page, f"ожидался один словарь страницы, найдено: {sorted(dicts) or 'ни одного'}")
        return
    name = dicts.pop()
    if not (site_root / "assets/js" / name).exists():
        report(page, f"словарь {name} не существует")
    page_dicts.setdefault((site, name), []).append(page)


def check_dict_sharing():
    """Один словарь на две страницы — тоже ошибка: meta.title чужой страницы
       подменит заголовок вкладки при переключении языка."""
    for (site, name), pages in sorted(page_dicts.items()):
        if len(pages) > 1:
            where = ", ".join(str(p.relative_to(ROOT / site)) for p in pages)
            problems.append(f"{site}/assets/js/{name}: один словарь на несколько страниц ({where})")


def check_shared():
    for src, dst in SHARED.items():
        origin = (ROOT / src).read_text()
        for site in SITES:
            copy = ROOT / site / dst
            if not copy.exists():
                problems.append(f"{site}/{dst}: файл отсутствует")
            elif copy.read_text() != origin:
                problems.append(f"{site}/{dst}: расходится с {src} — запустите tools/sync-shared.sh")


def main():
    pages = 0
    for site in SITES:
        site_root = ROOT / site
        if not site_root.is_dir():
            problems.append(f"{site}/: папка сайта не найдена")
            continue
        for page in sorted(site_root.rglob("*.html")):
            pages += 1
            check_links(site_root, page)
            check_scripts(site, site_root, page)
    check_dict_sharing()
    check_shared()

    if problems:
        print(f"Найдено проблем: {len(problems)}\n")
        for p in problems:
            print("  ✗", p)
        return 1
    print(f"Проверено страниц: {pages}. Проблем не найдено.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
