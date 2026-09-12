"""Read-only client for the Steam Community website.

Everything here is scraped from pages the user can already open in a browser.
Card drop counts, in-progress badges and market prices are only visible to the
logged-in owner, so a `steamLoginSecure` cookie unlocks the full data set; the
public subset still works without one.
"""

from __future__ import annotations

import html as html_module
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from i18n import n

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
CARD_ITEM_CLASS = "tag_item_class_2"  # trading cards, excludes emoticons/backgrounds


class WebError(Exception):
    pass


class RateLimited(WebError):
    pass


@dataclass
class Card:
    name: str
    owned: int
    index: str = ""
    price_text: str = ""
    price_cents: int | None = None


@dataclass
class Badge:
    app_id: int
    game_name: str
    badge_name: str = ""
    level: int = 0
    xp: int = 0
    cards_owned: int = 0
    cards_total: int = 0
    drops_remaining: int = 0
    playtime: str = ""
    cards: list[Card] = field(default_factory=list)

    @property
    def missing(self) -> int:
        if self.cards:
            return sum(1 for card in self.cards if card.owned == 0)
        return max(0, self.cards_total - self.cards_owned)

    @property
    def cost_cents(self) -> int | None:
        """Market cost of the missing cards, None while prices are unknown."""
        missing = [card for card in self.cards if card.owned == 0]
        if not missing or any(card.price_cents is None for card in missing):
            return None
        return sum(card.price_cents for card in missing)


@dataclass
class LevelInfo:
    level: int = 0
    xp: int = 0
    xp_to_next: int = 0


def _clean(text: str) -> str:
    return html_module.unescape(re.sub(r"\s+", " ", text)).strip()


class SteamWeb:
    """Throttled, cached HTTP access. Steam 429s aggressively -- especially the
    market endpoints -- so every request goes through one rate limiter."""

    def __init__(self, profile_url: str, cookie: str = "", min_interval: float = 1.2):
        self.profile_url = profile_url.rstrip("/")
        self.cookie = cookie.strip()
        self.min_interval = min_interval
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._cache: dict[str, str] = {}

    @property
    def logged_in(self) -> bool:
        return bool(self.cookie)

    # ---------------------------------------------------------------- http

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if self.cookie:
            value = self.cookie
            if "=" not in value:
                value = f"steamLoginSecure={value}"
            headers["Cookie"] = value
        return headers

    def get(self, url: str, use_cache: bool = True, retries: int = 3) -> str:
        if use_cache and url in self._cache:
            return self._cache[url]

        for attempt in range(retries):
            with self._lock:
                wait = self.min_interval - (time.monotonic() - self._last_request)
                if wait > 0:
                    time.sleep(wait)
                self._last_request = time.monotonic()

            request = urllib.request.Request(url, headers=self._headers())
            try:
                with urllib.request.urlopen(request, timeout=40) as response:
                    body = response.read().decode("utf-8", "replace")
                if use_cache:
                    self._cache[url] = body
                return body
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise WebError(n("web.http_error", code=exc.code, url=url)) from exc
            except urllib.error.URLError as exc:
                raise WebError(n("web.connect_failed", reason=exc.reason)) from exc

        raise RateLimited(n("web.rate_limited"))

    # -------------------------------------------------------------- session

    def validate_login(self) -> str:
        """Return the logged-in SteamID, or "" if the cookie is not active.

        Steam embeds `g_steamID = "7656…"` on authenticated pages and
        `g_steamID = false` otherwise -- a reliable liveness check.
        """
        if not self.cookie:
            return ""
        try:
            page = self.get(f"{self.profile_url}/badges/", use_cache=False)
        except WebError:
            return ""
        match = re.search(r'g_steamID\s*=\s*"(\d{17})"', page)
        return match.group(1) if match else ""

    # --------------------------------------------------------------- games

    def owned_games(self) -> list[tuple[int, str, float]]:
        """The full library as (app_id, name, hours) -- needs the cookie when
        the profile's game list is private, which is Steam's default."""
        page = self.get(f"{self.profile_url}/games/?tab=all&xml=1")
        if "<gamesList>" not in page:
            raise WebError(n("web.games_private"))

        games: list[tuple[int, str, float]] = []
        for block in re.findall(r"<game>(.*?)</game>", page, re.S):
            app_id = re.search(r"<appID>(\d+)</appID>", block)
            name = re.search(r"<name>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</name>", block, re.S)
            hours = re.search(r"<hoursOnRecord>([\d,.]+)</hoursOnRecord>", block)
            if not app_id:
                continue
            games.append(
                (
                    int(app_id.group(1)),
                    _clean(name.group(1)) if name else f"AppID {app_id.group(1)}",
                    float(hours.group(1).replace(",", "")) if hours else 0.0,
                )
            )
        return games

    # -------------------------------------------------------------- badges

    def level_info(self) -> LevelInfo:
        page = self.get(f"{self.profile_url}/badges/")
        info = LevelInfo()
        match = re.search(r'friendPlayerLevelNum">(\d+)<', page)
        if match:
            info.level = int(match.group(1))
        match = re.search(r"XP\s*([\d,]+)", page)
        if match:
            info.xp = int(match.group(1).replace(",", ""))
        match = re.search(r"([\d,]+)\s*XP to reach Level", page)
        if match:
            info.xp_to_next = int(match.group(1).replace(",", ""))
        return info

    def badges(self, max_pages: int = 20, progress=None) -> list[Badge]:
        """Every game badge on the profile. Without a cookie only completed
        badges are visible and drop counts come back as zero."""
        found: dict[int, Badge] = {}
        for page_number in range(1, max_pages + 1):
            if progress:
                progress(f"badges page {page_number}")
            url = f"{self.profile_url}/badges/?p={page_number}"
            page = self.get(url)

            page_badges = self._parse_badge_rows(page)
            for badge in page_badges:
                found.setdefault(badge.app_id, badge)

            if not page_badges or f"?p={page_number + 1}" not in page:
                break
        return list(found.values())

    def _parse_badge_rows(self, page: str) -> list[Badge]:
        badges: list[Badge] = []
        for block in re.split(r'<div[^>]*class="badge_row\b', page)[1:]:
            match = re.search(r"/gamecards/(\d+)", block)
            if not match:
                continue  # community badge (Years of Service etc.), not a card set
            app_id = int(match.group(1))

            badge = Badge(app_id=app_id, game_name="")
            # Steam pads its markup with newlines and tabs; flatten before matching.
            block = re.sub(r"\s+", " ", block)

            title = re.search(r'class="badge_title"> (.*?)(?:<span|</div>)', block)
            if title:
                badge.game_name = _clean(title.group(1))

            info_title = re.search(r'class="badge_info_title">(.*?)</div>', block)
            if info_title:
                badge.badge_name = _clean(info_title.group(1))

            level = re.search(r"Level (\d+),\s*([\d,]+)\s*XP", block)
            if level:
                badge.level = int(level.group(1))
                badge.xp = int(level.group(2).replace(",", ""))

            cards = re.search(r"(\d+)\s+of\s+(\d+)\s+cards", block)
            if cards:
                badge.cards_owned = int(cards.group(1))
                badge.cards_total = int(cards.group(2))

            drops = re.search(r"(\d+)\s+card drops remaining", block)
            if drops:
                badge.drops_remaining = int(drops.group(1))

            playtime = re.search(r"([\d,.]+)\s*hrs on record", block)
            if playtime:
                badge.playtime = playtime.group(1) + " hrs"

            badges.append(badge)
        return badges

    def card_set(self, app_id: int) -> tuple[list[Card], int]:
        """Cards for one game plus its remaining drop count."""
        page = self.get(f"{self.profile_url}/gamecards/{app_id}/")
        cards: list[Card] = []

        for raw_block in re.split(r'<div class="badge_card_set_card ', page)[1:]:
            owned_marker = raw_block[:40]
            block = re.sub(r"\s+", " ", raw_block)
            name = re.search(
                r'badge_card_set_title ellipsis">(.*?)<div style="clear', block
            )
            if not name:
                continue
            raw = name.group(1)
            quantity = re.search(r'badge_card_set_text_qty">\((\d+)\)', raw)
            label = _clean(re.sub(r"<[^>]+>", " ", raw))
            label = re.sub(r"^\(\d+\)\s*", "", label)

            index = re.search(r'badge_card_set_text ellipsis">\s*(\d+ of \d+[^<]*)', block)
            cards.append(
                Card(
                    name=label,
                    owned=int(quantity.group(1)) if quantity else (
                        0 if "unowned" in owned_marker else 1
                    ),
                    index=_clean(index.group(1)) if index else "",
                )
            )

        drops = re.search(r"(\d+)\s+card drops remaining", page)
        return cards, int(drops.group(1)) if drops else 0

    # -------------------------------------------------------------- prices

    def card_prices(self, app_id: int) -> dict[str, tuple[str, int | None]]:
        """All card prices for a game in one market request.

        Returns {card name: (display text, cents)}. Steam refuses these calls
        without a logged-in session, so this needs the cookie.
        """
        query = urllib.parse.urlencode(
            {
                "norender": 1,
                "appid": 753,
                "count": 100,
                "category_753_Game[]": f"tag_app_{app_id}",
                "category_753_item_class[]": CARD_ITEM_CLASS,
            }
        )
        raw = self.get(f"https://steamcommunity.com/market/search/render/?{query}")
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise WebError(n("web.bad_market")) from exc

        prices: dict[str, tuple[str, int | None]] = {}
        for result in data.get("results", []):
            hash_name = result.get("hash_name", "")
            # Market names are "<appid>-<card name>".
            name = hash_name.split("-", 1)[1] if "-" in hash_name else hash_name
            prices[name.strip().lower()] = (
                result.get("sell_price_text", ""),
                result.get("sell_price"),
            )
        return prices

    def attach_prices(self, badge: Badge) -> None:
        prices = self.card_prices(badge.app_id)
        for card in badge.cards:
            text, cents = prices.get(card.name.strip().lower(), ("", None))
            card.price_text = text
            card.price_cents = cents
