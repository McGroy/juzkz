/* ==========================================================================
   i18n.js — переключение языков без сборки и без перезагрузки страницы.

   Как это работает
   ----------------
   1. В разметке любой переводимый узел помечается атрибутом:
        <h2 data-i18n="services.title">Услуги</h2>          -> заменяет textContent
        <p  data-i18n-html="hero.lead">...</p>              -> заменяет innerHTML (для строк с разметкой)
        <input data-i18n-attr="placeholder:form.namePh">    -> заменяет атрибут(ы)
      Несколько атрибутов разделяются точкой с запятой:
        data-i18n-attr="placeholder:form.namePh;aria-label:form.name"

   2. Словари складываются из трёх источников, по возрастанию приоритета:
        window.I18N_COMMON — строки, общие для обоих сайтов (шапка, подвал, форма)
        window.I18N_BRAND  — строки конкретного бренда (i18n-brand.js)
        window.I18N_PAGE   — строки конкретной страницы (i18n-<страница>.js)

   3. Русский — базовый язык: он уже записан в HTML, поэтому при ru
      переводы не применяются вовсе (нет мигания и не нужен дубль контента).

   Выбор языка запоминается в localStorage и читается из ?lang=kk.
   ========================================================================== */
(function () {
  "use strict";

  var LANGS = ["ru", "kk", "en"];
  var BASE = "ru";
  var KEY = "juz:lang";

  /* ---- Хранилище может быть недоступно (приватный режим, блокировка) ---- */
  function readStore() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function writeStore(v) {
    try { localStorage.setItem(KEY, v); } catch (e) { /* не критично */ }
  }

  function normalize(lang) {
    if (!lang) return null;
    lang = String(lang).toLowerCase().slice(0, 2);
    if (lang === "kz") lang = "kk";          // частая ошибка в ссылках
    return LANGS.indexOf(lang) !== -1 ? lang : null;
  }

  /* Приоритет: ?lang= → сохранённый выбор → русский.

     Язык браузера НЕ учитывается по умолчанию: сайт рассчитан на рынок
     Казахстана, и посетитель с англоязычной локалью браузера почти всегда
     ожидает увидеть русскую версию. Если автоопределение всё же нужно,
     поставьте в config.js:  autoDetectLang: true */
  function detect() {
    var q = null;
    try {
      q = normalize(new URLSearchParams(location.search).get("lang"));
    } catch (e) { /* старый браузер */ }
    if (q) return q;

    var saved = normalize(readStore());
    if (saved) return saved;

    if (window.SITE && window.SITE.autoDetectLang) {
      var navLangs = navigator.languages || [navigator.language];
      for (var i = 0; i < navLangs.length; i++) {
        var n = normalize(navLangs[i]);
        if (n) return n;
      }
    }
    return BASE;
  }

  /* Достаёт "a.b.c" из вложенного объекта */
  function lookup(dict, path) {
    if (!dict) return undefined;
    var parts = path.split(".");
    var cur = dict;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null || typeof cur !== "object") return undefined;
      cur = cur[parts[i]];
    }
    return typeof cur === "string" ? cur : undefined;
  }

  function translate(path, lang) {
    var v = lookup(window.I18N_PAGE && window.I18N_PAGE[lang], path);
    if (v === undefined) v = lookup(window.I18N_BRAND && window.I18N_BRAND[lang], path);
    if (v === undefined) v = lookup(window.I18N_COMMON && window.I18N_COMMON[lang], path);
    return v;
  }

  /* Русские строки живут прямо в HTML — запоминаем их при первом проходе,
     чтобы возврат на ru не требовал словаря. */
  var originals = new WeakMap();

  function remember(el, kind, value) {
    var store = originals.get(el);
    if (!store) { store = {}; originals.set(el, store); }
    if (!(kind in store)) store[kind] = value;
    return store[kind];
  }

  function applyTo(root, lang) {
    var isBase = lang === BASE;

    root.querySelectorAll("[data-i18n]").forEach(function (el) {
      var base = remember(el, "text", el.textContent);
      var v = isBase ? base : translate(el.getAttribute("data-i18n"), lang);
      if (v !== undefined) el.textContent = v;
    });

    root.querySelectorAll("[data-i18n-html]").forEach(function (el) {
      var base = remember(el, "html", el.innerHTML);
      var v = isBase ? base : translate(el.getAttribute("data-i18n-html"), lang);
      if (v !== undefined) el.innerHTML = v;
    });

    root.querySelectorAll("[data-i18n-attr]").forEach(function (el) {
      el.getAttribute("data-i18n-attr").split(";").forEach(function (pair) {
        pair = pair.trim();
        if (!pair) return;
        var sep = pair.indexOf(":");
        if (sep === -1) return;
        var attr = pair.slice(0, sep).trim();
        var key = pair.slice(sep + 1).trim();
        var base = remember(el, "attr:" + attr, el.getAttribute(attr) || "");
        var v = isBase ? base : translate(key, lang);
        if (v !== undefined) el.setAttribute(attr, v);
      });
    });
  }

  function applyMeta(lang) {
    document.documentElement.lang = lang;

    var title = translate("meta.title", lang);
    if (title !== undefined) document.title = title;

    var desc = translate("meta.description", lang);
    if (desc !== undefined) {
      var m = document.querySelector('meta[name="description"]');
      if (m) m.setAttribute("content", desc);
      var og = document.querySelector('meta[property="og:description"]');
      if (og) og.setAttribute("content", desc);
    }
    if (title !== undefined) {
      var ogt = document.querySelector('meta[property="og:title"]');
      if (ogt) ogt.setAttribute("content", title);
    }
  }

  var current = BASE;

  function set(lang, opts) {
    lang = normalize(lang) || BASE;
    current = lang;

    // Базовые строки нужно снять со страницы до первой подмены,
    // поэтому на не-русском первый проход всё равно кэширует оригиналы.
    applyTo(document, lang);
    applyMeta(lang);

    document.querySelectorAll("[data-lang-btn]").forEach(function (btn) {
      btn.setAttribute("aria-pressed", String(btn.getAttribute("data-lang-btn") === lang));
    });

    if (!opts || opts.persist !== false) writeStore(lang);

    document.dispatchEvent(new CustomEvent("i18n:change", { detail: { lang: lang } }));
  }

  function init() {
    var initial = detect();

    document.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-lang-btn]");
      if (!btn) return;
      e.preventDefault();
      set(btn.getAttribute("data-lang-btn"));
    });

    set(initial, { persist: false });
  }

  window.I18N = {
    set: set,
    get: function () { return current; },
    t: function (path) { return translate(path, current); },
    /* Для контента, отрисованного скриптом после загрузки */
    apply: function (root) { applyTo(root || document, current); },
    langs: LANGS
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
