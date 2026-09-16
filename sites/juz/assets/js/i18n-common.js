/* ==========================================================================
   i18n-common.js — строки, одинаковые на всех страницах обоих сайтов:
   навигация, подвал, форма-бриф, общие кнопки.

   Русский здесь НЕ дублируется: он уже записан в HTML и служит основой.
   Достаточно казахской и английской версий.
   ========================================================================== */
window.I18N_COMMON = {
  kk: {
    nav: {
      development: "Әзірлеу",
      support: "Сүйемелдеу",
      analytics: "Аналитика",
      approach: "Тәсіл",
      contacts: "Байланыс",
      services: "Қызметтер",
      home: "Басты бет",
      menu: "Мәзір"
    },
    cta: {
      brief: "Өтінім қалдыру",
      discuss: "Мәселені талқылау",
      call: "Қоңырау шалу",
      write: "Жазу",
      more: "Толығырақ",
      allServices: "Барлық қызметтер",
      estimate: "Бағасын білу"
    },
    footer: {
      servicesTitle: "Қызметтер",
      companyTitle: "Компания",
      contactsTitle: "Байланыс",
      approach: "Жұмыс тәсілі",
      stack: "Технологиялар",
      faq: "Жиі қойылатын сұрақтар",
      privacy: "Дербес деректер саясаты",
      rights: "Барлық құқықтар қорғалған.",
      sisterHint: "Топ бренді"
    },
    form: {
      title: "Міндетті сипаттаңыз",
      lead: "Бір жұмыс күні ішінде жауап береміз: нақтылайтын сұрақтар, көлемді алдын ала бағалау және келесі қадам.",
      name: "Аты-жөніңіз",
      namePh: "Мысалы, Айгүл Серікова",
      company: "Компания",
      companyPh: "Ұйымның атауы",
      contact: "Телефон немесе e-mail",
      contactPh: "+7 700 000 00 00",
      service: "Қандай қызмет қажет",
      budget: "Болжамды бюджет",
      deadline: "Қалаған мерзім",
      message: "Міндет туралы қысқаша",
      messagePh: "Қандай жүйе, қандай мәселе, қандай нәтиже күтілуде",
      consent: "Дербес деректерімнің өңделуіне келісім беремін",
      submit: "Өтінім жіберу",
      required: "міндетті",
      optional: "міндетті емес",
      errRequired: "Міндетті өрістерді толтырыңыз.",
      sending: "Жіберілуде…",
      ok: "Өтінім жіберілді. Бір жұмыс күні ішінде хабарласамыз.",
      err: "Жіберу мүмкін болмады. WhatsApp арқылы немесе поштаға жазыңыз.",
      mailto: "Дайын хаты бар пошта клиенті ашылуда.",
      orQuick: "Немесе бірден жазыңыз"
    },
    opts: {
      svcDev: "БҚ әзірлеу",
      svcSupport: "ЖЖ сүйемелдеу",
      svcAnalytics: "Аналитика және деректер",
      svcAudit: "Аудит және консалтинг",
      svcOther: "Басқа",
      budgetSmall: "5 млн ₸ дейін",
      budgetMid: "5–20 млн ₸",
      budgetLarge: "20–60 млн ₸",
      budgetXL: "60 млн ₸ жоғары",
      budgetUnknown: "Әлі белгісіз",
      dlUrgent: "Шұғыл",
      dlQuarter: "1–3 ай",
      dlHalf: "3–6 ай",
      dlLong: "6 айдан астам",
      dlPlanning: "Жоспарлау кезеңінде"
    },
    contact: {
      phone: "Телефон",
      email: "Пошта",
      address: "Мекенжай",
      hours: "Жұмыс уақыты",
      whatsapp: "WhatsApp",
      telegram: "Telegram"
    }
  },

  en: {
    nav: {
      development: "Development",
      support: "Support",
      analytics: "Analytics",
      approach: "Approach",
      contacts: "Contact",
      services: "Services",
      home: "Home",
      menu: "Menu"
    },
    cta: {
      brief: "Send a brief",
      discuss: "Discuss your project",
      call: "Call us",
      write: "Message us",
      more: "Learn more",
      allServices: "All services",
      estimate: "Get an estimate"
    },
    footer: {
      servicesTitle: "Services",
      companyTitle: "Company",
      contactsTitle: "Contact",
      approach: "How we work",
      stack: "Technology",
      faq: "FAQ",
      privacy: "Privacy policy",
      rights: "All rights reserved.",
      sisterHint: "Group brand"
    },
    form: {
      title: "Tell us about the project",
      lead: "We reply within one business day: clarifying questions, a rough scope estimate and a concrete next step.",
      name: "Your name",
      namePh: "e.g. Aigul Serikova",
      company: "Company",
      companyPh: "Organisation name",
      contact: "Phone or e-mail",
      contactPh: "+7 700 000 00 00",
      service: "What do you need",
      budget: "Approximate budget",
      deadline: "Target timeline",
      message: "Short description",
      messagePh: "Which system, what problem, what outcome you expect",
      consent: "I consent to the processing of my personal data",
      submit: "Send the brief",
      required: "required",
      optional: "optional",
      errRequired: "Please fill in the required fields.",
      sending: "Sending…",
      ok: "Brief sent. We will get back to you within one business day.",
      err: "Could not send. Please message us on WhatsApp or by e-mail.",
      mailto: "Opening your mail client with a pre-filled message.",
      orQuick: "Or reach us directly"
    },
    opts: {
      svcDev: "Software development",
      svcSupport: "System support",
      svcAnalytics: "Analytics & data",
      svcAudit: "Audit & consulting",
      svcOther: "Something else",
      budgetSmall: "up to 5M ₸",
      budgetMid: "5–20M ₸",
      budgetLarge: "20–60M ₸",
      budgetXL: "60M ₸ and above",
      budgetUnknown: "Not defined yet",
      dlUrgent: "Urgent",
      dlQuarter: "1–3 months",
      dlHalf: "3–6 months",
      dlLong: "6+ months",
      dlPlanning: "Still planning"
    },
    contact: {
      phone: "Phone",
      email: "E-mail",
      address: "Address",
      hours: "Business hours",
      whatsapp: "WhatsApp",
      telegram: "Telegram"
    }
  }
};
