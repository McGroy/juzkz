#!/usr/bin/env python3
"""
Быстрая проверка обоих сайтов без внешних зависимостей.

  python3 tools/check.py

Что проверяет:
  * все внутренние ссылки ведут на существующие файлы;
  * все якоря (#id) существуют на целевой странице;
  * каждая страница подключает нужные скрипты и свой отдельный словарь;
  * общие файлы в sites/ совпадают с источником в shared/.
"""
import pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITES = ROOT / "sites"
SKIP = ("http://", "https://", "mailto:", "tel:", "data:", "#")

REQUIRED_SCRIPTS = ["config.js", "i18n-common.js", "i18n-brand.js", "i18n.js", "core.js"]
SHARED = {
    "shared/css/core.css": "assets/css/core.css",
    "shared/js/core.js": "assets/js/core.js",
    "shared/js/i18n.js": "assets/js/i18n.js",
    "shared/js/i18n-common.js": "assets/js/i18n-common.js",
}

problems = []


def report(page, message):
    problems.append(f"{page}: {message}")


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
            report(page.relative_to(ROOT), f"битая ссылка {value}")
        elif anchor and target.suffix == ".html" and f'id="{anchor}"' not in target.read_text():
            report(page.relative_to(ROOT), f"нет якоря #{anchor} в {path}")


page_dicts = {}


def check_scripts(page):
    html = page.read_text()
    for name in REQUIRED_SCRIPTS:
        if f"assets/js/{name}" not in html:
            report(page.relative_to(ROOT), f"не подключён {name}")
    # У страницы должен быть ровно один собственный словарь
    dicts = set(re.findall(r'assets/js/(i18n-(?!common|brand)[a-z0-9-]+\.js)', html))
    if len(dicts) != 1:
        report(page.relative_to(ROOT), f"ожидался один словарь страницы, найдено: {sorted(dicts) or 'ни одного'}")
    else:
        d = dicts.pop()
        site = page.relative_to(SITES).parts[0]
        if not (SITES / site / "assets/js" / d).exists():
            report(page.relative_to(ROOT), f"словарь {d} не существует")
        page_dicts.setdefault((site, d), []).append(page)


def check_dict_sharing():
    """Два словаря на одну страницу — ошибка, но и один словарь на две
       страницы тоже: meta.title из чужой страницы подменит заголовок
       вкладки при переключении языка."""
    for (site, d), pages in sorted(page_dicts.items()):
        if len(pages) > 1:
            names = ", ".join(str(p.relative_to(SITES / site)) for p in pages)
            problems.append(f"sites/{site}/assets/js/{d}: один словарь на несколько страниц ({names})")


def check_shared():
    for src, dst in SHARED.items():
        origin = (ROOT / src).read_text()
        for site in sorted(p.name for p in SITES.iterdir() if p.is_dir()):
            copy = SITES / site / dst
            if not copy.exists():
                problems.append(f"sites/{site}/{dst}: файл отсутствует")
            elif copy.read_text() != origin:
                problems.append(
                    f"sites/{site}/{dst}: расходится с {src} — запустите tools/sync-shared.sh")


def main():
    pages = 0
    for site in sorted(p for p in SITES.iterdir() if p.is_dir()):
        for page in sorted(site.rglob("*.html")):
            pages += 1
            check_links(site, page)
            check_scripts(page)
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
