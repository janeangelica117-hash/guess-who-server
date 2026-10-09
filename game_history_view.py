"""
game_history_view.py — turns the gameplay log (logs/gameplay.log, one JSON
object per finished/abandoned game) into a web page that shows the actual
card pictures next to each game.

Two ways to use it:

  1. On the server — server.py wires it up as two admin routes (same
     ADMIN_KEY as /admin/game-history):

        /admin/game-history/view?key=...            the picture page
        /admin/card-image/<category>/<card>?key=... serves one card's image

     The server needs the images/ folder next to server.py (same layout as
     the game: images/cartoons/..., images/fruits/..., images/desserts/...).
     Any card whose picture isn't found still shows up, as a name tile.

  2. On your own machine, from the project folder (the one with images/):

        python game_history_view.py                      # reads logs/gameplay.log
        python game_history_view.py my.log out.html      # explicit paths

     That writes one standalone .html file with the pictures embedded, so
     you can open it straight from disk — handy if you've copied
     gameplay.log down from the host.

Everything that came from a player (names, descriptions, questions) is
HTML-escaped before it's put on the page.
"""
import base64
import html
import json
import mimetypes
import os
import sys
from urllib.parse import quote

try:
    # Pure data (no pygame) — same lists the game itself uses.
    from categories import CATEGORIES, CATEGORY_ORDER
except Exception:           # categories.py or its card files missing
    CATEGORIES, CATEGORY_ORDER = {}, []

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
_IMAGE_EXTS  = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
_esc         = lambda s: html.escape(str(s if s is not None else ""), quote=True)


# ── reading the log ─────────────────────────────────────────────────────────

def read_events(json_path, limit=100):
    """Newest-first list of the last `limit` gameplay events. Reads the
    rotated backups too (gameplay.log.1 ... .N), so a log that just rolled
    over doesn't look empty."""
    paths = []
    i = 1
    while os.path.exists(f"{json_path}.{i}"):
        i += 1
    paths.extend(f"{json_path}.{n}" for n in range(i - 1, 0, -1))   # oldest backup first
    if os.path.exists(json_path):
        paths.append(json_path)

    events = []
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(ev, dict):
                        events.append(ev)
        except OSError:
            continue
    events.reverse()
    return events[:limit]


# ── card lookup ─────────────────────────────────────────────────────────────

def find_card(category, name):
    """-> (category_key, card_dict) or (None, None). Tries the game's own
    category first, then the rest (1v1 logs can have category=None)."""
    name = (name or "").strip()
    if not name or not CATEGORIES:
        return None, None
    order = ([category] if category in CATEGORIES else []) + \
            [k for k in CATEGORY_ORDER if k != category]
    for key in order:
        for card in CATEGORIES[key]["cards"]:
            if card["name"] == name:
                return key, card
    return None, None


def card_image_path(category, name):
    """Absolute path of a card's picture on disk, or None. Matches the file
    name case-insensitively — the card lists say 'tom.jpg' but the files may
    be 'tom.JPG', which works on Windows and silently fails on a Linux host."""
    _key, card = find_card(category, name)
    if not card:
        return None
    full = os.path.join(BASE_DIR, card.get("image", ""))
    if os.path.isfile(full):
        return full
    folder, fname = os.path.split(full)
    if not os.path.isdir(folder):
        return None
    stem = os.path.splitext(fname)[0].lower()
    for f in os.listdir(folder):
        base, ext = os.path.splitext(f)
        if base.lower() == stem and ext.lower() in _IMAGE_EXTS:
            return os.path.join(folder, f)
    return None


def _label(category):
    if category in CATEGORIES:
        return CATEGORIES[category]["label"]
    return category or "?"


def _fmt_duration(seconds):
    if seconds is None:
        return "?"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


# ── page building ───────────────────────────────────────────────────────────

class _Images:
    """Hands out card thumbnails. Each distinct picture is written into the
    page's <style> once (as a CSS class) however many games use it."""

    def __init__(self, src_for):
        self.src_for = src_for      # (category_key, card_name) -> url/data-URI or None
        self.ids = {}
        self.css = []

    def thumb(self, name, category, caption=""):
        name = (name or "").strip()
        cat_key, card = find_card(category, name)
        src = self.src_for(cat_key, card["name"]) if card else None
        if src:
            key = (cat_key, card["name"])
            if key not in self.ids:
                self.ids[key] = f"c{len(self.ids)}"
                self.css.append(f'.{self.ids[key]}{{background-image:url("{src.replace(chr(34), "%22")}")}}')
            tile = f'<div class="thumb {self.ids[key]}" title="{_esc(name)}"></div>'
        else:
            tile = f'<div class="thumb missing" title="{_esc(name)}"><span>{_esc(name or "?")}</span></div>'
        cap = f'<span class="cap">{_esc(caption)}</span>' if caption else ""
        return f'<figure class="card">{tile}<figcaption><b>{_esc(name or "?")}</b>{cap}</figcaption></figure>'


def _qa_lines(transcript):
    """1v1 questions/answers -> readable rows."""
    rows, qn = [], 0
    for e in transcript or []:
        if e.get("type") == "question":
            qn += 1
            rows.append(f'<li><b>Q{qn}.</b> {_esc(e.get("player", "?"))}: &ldquo;{_esc(e.get("text", ""))}&rdquo;</li>')
        elif e.get("type") == "answer":
            yn = "YES" if e.get("yes") else "NO"
            cls = "yes" if e.get("yes") else "no"
            rows.append(f'<li class="ans"><span class="{cls}">{yn}</span> &mdash; {_esc(e.get("player", "?"))}</li>')
    return f'<ul class="qa">{"".join(rows)}</ul>' if rows else '<p class="mute">No questions recorded.</p>'


def _game(tag, tag_cls, title, meta, chip, thumbs, body, open_=False):
    chip_html = f'<span class="chip {chip[1]}">{_esc(chip[0])}</span>' if chip else ""
    return (
        f'<details class="game"{" open" if open_ else ""}><summary>'
        f'<div class="head"><span class="tag {tag_cls}">{_esc(tag)}</span>'
        f'<span class="title">{_esc(title)}</span>{chip_html}'
        f'<span class="meta">{_esc(meta)}</span></div>'
        f'<div class="cards">{thumbs}</div></summary>'
        f'<div class="body">{body}</div></details>'
    )


def _render_1v1(ev, imgs, open_):
    abandoned = ev["event"] == "match_abandoned"
    pl = list(ev.get("players") or ["?", "?"]) + ["?", "?"]
    a, b = pl[0], pl[1]
    cat = ev.get("category")
    secrets = ev.get("secrets") or {}

    thumbs = "".join(imgs.thumb(secrets[p], cat, f"{p}'s secret") for p in (a, b) if secrets.get(p))
    if not thumbs:
        thumbs = '<span class="mute">No secret cards recorded.</span>'

    if abandoned:
        chip = (f'{ev.get("left_by", "?")} left', "orange")
        result = f'<p><b>Abandoned:</b> {_esc(ev.get("left_by", "?"))} left ({_esc(ev.get("reason", "left"))}).</p>'
    else:
        res = ev.get("result", "?")
        chip = (f'{ev.get("reported_by", "?")} reported {res}', "green" if res == "WIN" else "orange")
        result = (f'<p><b>Result:</b> {_esc(ev.get("reported_by", "?"))} reported {_esc(res)}'
                  f' &mdash; {_esc(ev.get("reason", ""))}</p>')

    return _game(
        "1v1 ABANDONED" if abandoned else "1v1", "oneonone",
        f"{a} vs {b} · {_label(cat)}",
        f'{ev.get("ts", "")} · {_fmt_duration(ev.get("duration_sec"))}',
        chip, thumbs, _qa_lines(ev.get("transcript")) + result, open_)


def _render_imposter(ev, imgs, open_):
    abandoned = ev["event"] == "imposter_match_abandoned"
    members = ev.get("members") or []
    roles = ev.get("roles") or {}
    cat = ev.get("category")

    thumbs = ""
    if ev.get("real_card"):
        thumbs += imgs.thumb(ev["real_card"], cat, "Innocents' card")
    if ev.get("imposter_card"):
        thumbs += imgs.thumb(ev["imposter_card"], cat, "Imposter's card at start")
    if not thumbs:
        thumbs = '<span class="mute">No cards recorded.</span>'

    players = "".join(
        f'<span class="player {_esc(roles.get(m, "unknown"))}">{_esc(m)}'
        f'<i>{_esc(roles.get(m, ""))}</i></span>' for m in members)

    by_round, order = {}, []
    for e in ev.get("transcript") or []:
        r = e.get("round")
        if r not in by_round:
            by_round[r] = []
            order.append(r)
        by_round[r].append(f'<li><b>{_esc(e.get("player", "?"))}:</b> {_esc(e.get("text", ""))}</li>')
    transcript = "".join(f'<h4>Round {_esc(r)}</h4><ul>{"".join(by_round[r])}</ul>' for r in order) \
        or '<p class="mute">No descriptions recorded.</p>'

    powers = ""
    if ev.get("powers"):
        rows = "".join(
            f'<li>Round {_esc(p.get("round", "?"))} &middot; <b>{_esc(p.get("player", "?"))}</b> used '
            f'{_esc(p.get("label", p.get("power", "?")))} ({_esc(p.get("cost", "?"))} pts) '
            f'&mdash; {_esc(p.get("detail", ""))}</li>' for p in ev["powers"])
        powers = f'<h4>Powers used</h4><ul>{rows}</ul>'

    votes = ""
    if ev.get("votes"):
        rows = "".join(f'<li>{_esc(v)} voted <b>{_esc(a)}</b></li>' for v, a in ev["votes"].items())
        votes = f'<h4>Votes</h4><ul>{rows}</ul>'

    if abandoned:
        chip = (f'{ev.get("last_to_leave", "?")} was last to leave', "orange")
        outcome = ""
    else:
        w = ev.get("winner")
        chip = {"innocents": ("Innocents win", "green"),
                "original_imposter": ("Original imposter wins (swap)", "gold")}.get(w, ("Imposter wins", "red"))
        if w == "original_imposter":
            outcome = (f'<p><b>Winner:</b> {_esc(ev.get("original_imposter", "?"))} was voted out, but the '
                       f'Imposter title had been swapped onto {_esc(ev.get("imposter", "?"))}.</p>')
        else:
            outcome = (f'<p><b>Winner:</b> {"Innocents" if w == "innocents" else "Imposter"} '
                       f'({_esc(ev.get("imposter", "?"))} was {"caught" if ev.get("caught") else "not caught"}).</p>')

    return _game(
        "IMPOSTER ABANDONED" if abandoned else "IMPOSTER", "imposter",
        f"{len(members)} players · {_label(cat)}",
        f'{ev.get("ts", "")} · {_fmt_duration(ev.get("duration_sec"))}',
        chip, thumbs,
        f'<div class="players">{players}</div>{transcript}{powers}{votes}{outcome}', open_)


def _render_other(ev, open_):
    extras = ", ".join(f"{k}={v}" for k, v in ev.items() if k not in ("ts", "event"))
    return _game(str(ev.get("event", "event")).upper(), "other", "", ev.get("ts", ""), None, "",
                 f'<p class="mute">{_esc(extras)}</p>', open_)


_CSS = """
body{margin:0;background:#2314aa;color:#f2f0ff;font:15px/1.45 system-ui,"Segoe UI",Arial,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:18px 14px 60px}
h1{margin:0 0 4px;font-size:26px;letter-spacing:.5px}
h1 span{color:#fad14c}
h4{margin:14px 0 4px;color:#fad14c;font-size:13px;letter-spacing:1px;text-transform:uppercase}
a{color:#8fe3ff}
.top{margin-bottom:16px;color:#b9b4e6}
.mute{color:#b9b4e6}
details.game{background:#2d1f7d;border:2px solid #120a45;border-radius:14px;margin:0 0 14px;overflow:hidden}
summary{list-style:none;cursor:pointer;padding:12px 14px}
summary::-webkit-details-marker{display:none}
.head{margin-bottom:8px}
.head span{display:inline-block;vertical-align:middle;margin:2px 8px 2px 0}
.tag{font-size:11px;font-weight:700;letter-spacing:1px;padding:3px 9px;border-radius:99px;background:#46a4ff;color:#06123a}
.tag.imposter{background:#e3524f;color:#fff}
.tag.other{background:#8a86b8;color:#fff}
.title{font-weight:700;font-size:16px}
.meta{color:#b9b4e6;font-size:13px}
.chip{font-size:12px;font-weight:700;padding:3px 10px;border-radius:99px;color:#fff;background:#555}
.chip.green{background:#2e9e5c}.chip.red{background:#cf4440}.chip.orange{background:#d9822b}.chip.gold{background:#fad14c;color:#2a2000}
.cards{font-size:0}
figure.card{display:inline-block;vertical-align:top;margin:4px 12px 4px 0;width:132px}
.thumb{width:132px;height:100px;border-radius:8px;border:3px solid #fff7dc;background:#c9b6a3 center/cover no-repeat}
.thumb.missing{text-align:center;display:table}
.thumb.missing span{display:table-cell;vertical-align:middle;color:#3b2a1a;font-size:13px;font-weight:700;padding:6px}
figcaption{font-size:13px;line-height:1.25;padding-top:3px}
figcaption b{display:block;color:#fff}
.cap{display:block;color:#b9b4e6;font-size:12px}
.body{padding:2px 16px 14px;border-top:1px solid #46399a;background:#261a6b}
.body ul{margin:4px 0;padding-left:20px}
.body li{margin:2px 0}
ul.qa{list-style:none;padding-left:0}
ul.qa li.ans{padding-left:22px;color:#cfcaf5}
.yes{color:#58d68d;font-weight:700}.no{color:#ff8a85;font-weight:700}
.players{margin:10px 0 2px}
.player{display:inline-block;margin:0 6px 6px 0;padding:3px 11px;border-radius:99px;background:#46399a;font-weight:700}
.player i{font-style:normal;font-weight:400;font-size:12px;margin-left:6px;color:#d6d2ff}
.player.imposter{background:#cf4440}.player.innocent{background:#2e7d52}
"""


def render_page(events, src_for, plain_text_url=None, limit_note=""):
    """`src_for(category_key, card_name)` decides how a picture is referenced
    on the page — a URL when served by the server, a data: URI when saved to
    a standalone file."""
    imgs = _Images(src_for)
    blocks = []
    for i, ev in enumerate(events):
        kind = ev.get("event")
        if kind in ("match_end", "match_abandoned"):
            blocks.append(_render_1v1(ev, imgs, i == 0))
        elif kind in ("imposter_match_end", "imposter_match_abandoned"):
            blocks.append(_render_imposter(ev, imgs, i == 0))
        else:
            blocks.append(_render_other(ev, i == 0))

    if not blocks:
        blocks = ['<p class="mute">No games recorded yet.</p>']

    links = f' &middot; <a href="{_esc(plain_text_url)}">Plain text version</a>' if plain_text_url else ""
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Guess Who? &mdash; Game History</title>'
        f'<style>{_CSS}{"".join(imgs.css)}</style></head><body><div class="wrap">'
        '<h1>Game <span>History</span></h1>'
        f'<div class="top">{len(events)} game(s), newest first{_esc(limit_note)}{links}. Click a game to expand it.</div>'
        f'{"".join(blocks)}</div></body></html>'
    )


# ── server mode: pictures are served by /admin/card-image ───────────────────

def server_image_src(key):
    def src_for(cat_key, name):
        if not card_image_path(cat_key, name):
            return None     # not on this server -> name tile instead of a broken image
        return f"/admin/card-image/{quote(cat_key, safe='')}/{quote(name, safe='')}?key={quote(key, safe='')}"
    return src_for


# ── standalone mode: pictures embedded in the file ──────────────────────────

def _data_uri_src(cat_key, name):
    path = card_image_path(cat_key, name)
    if not path:
        return None
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as fh:
        return f"data:{mime};base64,{base64.b64encode(fh.read()).decode('ascii')}"


if __name__ == "__main__":
    log_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE_DIR, "logs", "gameplay.log")
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE_DIR, "game_history.html")
    evs = read_events(log_path, limit=500)
    page = render_page(evs, _data_uri_src)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"Wrote {len(evs)} game(s) to {out_path}")