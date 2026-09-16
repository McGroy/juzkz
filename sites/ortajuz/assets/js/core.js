/* ==========================================================================
   core.js — весь интерактив сайта. Без зависимостей.
   Каждый модуль самостоятельно проверяет наличие своей разметки,
   поэтому файл безопасно подключать на любой странице.
   ========================================================================== */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $  = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  /* ------------------------------------------------------------------
     Шапка: фон появляется после прокрутки
     ------------------------------------------------------------------ */
  function initHeader() {
    var header = $(".header");
    if (!header) return;

    var ticking = false;
    function update() {
      header.classList.toggle("is-stuck", window.scrollY > 12);
      ticking = false;
    }
    window.addEventListener("scroll", function () {
      if (!ticking) { ticking = true; requestAnimationFrame(update); }
    }, { passive: true });
    update();
  }

  /* ------------------------------------------------------------------
     Мобильное меню
     ------------------------------------------------------------------ */
  function initNav() {
    var burger = $(".burger");
    var nav = $(".nav");
    if (!burger || !nav) return;

    function close() {
      document.body.classList.remove("nav-open");
      burger.setAttribute("aria-expanded", "false");
    }

    burger.addEventListener("click", function () {
      var open = document.body.classList.toggle("nav-open");
      burger.setAttribute("aria-expanded", String(open));
    });

    // Клик по пункту меню закрывает его
    nav.addEventListener("click", function (e) {
      if (e.target.closest("a")) close();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });

    // При переходе на десктоп состояние сбрасываем
    window.matchMedia("(min-width: 1041px)").addEventListener("change", close);
  }

  /* ------------------------------------------------------------------
     Появление блоков при прокрутке
     ------------------------------------------------------------------ */
  function initReveal() {
    var items = $$("[data-reveal]");
    if (!items.length) return;

    if (reduceMotion || !("IntersectionObserver" in window)) {
      items.forEach(function (el) { el.classList.add("is-visible"); });
      return;
    }

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        io.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });

    items.forEach(function (el) {
      // Каскад внутри одной группы: data-reveal-group на родителе
      var parent = el.parentElement;
      if (parent && parent.hasAttribute("data-reveal-group")) {
        var idx = Array.prototype.indexOf.call(parent.children, el);
        el.style.setProperty("--reveal-delay", Math.min(idx, 6) * 70 + "ms");
      }
      io.observe(el);
    });

    /* Подстраховка: при заходе по якорю или очень быстрой прокрутке часть
       блоков может ни разу не пересечь вьюпорт. Показываем всё, что уже
       оказалось выше нижней границы экрана. */
    setTimeout(function () {
      items.forEach(function (el) {
        if (el.classList.contains("is-visible")) return;
        if (el.getBoundingClientRect().top < window.innerHeight) {
          el.classList.add("is-visible");
          io.unobserve(el);
        }
      });
    }, 900);
  }

  /* ------------------------------------------------------------------
     Счётчики в блоке метрик
     ------------------------------------------------------------------ */
  function initCounters() {
    var nodes = $$("[data-count]");
    if (!nodes.length) return;

    function run(el) {
      var target = parseFloat(el.getAttribute("data-count"));
      if (isNaN(target)) return;
      var decimals = (el.getAttribute("data-count").split(".")[1] || "").length;
      var prefix = el.getAttribute("data-count-prefix") || "";
      var suffix = el.getAttribute("data-count-suffix") || "";

      if (reduceMotion) {
        el.textContent = prefix + target.toFixed(decimals) + suffix;
        return;
      }

      var start = null;
      var dur = 1500;
      function frame(ts) {
        if (start === null) start = ts;
        var p = Math.min((ts - start) / dur, 1);
        var eased = 1 - Math.pow(1 - p, 3);          // easeOutCubic
        el.textContent = prefix + (target * eased).toFixed(decimals) + suffix;
        if (p < 1) requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    }

    if (!("IntersectionObserver" in window)) { nodes.forEach(run); return; }

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        run(entry.target);
        io.unobserve(entry.target);
      });
    }, { threshold: 0.5 });

    nodes.forEach(function (el) { io.observe(el); });
  }

  /* ------------------------------------------------------------------
     Подсветка карточек за курсором
     ------------------------------------------------------------------ */
  function initCardGlow() {
    var cards = $$(".card--glow");
    if (!cards.length || reduceMotion) return;
    if (window.matchMedia("(hover: none)").matches) return;

    cards.forEach(function (card) {
      card.addEventListener("pointermove", function (e) {
        var r = card.getBoundingClientRect();
        card.style.setProperty("--mx", (e.clientX - r.left) + "px");
        card.style.setProperty("--my", (e.clientY - r.top) + "px");
      });
    });
  }

  /* ------------------------------------------------------------------
     Табы
     ------------------------------------------------------------------ */
  function initTabs() {
    $$("[data-tabs]").forEach(function (root) {
      var btns = $$("[role=tab]", root);
      var panels = $$("[role=tabpanel]", root);
      if (!btns.length) return;

      function select(idx) {
        btns.forEach(function (b, i) {
          b.setAttribute("aria-selected", String(i === idx));
          b.tabIndex = i === idx ? 0 : -1;
        });
        panels.forEach(function (p, i) { p.hidden = i !== idx; });
      }

      btns.forEach(function (btn, i) {
        btn.addEventListener("click", function () { select(i); });
        btn.addEventListener("keydown", function (e) {
          var dir = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
          if (!dir) return;
          e.preventDefault();
          var next = (i + dir + btns.length) % btns.length;
          select(next);
          btns[next].focus();
        });
      });

      select(0);
    });
  }

  /* ------------------------------------------------------------------
     Аккордеон
     ------------------------------------------------------------------ */
  function initAccordion() {
    $$("[data-acc]").forEach(function (root) {
      var single = root.getAttribute("data-acc") === "single";
      var btns = $$(".acc__btn", root);

      btns.forEach(function (btn) {
        var panel = document.getElementById(btn.getAttribute("aria-controls"));
        if (!panel) return;

        btn.addEventListener("click", function () {
          var open = btn.getAttribute("aria-expanded") === "true";

          if (single && !open) {
            btns.forEach(function (other) {
              if (other === btn) return;
              other.setAttribute("aria-expanded", "false");
              var op = document.getElementById(other.getAttribute("aria-controls"));
              if (op) op.setAttribute("data-open", "false");
            });
          }

          btn.setAttribute("aria-expanded", String(!open));
          panel.setAttribute("data-open", String(!open));
        });
      });
    });
  }

  /* ------------------------------------------------------------------
     Бегущая строка: дублируем содержимое, чтобы шла бесшовно
     ------------------------------------------------------------------ */
  function initMarquee() {
    $$(".marquee__track").forEach(function (track) {
      if (track.getAttribute("data-cloned") === "true") return;
      track.innerHTML += track.innerHTML;
      track.setAttribute("data-cloned", "true");
    });
  }

  /* ------------------------------------------------------------------
     Полоса прогресса чтения
     ------------------------------------------------------------------ */
  function initProgress() {
    var bar = $(".progress");
    if (!bar) return;

    var ticking = false;
    function update() {
      var max = document.documentElement.scrollHeight - window.innerHeight;
      var p = max > 0 ? window.scrollY / max : 0;
      bar.style.transform = "scaleX(" + Math.min(Math.max(p, 0), 1) + ")";
      ticking = false;
    }
    window.addEventListener("scroll", function () {
      if (!ticking) { ticking = true; requestAnimationFrame(update); }
    }, { passive: true });
    update();
  }

  /* ------------------------------------------------------------------
     Фон героя: дрейфующая сеть узлов
     ------------------------------------------------------------------ */
  function initHeroCanvas() {
    var canvas = $(".hero__canvas");
    if (!canvas || reduceMotion) return;

    var ctx = canvas.getContext("2d");
    if (!ctx) return;

    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var nodes = [];
    var w = 0, h = 0;
    var pointer = { x: -9999, y: -9999 };
    var running = true;

    // Цвет берём из CSS-переменной темы, чтобы канвас совпадал с брендом
    var accent = getComputedStyle(document.documentElement)
      .getPropertyValue("--accent-2").trim() || "#22d3ee";
    var rgb = hexToRgb(accent) || { r: 34, g: 211, b: 238 };

    function hexToRgb(hex) {
      var m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
      return m ? { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) } : null;
    }

    function resize() {
      var rect = canvas.getBoundingClientRect();
      w = rect.width; h = rect.height;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Плотность узлов зависит от площади, но ограничена сверху
      var count = Math.min(Math.round((w * h) / 17000), 86);
      nodes = [];
      for (var i = 0; i < count; i++) {
        nodes.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.19,
          vy: (Math.random() - 0.5) * 0.19,
          r: Math.random() * 1.25 + 0.55
        });
      }
    }

    function draw() {
      if (!running) return;
      ctx.clearRect(0, 0, w, h);

      for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        n.x += n.vx; n.y += n.vy;

        if (n.x < 0 || n.x > w) n.vx *= -1;
        if (n.y < 0 || n.y > h) n.vy *= -1;

        // Линии между близкими узлами
        for (var j = i + 1; j < nodes.length; j++) {
          var m = nodes[j];
          var dx = n.x - m.x, dy = n.y - m.y;
          var d2 = dx * dx + dy * dy;
          if (d2 > 20000) continue;                    // ~141px
          var a = (1 - Math.sqrt(d2) / 141) * 0.2;
          ctx.strokeStyle = "rgba(" + rgb.r + "," + rgb.g + "," + rgb.b + "," + a.toFixed(3) + ")";
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(n.x, n.y);
          ctx.lineTo(m.x, m.y);
          ctx.stroke();
        }

        // Узлы рядом с курсором разгораются
        var pdx = n.x - pointer.x, pdy = n.y - pointer.y;
        var near = Math.sqrt(pdx * pdx + pdy * pdy) < 170;
        ctx.fillStyle = "rgba(" + rgb.r + "," + rgb.g + "," + rgb.b + "," + (near ? 0.9 : 0.42) + ")";
        ctx.beginPath();
        ctx.arc(n.x, n.y, near ? n.r * 1.7 : n.r, 0, Math.PI * 2);
        ctx.fill();
      }

      requestAnimationFrame(draw);
    }

    window.addEventListener("resize", debounce(resize, 180));
    window.addEventListener("pointermove", function (e) {
      var r = canvas.getBoundingClientRect();
      pointer.x = e.clientX - r.left;
      pointer.y = e.clientY - r.top;
    }, { passive: true });

    // Не жжём батарею, когда герой не виден
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        var wasRunning = running;
        running = entries[0].isIntersecting;
        if (running && !wasRunning) draw();
      }, { threshold: 0 }).observe(canvas);
    }

    resize();
    draw();
  }

  function debounce(fn, ms) {
    var t;
    return function () {
      var args = arguments, self = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  }

  /* ------------------------------------------------------------------
     Год в подвале
     ------------------------------------------------------------------ */
  function initYear() {
    $$("[data-year]").forEach(function (el) {
      el.textContent = String(new Date().getFullYear());
    });
  }

  /* ------------------------------------------------------------------
     Подстановка контактов из config.js
     Даёт одну точку правки телефонов/почты/мессенджеров.
     ------------------------------------------------------------------ */
  function initContacts() {
    var S = window.SITE;
    if (!S) return;

    $$("[data-contact]").forEach(function (el) {
      var key = el.getAttribute("data-contact");
      var value = S[key];
      if (!value) return;

      if (el.tagName === "A") {
        if (key === "phone")      el.href = "tel:" + value.replace(/[^\d+]/g, "");
        else if (key === "email") el.href = "mailto:" + value;
        else if (/^https?:/.test(value)) el.href = value;
      }
      if (el.hasAttribute("data-contact-text") || el.children.length === 0) {
        el.textContent = value;
      }
    });

    $$("[data-link]").forEach(function (el) {
      var url = S[el.getAttribute("data-link")];
      if (url) el.href = url; else el.remove();
    });
  }

  /* ------------------------------------------------------------------
     Форма-бриф
     ------------------------------------------------------------------ */
  function initForm() {
    var form = $("[data-brief-form]");
    if (!form) return;

    var note = $(".form__note", form);
    var submit = form.querySelector('[type="submit"]');

    function setNote(state, key, fallback) {
      if (!note) return;
      var text = (window.I18N && window.I18N.t(key)) || fallback;
      note.textContent = text;
      note.setAttribute("data-state", state);
    }

    function fieldOf(input) { return input.closest(".field") || input.closest(".form__row"); }

    function validate() {
      var ok = true;
      $$("[required]", form).forEach(function (input) {
        var valid = input.checkValidity() && String(input.value).trim() !== "";
        var field = fieldOf(input);
        if (field) field.classList.toggle("is-invalid", !valid);
        if (!valid && ok) { input.focus(); ok = false; }
      });
      return ok;
    }

    // Снимаем подсветку ошибки, как только человек начал править поле
    form.addEventListener("input", function (e) {
      var field = fieldOf(e.target);
      if (field) field.classList.remove("is-invalid");
    });

    /* Собираем читаемое письмо — оно уходит и на почту, и в мессенджер */
    function compose(data) {
      var lines = ["Заявка с сайта " + location.hostname, ""];
      var labels = {
        name: "Имя", company: "Компания", contact: "Телефон / e-mail",
        service: "Услуга", budget: "Бюджет", deadline: "Сроки", message: "Задача"
      };
      Object.keys(labels).forEach(function (k) {
        if (data[k]) lines.push(labels[k] + ": " + data[k]);
      });
      lines.push("", "Страница: " + location.href);
      return lines.join("\n");
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!validate()) {
        setNote("err", "form.errRequired", "Заполните обязательные поля.");
        return;
      }

      var fd = new FormData(form);
      var data = {};
      fd.forEach(function (v, k) { data[k] = v; });
      var text = compose(data);

      var S = window.SITE || {};
      var endpoint = S.formEndpoint;

      // Есть настроенный приёмник заявок — отправляем туда
      if (endpoint) {
        if (submit) submit.setAttribute("aria-disabled", "true");
        setNote("ok", "form.sending", "Отправляем…");

        fetch(endpoint, {
          method: "POST",
          headers: { "Accept": "application/json" },
          body: fd
        }).then(function (res) {
          if (!res.ok) throw new Error("HTTP " + res.status);
          form.reset();
          setNote("ok", "form.ok", "Заявка отправлена. Свяжемся в течение рабочего дня.");
        }).catch(function () {
          setNote("err", "form.err", "Не удалось отправить. Напишите нам в WhatsApp или на почту.");
        }).finally(function () {
          if (submit) submit.removeAttribute("aria-disabled");
        });
        return;
      }

      // Приёмник не настроен — открываем почтовый клиент с готовым письмом
      var mail = S.email || "";
      var subject = "Заявка с сайта " + location.hostname;
      window.location.href = "mailto:" + mail +
        "?subject=" + encodeURIComponent(subject) +
        "&body=" + encodeURIComponent(text);
      setNote("ok", "form.mailto", "Открываем почтовый клиент с готовым письмом.");
    });
  }

  /* ------------------------------------------------------------------
     Плавная прокрутка к якорям с учётом фиксированной шапки
     ------------------------------------------------------------------ */
  function initAnchors() {
    document.addEventListener("click", function (e) {
      var a = e.target.closest('a[href^="#"]');
      if (!a) return;
      var id = a.getAttribute("href");
      if (id === "#" || id.length < 2) return;
      var target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
      history.replaceState(null, "", id);
    });
  }

  /* ------------------------------------------------------------------
     Запуск
     ------------------------------------------------------------------ */
  function boot() {
    initHeader();
    initNav();
    initReveal();
    initCounters();
    initCardGlow();
    initTabs();
    initAccordion();
    initMarquee();
    initProgress();
    initHeroCanvas();
    initYear();
    initContacts();
    initForm();
    initAnchors();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
