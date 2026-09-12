"""English/Arabic strings for the whole app.

Tk 8.6.x on Windows shapes and bidi-orders Arabic natively (verified on the
target: Tk 8.6.15 renders raw Arabic correctly). Pre-shaping with
arabic-reshaper + python-bidi on top of that DOUBLE-processes the text and
scrambles it, so `shape()` is a passthrough -- we hand Tk the raw string and
let it lay the text out. `n()` and `t()`/`shape()` therefore return the same
thing; both names are kept so call sites need not change.
"""

from __future__ import annotations

import steamlib

# Native Tk handles Arabic here, so no reshaping library is required.
HAS_SHAPING = True

LANGUAGES = {"en": "English", "ar": "العربية"}
DEFAULT_LANGUAGE = "en"

_current = steamlib.load_config().get("language", DEFAULT_LANGUAGE)
if _current not in LANGUAGES:
    _current = DEFAULT_LANGUAGE


def get_language() -> str:
    return _current


def set_language(code: str) -> None:
    global _current
    if code not in LANGUAGES:
        return
    _current = code
    config = steamlib.load_config()
    config["language"] = code
    steamlib.save_config(config)


def n(key: str, **kwargs) -> str:
    """Raw translation, for native dialogs and window titles."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(_current) or entry.get(DEFAULT_LANGUAGE, key)
    return text.format(**kwargs) if kwargs else text


def shape(text: str) -> str:
    """Passthrough. Tk shapes Arabic natively; extra processing would break it.
    Kept so call sites (game names, API strings) stay unchanged."""
    return text


def t(key: str, **kwargs) -> str:
    """Translation for drawing inside Tk widgets (Tk handles Arabic layout)."""
    return n(key, **kwargs)


STRINGS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------ shared
    "app.title": {"en": "ZFA Achievement", "ar": "ZFA Achievement"},
    "app.copyright": {
        "en": "© 2026 ZFA Achievement · by Ziad Fayez",
        "ar": "© 2026 ZFA Achievement · Ziad Fayez",
    },
    "tray.show": {"en": "Show ZFA Achievement", "ar": "إظهار ZFA Achievement"},
    "tray.quit": {"en": "Quit", "ar": "إنهاء"},
    "tray.minimized": {
        "en": "Still running here — right-click to quit.",
        "ar": "لسه شغّال هون — كليك يمين للإنهاء.",
    },
    "btn.save": {"en": "Save", "ar": "حفظ"},
    "btn.cancel": {"en": "Cancel", "ar": "إلغاء"},
    "btn.settings": {"en": "Settings", "ar": "الإعدادات"},
    "btn.refresh": {"en": "Refresh", "ar": "تحديث"},
    "btn.reload": {"en": "Reload", "ar": "إعادة تحميل"},
    "search": {"en": "Search", "ar": "بحث"},
    "col.appid": {"en": "AppID", "ar": "رقم اللعبة"},
    "col.game": {"en": "Game", "ar": "اللعبة"},
    "language": {"en": "Language", "ar": "اللغة"},
    "picker.header": {"en": "Your games", "ar": "ألعابك"},
    "picker.stat_games": {"en": "games", "ar": "لعبة"},
    "picker.stat_installed": {"en": "installed", "ar": "مثبّتة"},
    "picker.stat_completion": {"en": "avg. complete", "ar": "متوسط الإكمال"},
    "picker.whole_library": {"en": "Whole library", "ar": "كل المكتبة"},
    "picker.dll_searching": {
        "en": "searching for steam_api64.dll…",
        "ar": "جارٍ البحث عن steam_api64.dll…",
    },
    "picker.no_games": {
        "en": "No installed games found.\n\nTurn on “Whole library”, or use the AppID "
        "box to open a game manually.",
        "ar": "ما لقيت أي لعبة مثبّتة.\n\nشغّل خيار «كل المكتبة»، أو استخدم خانة رقم اللعبة "
        "لفتح لعبة يدويًا.",
    },
    "picker.col_played": {"en": "Played", "ar": "وقت اللعب"},
    "picker.not_installed": {"en": "not installed", "ar": "غير مثبّتة"},
    "picker.open_by_appid": {"en": "Or open by AppID:", "ar": "أو افتح برقم اللعبة:"},
    "picker.open": {"en": "Open", "ar": "افتح"},
    "picker.badges_button": {"en": "Badges & card costs", "ar": "الشارات وتكلفة الكروت"},
    "picker.idler_button": {"en": "Playtime & card idler", "ar": "وقت اللعب والكروت"},
    "picker.settings_button": {"en": "Profile settings", "ar": "إعدادات الحساب"},
    "picker.open_achievements": {"en": "Open achievements", "ar": "افتح الإنجازات"},
    "picker.refresh_games": {"en": "Refresh games", "ar": "تحديث الألعاب"},
    "picker.set_dll": {"en": "Set steam_api64.dll", "ar": "تحديد steam_api64.dll"},
    "picker.dll_path": {"en": "steam_api64.dll:  {path}", "ar": "steam_api64.dll:  {path}"},
    "picker.reading_library": {
        "en": "reading your whole Steam library…",
        "ar": "جارٍ قراءة مكتبتك كاملة…",
    },
    "picker.resolving_names": {
        "en": "looking up game names… {index}/{total}",
        "ar": "جارٍ جلب أسماء الألعاب… {index}/{total}",
    },
    "picker.library_failed": {
        "en": "Could not read your library:\n{error}",
        "ar": "تعذّر قراءة المكتبة:\n{error}",
    },
    "picker.select_first": {
        "en": "Select a game from the list first.",
        "ar": "اختر لعبة من القائمة أولًا.",
    },
    "picker.bad_appid": {
        "en": "Enter a valid AppID (digits only).",
        "ar": "اكتب رقم AppID صحيح (أرقام فقط).",
    },
    "picker.launch_failed": {
        "en": "Could not open the achievements window:\n{error}",
        "ar": "تعذّر فتح نافذة الإنجازات:\n{error}",
    },
    "picker.account": {"en": "signed in as {persona}", "ar": "الحساب: {persona}"},
    "picker.setting_up": {"en": "setting things up…", "ar": "جارٍ التجهيز تلقائيًا…"},
    "picker.dll_missing": {
        "en": "steam_api64.dll not found — press “Set steam_api64.dll” to pick one",
        "ar": "ما لقيت steam_api64.dll — اضغط «تحديد steam_api64.dll» لاختياره",
    },
    "idler.auto_start": {
        "en": "Auto-start games with drops",
        "ar": "شغّل اللي إلها كروت تلقائيًا",
    },
    "idler.status_restarted": {"en": " · {count} restarted", "ar": " · {count} أُعيد تشغيلها"},
    "idler.state_skipped": {"en": "not available", "ar": "غير متاحة"},
    "picker.scan_button": {"en": "Scan all achievements", "ar": "مسح كل الإنجازات"},
    "scan.title": {"en": "Achievement completion — all games", "ar": "إكمال الإنجازات — كل الألعاب"},
    "scan.header": {"en": "COMPLETION", "ar": "نسبة الإكمال"},
    "scan.col_pct": {"en": "%", "ar": "٪"},
    "scan.col_done": {"en": "Unlocked", "ar": "مفتوحة"},
    "scan.col_total": {"en": "Total", "ar": "الكل"},
    "scan.scan_button": {"en": "Scan now", "ar": "ابدأ المسح"},
    "scan.stop": {"en": "Stop", "ar": "إيقاف"},
    "scan.open": {"en": "Open achievements", "ar": "افتح الإنجازات"},
    "scan.only_incomplete": {"en": "Hide finished / empty", "ar": "إخفاء المكتملة/الفارغة"},
    "scan.scanning": {"en": "Scanning… {done}/{total}  ·  {game}", "ar": "جارٍ المسح… {done}/{total}  ·  {game}"},
    "scan.idle": {"en": "{scanned} game(s) scanned · double-click to open", "ar": "{scanned} لعبة ممسوحة · دبل-كليك للفتح"},
    "scan.never": {"en": "Not scanned yet — press “Scan now”. Steam must be running.", "ar": "ما انمسحت بعد — اضغط «ابدأ المسح». لازم Steam يكون شغّال."},
    "scan.done": {"en": "Done · {withach} game(s) have achievements · {perfect} at 100%", "ar": "خلص · {withach} لعبة إلها إنجازات · {perfect} على 100٪"},
    "scan.no_ach": {"en": "—", "ar": "—"},
    # ------------------------------------------------------------ dll
    "dll.title": {"en": "steam_api64.dll", "ar": "steam_api64.dll"},
    "dll.required": {
        "en": "Set the path to steam_api64.dll first.",
        "ar": "لازم تحدد مسار steam_api64.dll أولًا.",
    },
    "dll.select": {"en": "Select steam_api64.dll", "ar": "اختر steam_api64.dll"},
    # ------------------------------------------------------------ achievements
    "ach.title": {
        "en": "Achievements — {game} ({app_id})",
        "ar": "الإنجازات — {game} ({app_id})",
    },
    "ach.header": {"en": "ACHIEVEMENTS", "ar": "الإنجازات"},
    "ach.locked_only": {"en": "Locked only", "ar": "المقفلة فقط"},
    "ach.hidden": {"en": "(hidden)", "ar": "(مخفي)"},
    "ach.loading": {"en": "Loading…", "ar": "جارٍ التحميل…"},
    "ach.waiting": {
        "en": "Waiting for Steam stats… ({attempt})",
        "ar": "بانتظار بيانات Steam… ({attempt})",
    },
    "ach.none": {
        "en": "No achievements reported for this game.",
        "ar": "ما في إنجازات لهذه اللعبة.",
    },
    "ach.none_detail": {
        "en": "Steam reported no achievements for this game.\n\nMost likely the game has "
        "none, or Steam has not loaded its data yet. Make sure Steam is running and "
        "signed in, then try again.",
        "ar": "ما وصلني أي إنجاز لهذه اللعبة.\n\nغالبًا اللعبة بدون إنجازات، أو Steam لسه ما "
        "حمّل بياناتها.\nتأكد أن Steam شغّال ومسجّل دخول ثم أعد المحاولة.",
    },
    "ach.status": {
        "en": "{unlocked}/{total} unlocked · {changed} pending change(s)",
        "ar": "{unlocked}/{total} مفتوح · {changed} تعديل غير محفوظ",
    },
    "ach.commit": {"en": "Commit changes", "ar": "حفظ التغييرات"},
    "ach.invert": {"en": "Invert", "ar": "عكس"},
    "ach.lock_all": {"en": "Lock all", "ar": "اقفل الكل"},
    "ach.unlock_all": {"en": "Unlock all", "ar": "افتح الكل"},
    "ach.spread": {"en": "Spread over time", "ar": "وزّع على فترة"},
    "ach.spread_hint": {
        "en": "Unlock gradually instead of all at once (looks more natural).",
        "ar": "افتح تدريجيًا بدل دفعة وحدة (بيبيّن أطبعي).",
    },
    "ach.restore": {"en": "Undo (restore backup)", "ar": "تراجع (استرجاع)"},
    "ach.confirm_spread": {
        "en": "{count} achievement(s) in “{game}” will be changed over about "
        "{minutes} minute(s), saved to your account.\nA backup is taken first. "
        "Continue?",
        "ar": "سيتم تعديل {count} إنجاز في «{game}» على مدى حوالي {minutes} دقيقة، وحفظها "
        "على حسابك.\nبيتاخد نسخة احتياطية أول. نكمّل؟",
    },
    "ach.committing": {
        "en": "Applying… {done}/{total}",
        "ar": "جارٍ التطبيق… {done}/{total}",
    },
    "ach.commit_done": {
        "en": "Applied {count} change(s).",
        "ar": "تم تطبيق {count} تعديل.",
    },
    "ach.stop": {"en": "Stop", "ar": "إيقاف"},
    "ach.no_backup": {"en": "No backup found for this game.", "ar": "ما في نسخة احتياطية لهذه اللعبة."},
    "ach.restore_confirm": {
        "en": "Restore the saved state from {when}? This reverts {count} achievement(s).",
        "ar": "استرجاع الحالة المحفوظة من {when}؟ هاد بيرجّع {count} إنجاز.",
    },
    "ach.restored": {"en": "Restored {count} achievement(s).", "ar": "تم استرجاع {count} إنجاز."},
    "ach.confirm_title": {"en": "Confirm", "ar": "تأكيد"},
    "ach.confirm": {
        "en": "{count} achievement(s) in “{game}” will be changed and saved to your "
        "account.\nAre you sure?",
        "ar": "سيتم تعديل {count} إنجاز في «{game}» وحفظها على حسابك.\nمتأكد؟",
    },
    "ach.store_failed": {
        "en": "Saving failed (StoreStats). Make sure Steam is still running.",
        "ar": "فشل حفظ التغييرات (StoreStats). تأكد أن Steam ما زال شغّال.",
    },
    "ach.partial_failed": {
        "en": "These achievements could not be changed:\n{names}",
        "ar": "تعذّر تعديل هذه الإنجازات:\n{names}",
    },
    "ach.saved_title": {"en": "Done", "ar": "تم"},
    "ach.saved": {"en": "Changes saved successfully.", "ar": "تم حفظ التغييرات بنجاح."},
    # ------------------------------------------------------------ badges
    "badges.title": {"en": "Badges & card sets", "ar": "الشارات وأطقم الكروت"},
    "badges.level": {"en": "Level {level}", "ar": "المستوى {level}"},
    "badges.xp": {
        "en": "XP {xp}  ·  {needed} XP to reach Level {next_level}",
        "ar": "الخبرة {xp}  ·  ناقصك {needed} للمستوى {next_level}",
    },
    "badges.col_badge": {"en": "Badge", "ar": "الشارة"},
    "badges.col_level": {"en": "Lvl", "ar": "المستوى"},
    "badges.col_cards": {"en": "Cards", "ar": "الكروت"},
    "badges.col_missing": {"en": "Missing", "ar": "الناقص"},
    "badges.col_cost": {"en": "Cost", "ar": "التكلفة"},
    "badges.col_drops": {"en": "Drops", "ar": "متبقي"},
    "badges.fetch_prices": {"en": "Fetch market prices", "ar": "جلب أسعار السوق"},
    "badges.card_details": {"en": "Card details", "ar": "تفاصيل الكروت"},
    "badges.no_profile": {"en": "No profile configured.", "ar": "ما في حساب محدد."},
    "badges.loading": {"en": "Loading badges…", "ar": "جارٍ تحميل الشارات…"},
    "badges.loading_page": {"en": "Loading {what}…", "ar": "جارٍ تحميل {what}…"},
    "badges.loading_sets": {
        "en": "Loading card sets… {index}/{total}",
        "ar": "جارٍ تحميل أطقم الكروت… {index}/{total}",
    },
    "badges.load_failed": {"en": "Load failed.", "ar": "فشل التحميل."},
    "badges.load_failed_detail": {
        "en": "Could not load badges:\n{error}",
        "ar": "تعذّر تحميل الشارات:\n{error}",
    },
    "badges.summary": {
        "en": "{total} badge(s) · {incomplete} incomplete · prices not fetched yet",
        "ar": "{total} شارة · {incomplete} ناقصة · الأسعار لسه ما انجابت",
    },
    "badges.no_cookie_suffix": {
        "en": "  ·  no cookie: drops/prices unavailable",
        "ar": "  ·  بدون كوكي: الكروت المتبقية والأسعار غير متاحة",
    },
    "badges.cookie_needed_title": {"en": "Cookie required", "ar": "الكوكي مطلوب"},
    "badges.cookie_needed": {
        "en": "Steam refuses market requests without a login (it returns 429).\n"
        "Add your steamLoginSecure cookie from the Settings button.",
        "ar": "أسعار السوق بترفض الطلبات بدون تسجيل دخول (Steam بيرجّع 429).\n"
        "ضيف كوكي steamLoginSecure من زر الإعدادات.",
    },
    "badges.complete_title": {"en": "Complete", "ar": "مكتمل"},
    "badges.nothing_missing": {
        "en": "No badge is missing cards.",
        "ar": "ما في شارة ناقصة كروت.",
    },
    "badges.fetching_prices": {
        "en": "Fetching prices… {index}/{total}",
        "ar": "جارٍ جلب الأسعار… {index}/{total}",
    },
    "badges.failed_count": {"en": " ({count} failed)", "ar": " ({count} فشل)"},
    "badges.priced": {
        "en": "Priced {count} set(s) · completing them all ≈ {total}",
        "ar": "تم تسعير {count} طقم · إكمالها كلها ≈ {total}",
    },
    "badges.rate_limited": {
        "en": " · {count} failed (rate limit)",
        "ar": " · {count} فشل (تجاوز الحد)",
    },
    "badges.plan_need": {
        "en": "Need {xp} XP → {crafts} badge craft(s) to reach the next level.",
        "ar": "ناقصك {xp} خبرة ← {crafts} صياغة شارة للوصول للمستوى الجاي.",
    },
    "badges.plan_free": {"en": "Free route: idle {games}", "ar": "مجانًا: شغّل {games}"},
    "badges.plan_cheapest": {
        "en": "Cheapest to buy: {games}  =  {total}",
        "ar": "أرخص شراء: {games}  =  {total}",
    },
    "badges.detail_title": {"en": "{game} — cards", "ar": "{game} — الكروت"},
    "badges.no_badge_yet": {"en": "No badge yet", "ar": "ما في شارة بعد"},
    "badges.detail_header": {
        "en": "{badge} · {owned}/{total} cards",
        "ar": "{badge} · {owned}/{total} كرت",
    },
    "badges.col_card": {"en": "Card", "ar": "الكرت"},
    "badges.col_have": {"en": "Have", "ar": "عندك"},
    "badges.col_price": {"en": "Price", "ar": "السعر"},
    "badges.detail_footer": {
        "en": "Missing {count} card(s) · cost {cost}",
        "ar": "ناقصك {count} كرت · التكلفة {cost}",
    },
    # ------------------------------------------------------------ idler
    "idler.title": {
        "en": "Idler — playtime & card drops",
        "ar": "التشغيل الخلفي — وقت اللعب والكروت",
    },
    "idler.header": {"en": "IDLER", "ar": "التشغيل الخلفي"},
    "idler.drops_only": {
        "en": "Only games with card drops",
        "ar": "الألعاب اللي إلها كروت متبقية فقط",
    },
    "idler.col_playtime": {"en": "Playtime", "ar": "وقت اللعب"},
    "idler.col_drops": {"en": "Drops", "ar": "متبقي"},
    "idler.col_state": {"en": "State", "ar": "الحالة"},
    "idler.col_session": {"en": "Session", "ar": "الجلسة"},
    "idler.run_for": {"en": "Run for", "ar": "شغّل لمدة"},
    "idler.run_for_suffix": {
        "en": "hours, then stop automatically  (leave empty to run until you stop it)",
        "ar": "ساعة ثم يوقف تلقائيًا  (اتركها فاضية ليضل شغّال لحد ما توقفه)",
    },
    "idler.start_selected": {"en": "Start selected", "ar": "شغّل المحدد"},
    "idler.stop_selected": {"en": "Stop selected", "ar": "أوقف المحدد"},
    "idler.stop_all": {"en": "Stop all", "ar": "أوقف الكل"},
    "idler.start_all_drops": {
        "en": "Start all with drops",
        "ar": "شغّل كل اللي إلها كروت",
    },
    "idler.add_appid": {"en": "Add AppID", "ar": "إضافة رقم لعبة"},
    "idler.loading": {"en": "loading your library…", "ar": "جارٍ تحميل مكتبتك…"},
    "idler.note_no_cookie": {
        "en": "{count} game(s) · card drop counts need a cookie",
        "ar": "{count} لعبة · عدد الكروت المتبقية بيحتاج كوكي",
    },
    "idler.note_drops": {
        "en": "{count} game(s) · {waiting} card(s) waiting to drop",
        "ar": "{count} لعبة · {waiting} كرت بانتظار النزول",
    },
    "idler.note_drops_failed": {
        "en": "{count} game(s) · drops unavailable ({error})",
        "ar": "{count} لعبة · الكروت المتبقية غير متاحة ({error})",
    },
    "idler.load_failed": {"en": "load failed", "ar": "فشل التحميل"},
    "idler.status": {
        "en": "{running} idling · {hours} game-hours this session",
        "ar": "{running} شغّالة · {hours} ساعة لعب بهالجلسة",
    },
    "idler.status_failed": {"en": " · {count} failed", "ar": " · {count} فشل"},
    "idler.state_idling": {"en": "idling", "ar": "شغّالة"},
    "idler.state_stopped": {"en": "stopped", "ar": "متوقفة"},
    "idler.select_first": {
        "en": "Select one or more games from the list.",
        "ar": "اختر لعبة أو أكثر من القائمة.",
    },
    "idler.ctx_stop": {"en": "⏹  Stop this game", "ar": "⏹  أوقف هذه اللعبة"},
    "idler.ctx_start": {"en": "▶  Start this game", "ar": "▶  شغّل هذه اللعبة"},
    "idler.ctx_check": {"en": "☑  Tick", "ar": "☑  أشّر"},
    "idler.ctx_uncheck": {"en": "☐  Untick", "ar": "☐  ألغِ التأشير"},
    "idler.start_result": {
        "en": "{ok} of {total} game(s) are now running.",
        "ar": "{ok} من {total} لعبة صارت شغّالة الآن.",
    },
    "idler.start_failed_list": {
        "en": "Could not start (no license / removed from store):\n{names}",
        "ar": "ما زبطت (بدون ترخيص / مسحوبة من المتجر):\n{names}",
    },
    "idler.none_title": {"en": "Nothing to do", "ar": "لا يوجد"},
    "idler.no_drops": {
        "en": "No games have card drops remaining.\n"
        "(This needs a steamLoginSecure cookie from Settings.)",
        "ar": "ما في ألعاب إلها كروت متبقية.\n"
        "(هالمعلومة بتحتاج كوكي steamLoginSecure من الإعدادات.)",
    },
    "idler.max_title": {"en": "Limit reached", "ar": "الحد الأقصى"},
    "idler.max_reached": {
        "en": "You cannot run more than {max} games at once.\nStop some, then continue.",
        "ar": "ما بينفع أكثر من {max} لعبة بنفس الوقت.\nأوقف بعض الألعاب ثم كمّل.",
    },
    "idler.start_failed": {
        "en": "Could not start {game}:\n{error}",
        "ar": "تعذّر تشغيل {game}:\n{error}",
    },
    "idler.appid_prompt": {"en": "Enter an AppID:", "ar": "اكتب رقم AppID:"},
    "idler.close_title": {"en": "Stop idling", "ar": "إيقاف"},
    "idler.close_confirm": {
        "en": "{count} game(s) are still running. Closing this window stops them. Sure?",
        "ar": "في {count} لعبة شغّالة. إغلاق النافذة رح يوقفهم. متأكد؟",
    },
    # ------------------------------------------------------------ settings
    "settings.title": {"en": "Steam profile settings", "ar": "إعدادات حساب Steam"},
    "settings.profile_url": {"en": "Profile URL", "ar": "رابط الحساب"},
    "settings.profile_hint": {
        "en": "e.g. https://steamcommunity.com/id/yourname",
        "ar": "مثال: https://steamcommunity.com/id/yourname",
    },
    "settings.cookie": {"en": "Login cookie", "ar": "كوكي تسجيل الدخول"},
    "settings.cookie_help": {
        "en": "steamLoginSecure cookie (optional, but needed for card drop counts and "
        "prices):\nOpen steamcommunity.com in your browser while logged in →\n"
        "F12 → Application/Storage → Cookies → copy the steamLoginSecure value.",
        "ar": "كوكي steamLoginSecure (اختياري، بس ضروري لعدد الكروت المتبقية وللأسعار):\n"
        "افتح steamcommunity.com بالمتصفح وأنت مسجّل دخول ←\n"
        "F12 ← Application/Storage ← Cookies ← انسخ قيمة steamLoginSecure.",
    },
    "settings.cookie_note": {
        "en": "The cookie is stored only on this PC, in your AppData config file.",
        "ar": "الكوكي بينحفظ على هالجهاز بس، في ملف الإعدادات داخل AppData.",
    },
    "settings.bad_url_title": {"en": "Invalid URL", "ar": "رابط غير صالح"},
    "settings.bad_url": {
        "en": "The URL must be on steamcommunity.com\n"
        "Example: https://steamcommunity.com/id/yourname",
        "ar": "الرابط لازم يكون من steamcommunity.com\n"
        "مثال: https://steamcommunity.com/id/yourname",
    },
    "settings.autostart": {
        "en": "Start with Windows (in the tray, resumes idling)",
        "ar": "التشغيل مع ويندوز (بالساعة، ويكمّل الفرم تلقائيًا)",
    },
    "settings.autostart_on": {
        "en": "✓ Will start automatically on boot.",
        "ar": "✓ رح يشتغل تلقائيًا مع الإقلاع.",
    },
    "settings.autostart_off": {
        "en": "Auto-start turned off.",
        "ar": "التشغيل التلقائي متوقّف.",
    },
    "settings.language_note": {
        "en": "Open windows keep the old language until reopened.",
        "ar": "النوافذ المفتوحة بتضل باللغة القديمة لحد ما تسكّرها وتفتحها.",
    },
    "settings.no_shaping": {
        "en": "Arabic needs: pip install arabic-reshaper python-bidi",
        "ar": "العربية بتحتاج: pip install arabic-reshaper python-bidi",
    },
    "settings.import_cookie": {"en": "Import from browser", "ar": "استيراد من المتصفح"},
    "settings.check_cookie": {"en": "Test", "ar": "فحص"},
    "settings.import_ok": {
        "en": "Imported from {browser}.",
        "ar": "تم الاستيراد من {browser}.",
    },
    "settings.import_appbound": {
        "en": "{browser} uses App-Bound Encryption (Chrome 127+) and cannot be read "
        "automatically. Paste the cookie manually — the guide is below.",
        "ar": "{browser} بيستخدم تشفير App-Bound (Chrome 127+) وما ينقرأ تلقائيًا. الصق "
        "الكوكي يدويًا — الشرح تحت.",
    },
    "settings.import_none": {
        "en": "No Steam cookie found in any browser. Sign in to steamcommunity.com "
        "first, or paste it manually.",
        "ar": "ما لقيت كوكي Steam بأي متصفح. سجّل دخول على steamcommunity.com أولًا، أو "
        "الصقه يدويًا.",
    },
    "settings.import_deep": {
        "en": "Reading from Chrome (a few seconds)…",
        "ar": "جارٍ القراءة من كروم (بضع ثوانٍ)…",
    },
    "settings.cookie_valid": {
        "en": "✓ Logged in as {persona}",
        "ar": "✓ مسجّل دخول: {persona}",
    },
    "settings.cookie_wrong_account": {
        "en": "⚠ This cookie is for a different account ({id}).",
        "ar": "⚠ هالكوكي لحساب ثاني ({id}).",
    },
    "settings.cookie_invalid": {
        "en": "✗ Cookie not valid or expired.",
        "ar": "✗ الكوكي غير صالح أو منتهي.",
    },
    "settings.cookie_checking": {"en": "checking…", "ar": "جارٍ الفحص…"},
    # ------------------------------------------------------------ steamapi
    "steam.title": {"en": "Steam", "ar": "Steam"},
    "steam.dll_load_failed": {
        "en": "Could not load {path}\n{error}",
        "ar": "تعذّر تحميل {path}\n{error}",
    },
    "steam.not_a_dll": {
        "en": "That file is not a valid steam_api64.dll (no SteamAPI_Init).",
        "ar": "الملف المحدد ليس steam_api64.dll صالح (لا يوجد SteamAPI_Init).",
    },
    "steam.init_failed_detail": {
        "en": "Steamworks failed to start: {detail}",
        "ar": "فشل تشغيل Steamworks: {detail}",
    },
    "steam.init_failed": {
        "en": "Steamworks failed to start.\nMake sure Steam is running and signed in, "
        "and that the game is in your library.",
        "ar": "فشل تشغيل Steamworks.\nتأكد أن Steam شغّال ومسجّل دخول، وأن اللعبة موجودة "
        "في مكتبتك.",
    },
    "steam.no_interface": {
        "en": "Could not find the required interface in the DLL ({name}).",
        "ar": "لم أجد الواجهة المطلوبة في الـ DLL ({name}).",
    },
    "steam.missing_export": {
        "en": "The function {name} is missing from the DLL.",
        "ar": "الدالة {name} غير موجودة في الـ DLL.",
    },
    "web.games_private": {
        "en": "Your games list is not visible. The profile is probably private — add a "
        "steamLoginSecure cookie in Settings.",
        "ar": "قائمة ألعابك مش ظاهرة. غالبًا البروفايل خاص — ضيف كوكي steamLoginSecure من "
        "الإعدادات.",
    },
    "web.bad_market": {
        "en": "Invalid market response (the cookie has probably expired).",
        "ar": "رد السوق غير صالح (غالبًا الكوكي منتهي).",
    },
    "web.rate_limited": {
        "en": "Steam refused the requests (429). Try again shortly, or add a "
        "steamLoginSecure cookie.",
        "ar": "Steam رفض الطلبات (429). جرّب بعد شوي، أو ضيف كوكي steamLoginSecure.",
    },
    "web.http_error": {"en": "HTTP {code} from {url}", "ar": "HTTP {code} من {url}"},
    "web.connect_failed": {
        "en": "Could not reach Steam: {reason}",
        "ar": "تعذّر الاتصال بـ Steam: {reason}",
    },
}
