"""
APEX CLAN - Discord Bot
========================================
Commands:
    !help                           — list all commands
    !register <ingame_username>     — link your Discord to your in-game name
    !unregister <ingame_username>   — admin only: remove/correct a registration
    !stats <username>               — look up any member's stats
    !mystats                        — your own stats (requires !register first)
    !armory                         — view clan armory inventory
    !armory request <item name>     — request to borrow an item
    !weeklysummary                  — admin only: post weekly summary image
    !applyofficer                   — apply for Officer promotion (checks eligibility first)
    !assignroles                    — admin only: assign Discord roles by SP rank

Auto role assignment:
    Run apex_assign_roles() manually or call it after your weekly calc.
    Requires Discord roles named exactly: Scout, Apex Scout, Ranger,
    Apex Ranger, Templar, Apex Templar, Officer, Apex Officer, Axiom

Requirements:
    pip install discord.py python-dotenv

.env file (same folder):
    DISCORD_TOKEN=your_token_here
    DB_FILE=apex_clan_v2.db
    ADMIN_DISCORD_ID=your_discord_user_id

Run:
    python apex_discord_bot.py
"""

import discord
from discord.ext import commands, tasks
import asyncio
import sqlite3
import os
import io
import urllib.request
import json as _json
from datetime import datetime, date
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

load_dotenv()

TOKEN          = os.getenv("DISCORD_TOKEN")
DB_FILE        = os.getenv("DB_FILE", "apex_clan_v2.db")
ADMIN_ID       = int(os.getenv("ADMIN_DISCORD_ID", "0"))

ARMORY_SHEET_ID        = "1BJKCAruFvG4Q8gGpo1VMequJwAjthupQO9Ne-FexKw0"
ARMORY_API_KEY         = os.getenv("ARMORY_API_KEY")
ARMORY_TAB             = "Sheet1"
ARMORY_REQUEST_CHANNEL = "armory-requests"
PROMOTION_APP_CHANNEL  = "officer-applications"
ACOL = {"name":3, "borrowed_by":10, "due_date":12, "rank":15}

# Officer promotion requirements
OFFICER_MIN_RANK     = "Ranger"
OFFICER_DISCORD_ROLE = "Regular"
OFFICER_MIN_MEDALS   = 4

# Application questions (replace with real questions when ready)
OFFICER_APP_QUESTIONS = [
    "Why do you want to become an Officer in APEX?",
    "What did you contribute to the clan beyond your stats in the past 3 months?",
    "What skills (not DF related) do you bring to the table?",
    "Describe 3 moments where you helped another clan member.",
    "What would you like to change within APEX, how would you facilitate this change as an Officer?",
]

# All valid SP rank names (must match Discord role names exactly)
# Ordered lowest → highest (used for rank-up comparisons and armory checks)
SP_RANKS = [
    "Scout", "Apex Scout", "Ranger", "Apex Ranger",
    "Templar", "Apex Templar", "Officer", "Apex Officer", "Axiom"
]

RANK_COLORS = {
    "axiom":        0xc9b8ff,
    "apex officer": 0xffd700,
    "officer":      0xffe680,
    "apex templar": 0xff9999,
    "templar":      0xff8080,
    "apex ranger":  0x99bbff,
    "ranger":       0x74b9ff,
    "apex scout":   0x90ee90,
    "scout":        0x55efc4,
}

RANK_NEXT = {
    "Scout":        ("Apex Scout",   50),
    "Apex Scout":   ("Ranger",       120),
    "Ranger":       ("Apex Ranger",  200),
    "Apex Ranger":  ("Templar",      300),
    "Templar":      ("Apex Templar", 400),
    "Apex Templar": (None,           None),
    "Officer":      (None,           None),
    "Apex Officer": (None,           None),
    "Axiom":        (None,           None),
}

TIER_EMOJI = {"Bronze": "🟫", "Silver": "⬜", "Gold": "🟨", "Platinum": "🔷"}
CAT_LABEL  = {
    "ts":     "TS ⚔️",
    "tpk":    "TPK 💀",
    "tl":     "TL 📦",
    "streak": "Streak 🔥",
    "global": "Global 🌍",
}

# ══════════════════════════════════════════════
#  DB HELPERS
# ══════════════════════════════════════════════
def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def safe_int(v, default=0):
    try: return int(float(v)) if v not in (None, "", "-") else default
    except: return default

def safe_float(v, default=0.0):
    try: return float(v) if v not in (None, "", "-") else default
    except: return default

def fmt(n):
    n = float(n or 0)
    if n >= 1_000_000_000: return f"{n/1_000_000_000:.2f}B"
    if n >= 1_000_000:     return f"{n/1_000_000:.1f}M"
    if n >= 1_000:         return f"{n/1_000:.1f}K"
    return str(int(n))

def progress_bar(pct, length=10):
    filled = round(pct / 100 * length)
    return "█" * filled + "░" * (length - filled) + f" {pct:.0f}%"

def get_current_week(conn):
    row = conn.execute(
        "SELECT week FROM weekly_analysis ORDER BY week DESC LIMIT 1"
    ).fetchone()
    return row["week"] if row else None

def ensure_discord_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS discord_members (
            discord_id   TEXT PRIMARY KEY,
            username     TEXT NOT NULL,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

def find_username(conn, query):
    query = query.strip()
    for sql in [
        "SELECT DISTINCT username FROM weekly_snapshots WHERE username = ?",
        "SELECT DISTINCT username FROM weekly_snapshots WHERE LOWER(username) = LOWER(?)",
        "SELECT DISTINCT username FROM weekly_snapshots WHERE LOWER(username) LIKE LOWER(?)",
    ]:
        q = query if "LIKE" not in sql else f"%{query}%"
        row = conn.execute(sql, (q,)).fetchone()
        if row: return row["username"]
    return None

def get_ingame_name(conn, discord_id):
    ensure_discord_table(conn)
    row = conn.execute(
        "SELECT username FROM discord_members WHERE discord_id = ?", (str(discord_id),)
    ).fetchone()
    return row["username"] if row else None

# ══════════════════════════════════════════════
#  REGISTRATION
# ══════════════════════════════════════════════
def register_member(conn, discord_id, ingame_username):
    ensure_discord_table(conn)
    conn.execute("""
        INSERT INTO discord_members (discord_id, username)
        VALUES (?, ?)
        ON CONFLICT(discord_id) DO UPDATE SET username = excluded.username, registered_at = CURRENT_TIMESTAMP
    """, (str(discord_id), ingame_username))
    conn.commit()

def unregister_member(conn, ingame_username):
    ensure_discord_table(conn)
    conn.execute("DELETE FROM discord_members WHERE username = ?", (ingame_username,))
    conn.commit()

# ══════════════════════════════════════════════
#  MEDALS
# ══════════════════════════════════════════════
def get_player_medals(conn, username):
    medal_defs = conn.execute(
        "SELECT category, tier, threshold, sort_order FROM medal_definitions ORDER BY category, sort_order ASC"
    ).fetchall()
    thresholds = {}
    for r in medal_defs:
        thresholds.setdefault(r["category"], []).append((r["tier"], safe_int(r["threshold"])))

    snaps = conn.execute(
        "SELECT weekly_ts, weekly_tpk, weekly_loots FROM weekly_snapshots WHERE username=?",
        (username,)
    ).fetchall()

    best_streak = conn.execute(
        "SELECT MAX(best_streak) as bs FROM weekly_analysis WHERE username=?", (username,)
    ).fetchone()
    best_streak_val = safe_int(best_streak["bs"]) if best_streak else 0

    best_global = None
    for r in conn.execute(
        "SELECT weekly_ts_rank, weekly_tpk_rank, weekly_tl_rank FROM weekly_snapshots WHERE username=?",
        (username,)
    ).fetchall():
        for col in ("weekly_ts_rank", "weekly_tpk_rank", "weekly_tl_rank"):
            val = r[col]
            if val:
                try:
                    n = int(str(val).replace("#", "").strip())
                    if n > 0:
                        best_global = min(best_global or 9999, n)
                except: pass

    col_map = {"ts": "weekly_ts", "tpk": "weekly_tpk", "tl": "weekly_loots"}
    medals = []

    for cat, tiers in thresholds.items():
        if cat in col_map:
            col = col_map[cat]
            best_val = max((safe_int(r[col]) for r in snaps), default=0)
            for tier, thresh in reversed(tiers):
                if best_val >= thresh:
                    medals.append(f"{TIER_EMOJI.get(tier,'🏅')} {tier} {CAT_LABEL.get(cat, cat)}")
                    break
        elif cat == "streak":
            for tier, thresh in reversed(tiers):
                if best_streak_val >= thresh:
                    medals.append(f"{TIER_EMOJI.get(tier,'🏅')} {tier} {CAT_LABEL.get(cat, cat)}")
                    break
        elif cat == "global" and best_global:
            for tier, thresh in reversed(tiers):
                if best_global <= thresh:
                    medals.append(f"{TIER_EMOJI.get(tier,'🏅')} {tier} {CAT_LABEL.get(cat, cat)}")
                    break

    wins = conn.execute(
        "SELECT COUNT(*) as c FROM event_rewards WHERE username=? AND event_id NOT LIKE 'W%'",
        (username,)
    ).fetchone()
    if wins and safe_int(wins["c"]) > 0:
        medals.append(f"🏆 Event Winner ×{safe_int(wins['c'])}")

    return medals

# ══════════════════════════════════════════════
#  IMAGE CARD GENERATOR
# ══════════════════════════════════════════════
def _font(candidates, size):
    """Try each font path in order, fall back gracefully."""
    for path in candidates:
        try: return ImageFont.truetype(path, size)
        except: pass
    return ImageFont.load_default()

# Font candidates: Windows paths first, Linux fallback
_BOLD    = ["C:/Windows/Fonts/arialbd.ttf",   "C:/Windows/Fonts/calibrib.ttf",
            "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
_REG     = ["C:/Windows/Fonts/arial.ttf",     "C:/Windows/Fonts/calibri.ttf",
            "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
_MEDIUM  = ["C:/Windows/Fonts/arial.ttf",     "C:/Windows/Fonts/calibri.ttf",
            "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
_MONO    = ["C:/Windows/Fonts/consola.ttf",   "C:/Windows/Fonts/cour.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"]
_MONO_SM = ["C:/Windows/Fonts/consola.ttf",   "C:/Windows/Fonts/cour.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"]

_fnt_title    = _font(_BOLD,    30)
_fnt_rank     = _font(_BOLD,    18)
_fnt_label    = _font(_MEDIUM,  11)
_fnt_value    = _font(_BOLD,    22)
_fnt_sub      = _font(_REG,     12)
_fnt_mono     = _font(_MONO,    12)
_fnt_mono_sm  = _font(_MONO_SM, 11)
_fnt_medal    = _font(_BOLD,    10)
_fnt_event    = _font(_MEDIUM,  11)

_CARD_BG      = (10, 10, 10)
_CARD_SECTION = (28, 28, 28)
_CARD_GOLD    = (241, 196, 15)
_CARD_GREEN   = (46, 204, 113)
_CARD_MUTED   = (107, 96, 85)
_CARD_TEXT    = (212, 201, 184)
_CARD_WHITE   = (255, 255, 255)
_CARD_RED     = (231, 76, 60)

_CARD_RANK_COLORS = {
    "axiom":        (201, 184, 255),
    "apex officer": (255, 215,   0),
    "officer":      (255, 230, 128),
    "apex templar": (255, 153, 153),
    "templar":      (255, 128, 128),
    "apex ranger":  (153, 187, 255),
    "ranger":       (116, 185, 255),
    "apex scout":   (144, 238, 144),
    "scout":        ( 85, 239, 196),
}

_TIER_COLORS = {
    "Platinum": (116, 185, 255),
    "Gold":     (241, 196,  15),
    "Silver":   (189, 195, 199),
    "Bronze":   (176, 106,  53),
}

_CARD_W, _CARD_H = 540, 450

def _draw_progress_bar(draw, x, y, w, pct, col):
    h = 8
    draw.rectangle([x, y, x+w, y+h], fill=(40,40,40))
    fw = int(w * min(pct, 100) / 100)
    if fw > 0:
        draw.rectangle([x, y, x+fw, y+h], fill=col)
        if fw > 3:
            draw.rectangle([x+fw-3, y, x+fw, y+h], fill=tuple(min(255, c+80) for c in col))

def _draw_stat_box(draw, x, y, w, h, label, value, sub, sp_gained, rank_col):
    draw.rectangle([x, y, x+w, y+h], fill=_CARD_SECTION)
    draw.rectangle([x, y, x+w, y+3], fill=rank_col)
    lx = x + 10
    draw.text((lx, y+10), label,    font=_fnt_label, fill=_CARD_MUTED)
    draw.text((lx, y+26), value,    font=_fnt_value, fill=_CARD_WHITE)
    draw.text((lx, y+52), sub,      font=_fnt_sub,   fill=_CARD_MUTED)
    sp_col = _CARD_GREEN if (sp_gained and float(sp_gained.replace("+","").replace(" SP","")) > 0) else _CARD_MUTED
    draw.text((lx, y+68), sp_gained or "+0 SP", font=_fnt_mono, fill=sp_col)

def _draw_circle_medal(draw, cx, cy, r, tier, label):
    col  = _TIER_COLORS.get(tier, _CARD_MUTED)
    dark = tuple(max(0, c - 90) for c in col)
    mid  = tuple(max(0, c - 40) for c in col)
    for i in range(3, 0, -1):
        glow = tuple(max(0, c - 130 + i*10) for c in col)
        draw.ellipse([cx-r-i, cy-r-i, cx+r+i, cy+r+i], outline=glow, width=1)
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=dark)
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=col, width=2)
    draw.ellipse([cx-r+5, cy-r+5, cx+r-5, cy+r-5], outline=mid, width=1)
    lbl_w = draw.textlength(label, font=_fnt_medal)
    draw.text((cx - lbl_w/2, cy - 6), label, font=_fnt_medal, fill=_CARD_WHITE)

def _draw_event_badge(draw, x, y, text, height=52):
    col  = _CARD_GOLD
    dark = (55, 42, 0)
    tw   = int(draw.textlength(text, font=_fnt_event))
    pw   = tw + 20
    draw.rounded_rectangle([x, y, x+pw, y+height], radius=height//2, fill=dark)
    draw.rounded_rectangle([x, y, x+pw, y+height], radius=height//2, outline=col, width=2)
    ty = y + (height - 14) // 2
    draw.text((x+10, ty), text, font=_fnt_event, fill=col)
    return pw

def _get_medals_for_card(conn, username):
    """Returns list of (tier, label) tuples for the image card."""
    medal_defs = conn.execute(
        "SELECT category, tier, threshold, sort_order FROM medal_definitions ORDER BY category, sort_order ASC"
    ).fetchall()
    thresholds = {}
    for r in medal_defs:
        thresholds.setdefault(r["category"], []).append((r["tier"], safe_int(r["threshold"])))

    snaps = conn.execute(
        "SELECT weekly_ts, weekly_tpk, weekly_loots FROM weekly_snapshots WHERE username=?",
        (username,)
    ).fetchall()

    best_streak = conn.execute(
        "SELECT MAX(best_streak) as bs FROM weekly_analysis WHERE username=?", (username,)
    ).fetchone()
    best_streak_val = safe_int(best_streak["bs"]) if best_streak else 0

    best_global = None
    for r in conn.execute(
        "SELECT weekly_ts_rank, weekly_tpk_rank, weekly_tl_rank FROM weekly_snapshots WHERE username=?",
        (username,)
    ).fetchall():
        for col in ("weekly_ts_rank", "weekly_tpk_rank", "weekly_tl_rank"):
            val = r[col]
            if val:
                try:
                    n = int(str(val).replace("#", "").strip())
                    if n > 0:
                        best_global = min(best_global or 9999, n)
                except: pass

    col_map    = {"ts": "weekly_ts", "tpk": "weekly_tpk", "tl": "weekly_loots"}
    cat_labels = {"ts": "TS", "tpk": "TPK", "tl": "TL", "streak": "Streak", "global": "Global"}
    medals = []
    TIER_ORDER = {"Platinum": 0, "Gold": 1, "Silver": 2, "Bronze": 3}
    CAT_ORDER  = {"ts": 0, "tpk": 1, "tl": 2, "streak": 3, "global": 4}

    for cat, tiers in thresholds.items():
        if cat in col_map:
            col = col_map[cat]
            best_val = max((safe_int(r[col]) for r in snaps), default=0)
            for tier, thresh in reversed(tiers):
                if best_val >= thresh:
                    medals.append((tier, cat_labels.get(cat, cat), CAT_ORDER.get(cat, 99), TIER_ORDER.get(tier, 99)))
                    break
        elif cat == "streak":
            for tier, thresh in reversed(tiers):
                if best_streak_val >= thresh:
                    medals.append((tier, "Streak", CAT_ORDER.get("streak", 99), TIER_ORDER.get(tier, 99)))
                    break
        elif cat == "global" and best_global:
            for tier, thresh in reversed(tiers):
                if best_global <= thresh:
                    medals.append((tier, "Global", CAT_ORDER.get("global", 99), TIER_ORDER.get(tier, 99)))
                    break

    # Sort: exact category order TS > TPK > TL > Streak > Global, then tier within
    CAT_FIXED = {"TS": 0, "TPK": 1, "TL": 2, "Streak": 3, "Global": 4}
    medals.sort(key=lambda x: (CAT_FIXED.get(x[1], 99), x[3]))
    medals = [(tier, lbl) for tier, lbl, _, _ in medals]

    wins = conn.execute(
        "SELECT COUNT(*) as c FROM event_rewards WHERE username=? AND event_id NOT LIKE 'W%'",
        (username,)
    ).fetchone()
    if wins and safe_int(wins["c"]) > 0:
        medals.append(("Event", f"Event Winner x{safe_int(wins['c'])}"))

    return medals

def generate_stats_card(data: dict) -> bytes:
    _RANK_BG = {
        "axiom":        "bg_axiom.png",
        "apex officer": "bg_officer.png",
        "officer":      "bg_officer.png",
        "apex templar": "bg_templar.png",
        "templar":      "bg_templar.png",
        "apex ranger":  "bg_ranger.png",
        "ranger":       "bg_ranger.png",
        "apex scout":   "bg_scout.png",
        "scout":        "bg_scout.png",
    }

    bg_path    = _RANK_BG.get(data["sp_rank"].lower(), None)
    has_bg     = False
    if bg_path:
        try:
            img    = Image.open(bg_path).convert("RGBA").resize((_CARD_W, _CARD_H), Image.LANCZOS)
            # Subtle global darkening so text always readable
            dimmer = Image.new("RGBA", (_CARD_W, _CARD_H), (0, 0, 0, 100))
            img    = Image.alpha_composite(img, dimmer)
            has_bg = True
        except FileNotFoundError:
            img = Image.new("RGBA", (_CARD_W, _CARD_H), _CARD_BG + (255,))
    else:
        img = Image.new("RGBA", (_CARD_W, _CARD_H), _CARD_BG + (255,))

    W, H     = _CARD_W, _CARD_H
    rank_col = _CARD_RANK_COLORS.get(data["sp_rank"].lower(), _CARD_RED)

    # ── Semi-transparent box overlay (only drawn when there's a background) ──
    # BOX_ALPHA: 0 = fully see-through, 255 = fully solid. 160 is a good midpoint.
    BOX_ALPHA = 160 if has_bg else 255

    overlay      = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    box_y = 193
    box_h = 92
    gap   = 5
    box_w = (W - 40 - gap*2) // 3

    # Stat boxes
    for i in range(3):
        bx = 20 + i * (box_w + gap)
        overlay_draw.rectangle([bx, box_y, bx+box_w, box_y+box_h],
                                fill=_CARD_SECTION + (BOX_ALPHA,))

    # Footer bar
    overlay_draw.rectangle([4, H-26, W-4, H-4], fill=(14, 14, 14, BOX_ALPHA + 40))

    # Header area subtle tint (top ~120px) so text is always readable over busy backgrounds
    if has_bg:
        overlay_draw.rectangle([0, 0, W, 120], fill=(0, 0, 0, 80))

    img = Image.alpha_composite(img, overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── Borders ──
    draw.rectangle([0,   0,   4,   H  ], fill=rank_col)
    draw.rectangle([W-4, 0,   W,   H  ], fill=rank_col)
    draw.rectangle([0,   0,   W,   4  ], fill=rank_col)
    draw.rectangle([0,   H-4, W,   H  ], fill=rank_col)

    draw.text((20, 14), data["username"], font=_fnt_title, fill=_CARD_WHITE)
    draw.text((20, 52), f"{data['sp_rank']}  ·  Lv. {data['level']}", font=_fnt_rank, fill=rank_col)

    sp_txt  = f"{data['sp']:.1f} SP"
    chg     = data["sp_change"]
    chg_col = _CARD_GREEN if chg >= 0 else _CARD_RED
    chg_txt = (f"+{chg:.1f}" if chg >= 0 else f"{chg:.1f}") + " this week"
    draw.text((20, 76), sp_txt, font=_fnt_rank, fill=_CARD_GOLD)
    sp_w = draw.textlength(sp_txt, font=_fnt_rank)
    draw.text((20 + sp_w + 10, 80), chg_txt, font=_fnt_sub, fill=chg_col)

    s     = data["streak"]
    s_col = _CARD_RED if s >= 4 else (_CARD_GOLD if s >= 2 else _CARD_MUTED)
    draw.text((20, 100), f"STREAK: {s} weeks  (best: {data['best_streak']})", font=_fnt_sub, fill=s_col)

    draw.rectangle([20, 124, W-20, 125], fill=(40, 40, 40))
    draw.text((20, 132), "RANK PROGRESS", font=_fnt_label, fill=_CARD_MUTED)

    pct    = data["progress_pct"]
    next_r = data["next_rank"]
    _draw_progress_bar(draw, 20, 150, W-40, pct, rank_col)
    sub_txt = f"{data['sp_to_next']:.1f} SP to {next_r}" if next_r else "Maximum rank reached"
    draw.text((20, 164), sub_txt, font=_fnt_sub, fill=_CARD_TEXT)
    pct_txt = f"{pct:.0f}%"
    pw = draw.textlength(pct_txt, font=_fnt_mono_sm)
    draw.text((W-24-pw, 164), pct_txt, font=_fnt_mono_sm, fill=rank_col)

    draw.rectangle([20, 184, W-20, 185], fill=(40, 40, 40))

    # ── Stat boxes (text only — boxes already drawn in overlay) ──
    stats = [
        ("TOP SURVIVOR", fmt(data["weekly_ts"]),  f"Global: {data['ts_rank']}",  data["sp_ts"]),
        ("TOTAL KILLS",  fmt(data["weekly_tpk"]), f"Global: {data['tpk_rank']}", data["sp_tpk"]),
        ("TOTAL LOOTS",  fmt(data["weekly_tl"]),  f"Global: {data['tl_rank']}",  data["sp_tl"]),
    ]
    for i, (lbl, val, sub, sp_g) in enumerate(stats):
        bx = 20 + i * (box_w + gap)
        # top accent bar on each box
        draw.rectangle([bx, box_y, bx+box_w, box_y+3], fill=rank_col)
        lx = bx + 10
        draw.text((lx, box_y+10), lbl, font=_fnt_label, fill=_CARD_MUTED)
        draw.text((lx, box_y+26), val, font=_fnt_value, fill=_CARD_WHITE)
        draw.text((lx, box_y+52), sub, font=_fnt_sub,   fill=_CARD_MUTED)
        sp_col = _CARD_GREEN if (sp_g and float(sp_g.replace("+","").replace(" SP","")) > 0) else _CARD_MUTED
        draw.text((lx, box_y+68), sp_g or "+0 SP", font=_fnt_mono, fill=sp_col)

    div_y = box_y + box_h + 10
    draw.rectangle([20, div_y, W-20, div_y+1], fill=(40, 40, 40))

    med_y = div_y + 10
    draw.text((20, med_y), "MEDALS OF HONOR", font=_fnt_label, fill=_CARD_MUTED)

    medals        = data.get("medals", [])
    circle_medals = [(t, l) for t, l in medals if t != "Event"]
    event_medals  = [(t, l) for t, l in medals if t == "Event"]

    r       = 26
    spacing = 14
    cx      = 20 + r
    cy      = med_y + 20 + r

    for tier, lbl in circle_medals:
        _draw_circle_medal(draw, cx, cy, r, tier, lbl)
        cx += r*2 + spacing

    badge_x = cx + 4
    badge_y = cy - r
    if badge_x + 100 > W - 10:
        badge_x = 20
        badge_y = cy + r + 10
    for _, txt in event_medals:
        _draw_event_badge(draw, badge_x, badge_y, txt, height=r*2)

    draw.text((20, H-18), f"APEX Clan  ·  Dead Frontier  ·  {data['week']}", font=_fnt_mono_sm, fill=_CARD_MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()

def build_stats_image(conn, username):
    """Build stats card image bytes for a given username. Returns None if no data."""
    week = get_current_week(conn)
    row  = conn.execute("""
        SELECT wa.sp_rank, wa.star_points, wa.sp_change, wa.sp_alltime,
               wa.current_streak, wa.best_streak, ws.level,
               ws.weekly_ts, ws.weekly_tpk, ws.weekly_loots,
               ws.weekly_ts_rank, ws.weekly_tpk_rank, ws.weekly_tl_rank
        FROM weekly_analysis wa
        JOIN weekly_snapshots ws ON wa.week = ws.week AND wa.username = ws.username
        WHERE wa.week = ? AND wa.username = ?
    """, (week, username)).fetchone()

    if not row:
        return None

    sp_rank   = row["sp_rank"] or "Scout"
    sp        = safe_float(row["star_points"])
    sp_change = safe_float(row["sp_change"])

    prev_thresholds = {
        "Apex Scout":   50,
        "Ranger":       120,
        "Apex Ranger":  200,
        "Templar":      300,
        "Apex Templar": 400,
    }
    next_rank, threshold = RANK_NEXT.get(sp_rank, (None, None))
    if threshold:
        prev_thresh = prev_thresholds.get(sp_rank, 0)
        pct      = min(100, (sp - prev_thresh) / (threshold - prev_thresh) * 100)
        sp_left  = threshold - sp
    else:
        pct, sp_left = 100, 0

    weekly_ts  = safe_int(row["weekly_ts"])
    weekly_tpk = safe_int(row["weekly_tpk"])
    weekly_tl  = safe_int(row["weekly_loots"])

    sp_alltime = safe_float(row["sp_alltime"])
    sp_mult = 2 if sp_alltime < 60 else (1.5 if sp_alltime < 120 else 1)
    def sp_ts_calc(ts):   return (20 * ts / (ts + 2_000_000_000)) * sp_mult if ts else 0
    def sp_tpk_calc(tpk): return (20 * tpk / (tpk + 12_000))      * sp_mult if tpk else 0
    def sp_tl_calc(tl):   return (20 * tl  / (tl  + 8_000))        * sp_mult if tl  else 0

    def sp_line(v): return f"+{v:.2f} SP" if v > 0 else "+0 SP"

    medals = _get_medals_for_card(conn, username)

    data = {
        "username":    username,
        "sp_rank":     sp_rank,
        "level":       safe_int(row["level"]),
        "sp":          sp,
        "sp_change":   sp_change,
        "streak":      safe_int(row["current_streak"]),
        "best_streak": safe_int(row["best_streak"]),
        "progress_pct": pct,
        "next_rank":   next_rank,
        "sp_to_next":  sp_left,
        "weekly_ts":   weekly_ts,
        "weekly_tpk":  weekly_tpk,
        "weekly_tl":   weekly_tl,
        "ts_rank":     row["weekly_ts_rank"]  or "—",
        "tpk_rank":    row["weekly_tpk_rank"] or "—",
        "tl_rank":     row["weekly_tl_rank"]  or "—",
        "sp_ts":       sp_line(sp_ts_calc(weekly_ts)),
        "sp_tpk":      sp_line(sp_tpk_calc(weekly_tpk)),
        "sp_tl":       sp_line(sp_tl_calc(weekly_tl)),
        "medals":      medals,
        "week":        week,
    }
    return generate_stats_card(data)

# ══════════════════════════════════════════════
#  STATS EMBED
# ══════════════════════════════════════════════
def build_stats_embed(conn, username):
    week = get_current_week(conn)

    row = conn.execute("""
        SELECT wa.sp_rank, wa.star_points, wa.sp_change, wa.current_streak,
               wa.best_streak, wa.activity_status,
               ws.level, ws.weekly_ts, ws.weekly_tpk, ws.weekly_loots,
               ws.alltime_ts, ws.alltime_tpk, ws.alltime_loots,
               ws.weekly_ts_rank, ws.weekly_tpk_rank, ws.weekly_tl_rank
        FROM weekly_analysis wa
        JOIN weekly_snapshots ws ON wa.week = ws.week AND wa.username = ws.username
        WHERE wa.week = ? AND wa.username = ?
    """, (week, username)).fetchone()

    if not row:
        return None

    sp_rank   = row["sp_rank"] or "Scout"
    sp        = safe_float(row["star_points"])
    sp_change = safe_float(row["sp_change"])
    streak    = safe_int(row["current_streak"])
    best_str  = safe_int(row["best_streak"])

    # Progress bar
    next_rank, threshold = RANK_NEXT.get(sp_rank, (None, None))
    prev_thresholds = {
        "Apex Scout":   50,
        "Ranger":       120,
        "Apex Ranger":  200,
        "Templar":      300,
        "Apex Templar": 400,
    }
    if threshold:
        prev_thresh = prev_thresholds.get(sp_rank, 0)
        pct = min(100, (sp - prev_thresh) / (threshold - prev_thresh) * 100)
        progress_str = f"`{progress_bar(pct)}`\n{threshold - sp:.1f} SP to **{next_rank}**"
    else:
        progress_str = "✅ Maximum rank reached"

    change_str = f"+{sp_change:.1f}" if sp_change > 0 else f"{sp_change:.1f}"

    if streak >= 4:   streak_str = f"🔥 {streak} weeks"
    elif streak >= 2: streak_str = f"⚡ {streak} weeks"
    elif streak == 1: streak_str = "1 week"
    else:             streak_str = "💤 Inactive"

    # SP gained per category
    weekly_ts  = safe_int(row["weekly_ts"])
    weekly_tpk = safe_int(row["weekly_tpk"])
    weekly_tl  = safe_int(row["weekly_loots"])
    ts_rank    = row["weekly_ts_rank"]  or "—"
    tpk_rank   = row["weekly_tpk_rank"] or "—"
    tl_rank    = row["weekly_tl_rank"]  or "—"

    sp_mult = 2 if sp < 60 else (1.5 if sp < 120 else 1)
    def clan_sp_ts(ts):   return (20 * ts / (ts + 2_000_000_000)) * sp_mult if ts else 0
    def clan_sp_tpk(tpk): return (20 * tpk / (tpk + 12_000))      * sp_mult if tpk else 0
    def clan_sp_tl(tl):   return (20 * tl  / (tl  + 8_000))        * sp_mult if tl  else 0

    sp_ts_val  = clan_sp_ts(weekly_ts)
    sp_tpk_val = clan_sp_tpk(weekly_tpk)
    sp_tl_val  = clan_sp_tl(weekly_tl)

    def sp_line(val):
        return f"+{val:.2f} SP" if val > 0 else "+0 SP"

    color = RANK_COLORS.get(sp_rank.lower(), 0xe74c3c)

    if streak >= 4:   streak_icon = "🔥"
    elif streak >= 2: streak_icon = "⚡"
    else:             streak_icon = "💤"

    embed = discord.Embed(
        title=f"📋  {username}",
        color=color
    )

    level_val = safe_int(row["level"])
    header = (
        f"🏷  **{sp_rank}** · Lv. **{level_val}**\n"
        f"⭐  **{sp:.1f} SP** ({change_str} this week)\n"
        f"{streak_icon}  Streak: **{streak} weeks** (best: {best_str})"
    )
    embed.add_field(name="​", value=header, inline=False)

    embed.add_field(name="📈  Rank Progress", value=progress_str, inline=False)

    embed.add_field(
        name="⚔️  TS",
        value=f"**{fmt(weekly_ts)}**\nGlobal: {ts_rank}\n`{sp_line(sp_ts_val)}`",
        inline=True
    )
    embed.add_field(
        name="💀  TPK",
        value=f"**{fmt(weekly_tpk)}**\nGlobal: {tpk_rank}\n`{sp_line(sp_tpk_val)}`",
        inline=True
    )
    embed.add_field(
        name="📦  TL",
        value=f"**{fmt(weekly_tl)}**\nGlobal: {tl_rank}\n`{sp_line(sp_tl_val)}`",
        inline=True
    )

    medals = get_player_medals(conn, username)
    medal_str = "  ·  ".join(medals) if medals else "*No medals yet*"
    embed.add_field(name="🏅  Medals", value=medal_str, inline=False)

    embed.set_footer(text=f"APEX Clan · Dead Frontier · {week}")
    return embed

# ══════════════════════════════════════════════
#  ROLE ASSIGNMENT
# ══════════════════════════════════════════════
async def assign_roles_for_guild(guild, conn):
    """
    For every registered member, find their current SP rank
    and update their Discord roles accordingly.
    Call this after running your weekly calc.
    """
    ensure_discord_table(conn)
    week = get_current_week(conn)
    registrations = conn.execute(
        "SELECT discord_id, username FROM discord_members"
    ).fetchall()

    # Get all rank roles from the guild — strip leading emoji from role names
    def strip_emoji(text):
        clean = ""
        for ch in text:
            if ord(ch) > 127 and ord(ch) != 8205:  # non-ASCII except zero-width joiner
                continue
            clean += ch
        return clean.strip()

    rank_roles = {}
    for r in guild.roles:
        clean_name = strip_emoji(r.name).strip()
        if clean_name in SP_RANKS:
            rank_roles[clean_name.lower()] = r

    results = {"updated": [], "not_found": [], "no_role": [], "already_set": []}

    for reg in registrations:
        discord_id  = int(reg["discord_id"])
        ingame_name = reg["username"]

        # Get current rank from DB
        rank_row = conn.execute(
            "SELECT sp_rank FROM weekly_analysis WHERE week=? AND username=?",
            (week, ingame_name)
        ).fetchone()
        if not rank_row:
            results["not_found"].append(ingame_name)
            continue

        sp_rank = (rank_row["sp_rank"] or "Scout").strip()

        # Find the Discord member
        member = guild.get_member(discord_id)
        if not member:
            try:
                member = await asyncio.wait_for(guild.fetch_member(discord_id), timeout=5.0)
            except asyncio.TimeoutError:
                results["not_found"].append(f"{ingame_name} (timeout)")
                continue
            except Exception as e:
                results["not_found"].append(f"{ingame_name} (error: {e})")
                continue

        # Find the new role first
        new_role = rank_roles.get(sp_rank.lower())
        if not new_role:
            results["no_role"].append(f"{sp_rank} role not found in server (for {ingame_name})")
            continue

        # Only add the role if they don't already have it
        current_role_names = [strip_emoji(r.name).strip().lower() for r in member.roles]
        if sp_rank.lower() in current_role_names:
            results["already_set"].append(f"{member.display_name} already has {sp_rank}")
            continue

        try:
            await member.add_roles(new_role, reason=f"APEX rank: {sp_rank}")
            results["updated"].append(f"{member.display_name} → {sp_rank}")
        except Exception as e:
            results["no_role"].append(f"{sp_rank} (add failed: {e})")

    return results

# ══════════════════════════════════════════════
#  OFFICER PROMOTION
# ══════════════════════════════════════════════
def check_promotion_eligibility(conn, username, member):
    """Returns (eligible: bool, failures: list of unmet requirement strings)"""
    failures = []

    # Check 1: SP rank — must be Apex Ranger or higher
    rank_row = conn.execute(
        "SELECT sp_rank FROM weekly_analysis WHERE username=? ORDER BY week DESC LIMIT 1",
        (username,)
    ).fetchone()
    sp_rank = rank_row["sp_rank"] if rank_row else None
    if not sp_rank or sp_rank not in SP_RANKS:
        failures.append(f"❌ **Minimum SP Rank:** {OFFICER_MIN_RANK} — your rank could not be determined")
    else:
        min_idx  = SP_RANKS.index(OFFICER_MIN_RANK)
        rank_idx = SP_RANKS.index(sp_rank)
        if rank_idx < min_idx:
            failures.append(f"❌ **Minimum SP Rank:** {OFFICER_MIN_RANK} — you are currently **{sp_rank}**")

    # Check 2: Discord Regular role
    member_role_names = [r.name for r in member.roles]
    if OFFICER_DISCORD_ROLE not in member_role_names:
        failures.append(f"❌ **Discord Role:** @{OFFICER_DISCORD_ROLE} — you do not have this role")

    # Check 3: Minimum 4 unique medals
    medal_defs = conn.execute(
        "SELECT category, tier, threshold, sort_order FROM medal_definitions ORDER BY category, sort_order ASC"
    ).fetchall()
    thresholds = {}
    for r in medal_defs:
        thresholds.setdefault(r["category"], []).append((r["tier"], safe_int(r["threshold"])))

    snaps = conn.execute(
        "SELECT weekly_ts, weekly_tpk, weekly_loots FROM weekly_snapshots WHERE username=?",
        (username,)
    ).fetchall()
    best_streak = conn.execute(
        "SELECT MAX(best_streak) as bs FROM weekly_analysis WHERE username=?", (username,)
    ).fetchone()
    best_streak_val = safe_int(best_streak["bs"]) if best_streak else 0
    best_global = None
    for r in conn.execute(
        "SELECT weekly_ts_rank, weekly_tpk_rank, weekly_tl_rank FROM weekly_snapshots WHERE username=?",
        (username,)
    ).fetchall():
        for col in ("weekly_ts_rank", "weekly_tpk_rank", "weekly_tl_rank"):
            val = r[col]
            if val:
                try:
                    n = int(str(val).replace("#", "").strip())
                    if n > 0:
                        best_global = min(best_global or 9999, n)
                except: pass

    col_map      = {"ts": "weekly_ts", "tpk": "weekly_tpk", "tl": "weekly_loots"}
    earned_medals = 0
    for cat, tiers in thresholds.items():
        if cat in col_map:
            best_val = max((safe_int(r[col_map[cat]]) for r in snaps), default=0)
            for tier, thresh in reversed(tiers):
                if best_val >= thresh:
                    earned_medals += 1
                    break
        elif cat == "streak":
            for tier, thresh in reversed(tiers):
                if best_streak_val >= thresh:
                    earned_medals += 1
                    break
        elif cat == "global" and best_global:
            for tier, thresh in reversed(tiers):
                if best_global <= thresh:
                    earned_medals += 1
                    break

    wins = conn.execute(
        "SELECT COUNT(*) as c FROM event_rewards WHERE username=? AND event_id NOT LIKE 'W%'",
        (username,)
    ).fetchone()
    if wins and safe_int(wins["c"]) > 0:
        earned_medals += 1

    if earned_medals < OFFICER_MIN_MEDALS:
        failures.append(f"❌ **Unique Medals:** minimum {OFFICER_MIN_MEDALS} — you have **{earned_medals}**")

    return len(failures) == 0, failures


# ══════════════════════════════════════════════
#  BOT
# ══════════════════════════════════════════════
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# ══════════════════════════════════════════════
#  ARMORY FULFILLMENT BUTTON
# ══════════════════════════════════════════════
class ArmoryFulfillView(discord.ui.View):
    """Persistent button posted in #applications for officers to mark a request fulfilled."""

    def __init__(self, requester_id: int, requester_name: str, item_name: str):
        super().__init__(timeout=None)  # never expires
        self.requester_id   = requester_id
        self.requester_name = requester_name
        self.item_name      = item_name

    @discord.ui.button(label="✅  Mark as Fulfilled", style=discord.ButtonStyle.success,
                       custom_id="armory_fulfill")
    async def fulfill(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Disable the button so it can't be clicked again
        button.disabled = True
        button.label    = "✅  Fulfilled"

        # Edit the original embed to show fulfilled state
        original_embed        = interaction.message.embeds[0]
        fulfilled_embed       = original_embed.copy()
        fulfilled_embed.color = 0x2ecc71  # green

        # Update or append a Fulfilled By field
        new_fields = []
        for field in fulfilled_embed.fields:
            if field.name != "Fulfilled By":
                new_fields.append(field)
        fulfilled_embed.clear_fields()
        for f in new_fields:
            fulfilled_embed.add_field(name=f.name, value=f.value, inline=f.inline)
        fulfilled_embed.add_field(
            name="Fulfilled By",
            value=f"{interaction.user.mention} · {interaction.user.display_name}",
            inline=False
        )
        fulfilled_embed.set_footer(
            text=f"Fulfilled {interaction.created_at.strftime('%Y-%m-%d %H:%M UTC')} · APEX Clan"
        )

        await interaction.response.edit_message(embed=fulfilled_embed, view=self)

        # Also DM the requester to let them know
        try:
            requester = await client.fetch_user(self.requester_id)
            await requester.send(
                f"✅ Your armory request for **{self.item_name}** has been fulfilled by "
                f"**{interaction.user.display_name}**! Reach out to them to arrange the handoff."
            )
        except Exception:
            pass  # DMs may be closed — silently skip


# ══════════════════════════════════════════════
#  ARMORY
# ══════════════════════════════════════════════
def fetch_armory():
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{ARMORY_SHEET_ID}"
           f"/values/{ARMORY_TAB}?key={ARMORY_API_KEY}")
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = _json.loads(r.read())
    except Exception as e:
        return None, str(e)

    rows  = data.get("values", [])
    items = {"weapons": [], "armor": [], "implants": []}
    sec   = "weapons"

    for row in rows:
        while len(row) <= max(ACOL.values()):
            row.append("")

        c0 = row[0].strip().lower()
        c1 = row[1].strip().lower() if len(row) > 1 else ""

        # Same logic as apex_html_gen_v2.py
        if ("weapon" in c0 or "weapon" in c1) and "name" not in c1:
            sec = "weapons"; continue
        if ("armor" in c0 or "armor" in c1) and "name" not in c1:
            sec = "armor"; continue
        if ("implant" in c0 or "implant" in c1) and "name" not in c1:
            sec = "implants"; continue

        name = row[ACOL["name"]].strip()
        if not name:
            continue

        borrowed_by = row[ACOL["borrowed_by"]].strip()
        due_date    = row[ACOL["due_date"]].strip()
        rank_req    = row[ACOL["rank"]].strip()
        status      = "borrowed" if borrowed_by else "available"

        items[sec].append({
            "name":        name,
            "status":      status,
            "borrowed_by": borrowed_by,
            "due_date":    due_date,
            "rank_req":    rank_req,
            "section":     sec,
        })

    return items, None

def find_armory_item(items, query):
    query = query.lower().strip()
    all_items = [i for v in items.values() for i in v]
    for item in all_items:
        if item["name"].lower() == query:
            return item
    for item in all_items:
        if query in item["name"].lower():
            return item
    return None

def build_armory_image(items) -> bytes:
    """Render the armory as a clean, wide image card with one item per row."""
    # ── Colours ──────────────────────────────────────────────
    BG           = (13,  13,  13)
    ROW_A        = (20,  20,  20)
    ROW_B        = (17,  17,  17)
    SEC_BG       = (26,  26,  26)
    AVAIL_COL    = (46,  204, 113)
    BORROW_COL   = (231, 76,  60)
    WHITE        = (255, 255, 255)
    MUTED        = (90,  90,  90)
    GOLD         = (241, 196, 15)
    GOLD_DARK    = (40,  32,  0)
    ACCENT       = (231, 76,  60)
    CAT_COLS     = {"weapons": (231,76,60), "armor": (52,152,219), "implants": (155,89,182)}
    DIV          = (35,  35,  35)

    # ── Fonts ─────────────────────────────────────────────────
    fnt_title   = _font(_BOLD,    34)
    fnt_sub     = _font(_MONO_SM, 13)
    fnt_sechdr  = _font(_BOLD,    16)
    fnt_item    = _font(_BOLD,    18)
    fnt_status  = _font(_MONO_SM, 13)
    fnt_rank    = _font(_BOLD,    13)
    fnt_counter = _font(_BOLD,    22)
    fnt_footer  = _font(_MONO_SM, 12)

    # ── Layout ───────────────────────────────────────────────
    CARD_W  = 1100
    PAD     = 30
    HDR_H   = 100     # header height
    COL_H   = 28      # column-header row height
    SEC_H   = 44      # section header height
    ROW_H   = 48      # item row height
    SEC_GAP = 10
    FOOT_H  = 40

    # Column positions — spaced so nothing overlaps
    COL_DOT    = PAD + 12
    COL_NAME   = PAD + 32
    COL_STATUS = 420
    COL_WHO    = 590
    COL_DUE    = 790
    COL_RANK   = 950   # fixed, not relative to CARD_W so rank badge doesn't eat DUE

    total  = sum(len(v) for v in items.values())
    avail  = sum(1 for v in items.values() for i in v if i["status"] == "available")
    borrow = total - avail

    num_secs = sum(1 for v in items.values() if v)
    num_rows = sum(len(v) for v in items.values())
    CARD_H   = HDR_H + COL_H + num_secs * (SEC_H + SEC_GAP + 4) + num_rows * ROW_H + FOOT_H + PAD

    img  = Image.new("RGB", (CARD_W, CARD_H), BG)
    draw = ImageDraw.Draw(img)

    # ── Top accent bar ────────────────────────────────────────
    draw.rectangle([0, 0, CARD_W, 4], fill=ACCENT)

    # ── Header ────────────────────────────────────────────────
    draw.text((PAD, 16), "APEX ARMORY", font=fnt_title, fill=WHITE)
    draw.text((PAD, 62), f"// LIVE INVENTORY  ·  {total} ITEMS  ·  {avail} AVAILABLE  ·  {borrow} BORROWED //",
              font=fnt_sub, fill=(100, 100, 100))

    # Right-side counters: AVAIL / OUT / TOTAL
    counter_x = CARD_W - PAD - 260
    for lbl, val, col in [("AVAIL", str(avail), AVAIL_COL),
                           ("OUT",   str(borrow), BORROW_COL),
                           ("TOTAL", str(total),  MUTED)]:
        draw.text((counter_x, 16), lbl, font=fnt_sub, fill=MUTED)
        draw.text((counter_x, 34), val, font=fnt_counter, fill=col)
        counter_x += 90

    draw.rectangle([PAD, HDR_H - 2, CARD_W - PAD, HDR_H - 1], fill=DIV)

    # ── Column headers ────────────────────────────────────────
    col_hdr_y = HDR_H + 6
    for txt, x in [("ITEM", COL_NAME), ("STATUS", COL_STATUS),
                   ("BORROWED BY", COL_WHO), ("DUE DATE", COL_DUE), ("MIN RANK", COL_RANK)]:
        draw.text((x, col_hdr_y), txt, font=fnt_footer, fill=MUTED)

    draw.rectangle([PAD, HDR_H + COL_H, CARD_W - PAD, HDR_H + COL_H + 1], fill=DIV)

    y = HDR_H + COL_H + 6

    for sec in ["weapons", "armor", "implants"]:
        sec_items = items.get(sec, [])
        if not sec_items:
            continue

        cat_col = CAT_COLS[sec]
        icon    = {"weapons": "WEAPONS", "armor": "ARMOR", "implants": "IMPLANTS"}[sec]

        # ── Section header ────────────────────────────────────
        draw.rectangle([0, y, CARD_W, y + SEC_H], fill=SEC_BG)
        draw.rectangle([0, y, 4,      y + SEC_H], fill=cat_col)
        draw.text((PAD + 10, y + (SEC_H - 18) // 2), f"{icon}  ({len(sec_items)})",
                  font=fnt_sechdr, fill=cat_col)
        y += SEC_H + 4

        # ── Item rows ─────────────────────────────────────────
        for idx, item in enumerate(sec_items):
            is_avail = item["status"] == "available"
            row_col  = AVAIL_COL if is_avail else BORROW_COL
            row_bg   = ROW_A if idx % 2 == 0 else ROW_B

            draw.rectangle([0, y, CARD_W, y + ROW_H], fill=row_bg)
            draw.rectangle([0, y, 4,      y + ROW_H], fill=row_col)

            # Dot
            cy = y + ROW_H // 2
            draw.ellipse([COL_DOT - 6, cy - 6, COL_DOT + 6, cy + 6], fill=row_col)

            # Item name — truncate if too long
            name = item["name"].replace("\n", " ").replace("\r", "").strip()
            while draw.textlength(name, font=fnt_item) > (COL_STATUS - COL_NAME - 12) and len(name) > 4:
                name = name[:-1]
            if name != item["name"].replace("\n", " ").replace("\r", "").strip():
                name = name[:-1] + "…"
            ty = y + (ROW_H - 18) // 2
            draw.text((COL_NAME, ty), name, font=fnt_item, fill=WHITE)

            # Status
            sy = y + (ROW_H - 13) // 2
            if is_avail:
                draw.text((COL_STATUS, sy), "AVAILABLE", font=fnt_status, fill=AVAIL_COL)
            else:
                draw.text((COL_STATUS, sy), "BORROWED",  font=fnt_status, fill=BORROW_COL)
                # Who
                who = item["borrowed_by"]
                while draw.textlength(who, font=fnt_status) > (COL_DUE - COL_WHO - 12) and len(who) > 2:
                    who = who[:-1]
                if who != item["borrowed_by"]:
                    who = who[:-1] + "…"
                draw.text((COL_WHO, sy), who, font=fnt_status, fill=(210, 110, 100))
                if item["due_date"]:
                    draw.text((COL_DUE, sy), item["due_date"], font=fnt_status, fill=MUTED)

            # Rank badge
            if item["rank_req"]:
                rk_txt = f"  {item['rank_req'].upper()}+  "
                rk_w   = int(draw.textlength(rk_txt, font=fnt_rank))
                rk_y1  = y + 10
                rk_y2  = y + ROW_H - 10
                draw.rectangle([COL_RANK, rk_y1, COL_RANK + rk_w, rk_y2],
                                fill=GOLD_DARK, outline=(60, 50, 0))
                draw.text((COL_RANK + 2, rk_y1 + (rk_y2 - rk_y1 - 14) // 2),
                          rk_txt, font=fnt_rank, fill=GOLD)

            y += ROW_H

        y += SEC_GAP

    # ── Footer ────────────────────────────────────────────────
    draw.rectangle([0, CARD_H - FOOT_H, CARD_W, CARD_H], fill=(10, 10, 10))
    draw.rectangle([0, CARD_H - FOOT_H, CARD_W, CARD_H - FOOT_H + 1], fill=DIV)
    draw.text((PAD, CARD_H - FOOT_H + 12),
              "APEX CLAN  ·  DEAD FRONTIER  ·  use  !armory request <item name>  to borrow",
              font=fnt_footer, fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def build_armory_embed(items):
    CAT_ICON = {"weapons": "⚔️", "armor": "🛡️", "implants": "💉"}
    total = sum(len(v) for v in items.values())
    avail = sum(1 for v in items.values() for i in v if i["status"] == "available")

    embed = discord.Embed(
        title="⚔️  APEX Armory",
        description=f"`// LIVE INVENTORY · {total} ITEMS · {avail} AVAILABLE //`",
        color=0xe74c3c
    )

    for sec in ["weapons", "armor", "implants"]:
        sec_items = items[sec]
        if not sec_items:
            continue
        lines = []
        for item in sec_items:
            if item["status"] == "available":
                status_str = "✅ Available"
            else:
                status_str = f"⊘ {item['borrowed_by']}"
                if item["due_date"]:
                    status_str += f" · due {item['due_date']}"
            rank_str = f"⚡ {item['rank_req']}+" if item["rank_req"] else ""
            line = f"**{item['name']}**"
            if rank_str: line += f"  {rank_str}"
            line += "\n" + status_str
            lines.append(line)

        embed.add_field(
            name=f"{CAT_ICON[sec]}  {sec.capitalize()}",
            value="\n".join(lines) or "*No items*",
            inline=False
        )

    embed.set_footer(text="Use !armory request <item name> to request an item")
    return embed


# ══════════════════════════════════════════════
#  WEEKLY SUMMARY
# ══════════════════════════════════════════════
def get_weekly_summary_data(conn):
    week = get_current_week(conn)
    if not week:
        return None

    prev_row  = conn.execute(
        "SELECT week FROM weekly_analysis WHERE week < ? ORDER BY week DESC LIMIT 1", (week,)
    ).fetchone()
    prev_week = prev_row["week"] if prev_row else None

    all_rows = conn.execute("""
        SELECT wa.username, wa.sp_rank, wa.sp_change, wa.star_points,
               wa.current_streak, wa.best_streak,
               ws.weekly_ts, ws.weekly_tpk, ws.weekly_loots
        FROM weekly_analysis wa
        JOIN weekly_snapshots ws
          ON wa.week = ws.week AND wa.username = ws.username
        WHERE wa.week = ?
    """, (week,)).fetchall()

    # Top 3 SP gain — exclude Scout
    sp_rows = [r for r in all_rows if (r["sp_rank"] or "").lower() != "scout"]
    sp_rows.sort(key=lambda r: safe_float(r["sp_change"]), reverse=True)
    top3_sp  = sp_rows[:3]
    ts_top3  = sorted(all_rows, key=lambda r: safe_int(r["weekly_ts"]),    reverse=True)[:3]
    tpk_top3 = sorted(all_rows, key=lambda r: safe_int(r["weekly_tpk"]),   reverse=True)[:3]
    tl_top3  = sorted(all_rows, key=lambda r: safe_int(r["weekly_loots"]), reverse=True)[:3]

    # Rank-ups vs previous week
    rank_ups = []
    if prev_week:
        prev_ranks = {r["username"]: r["sp_rank"] for r in conn.execute(
            "SELECT username, sp_rank FROM weekly_analysis WHERE week=?", (prev_week,)
        ).fetchall()}
        for r in all_rows:
            u   = r["username"]; cur = r["sp_rank"] or ""; prev = prev_ranks.get(u, "")
            if cur and prev and cur != prev:
                try:
                    if SP_RANKS.index(cur) > SP_RANKS.index(prev):
                        rank_ups.append((u, prev, cur))
                except ValueError:
                    pass

    # New medals this week vs previous history
    medal_defs = conn.execute(
        "SELECT category, tier, threshold, sort_order FROM medal_definitions "
        "ORDER BY category, sort_order ASC"
    ).fetchall()
    thresholds = {}
    for r in medal_defs:
        thresholds.setdefault(r["category"], []).append((r["tier"], safe_int(r["threshold"])))

    col_map    = {"ts": "weekly_ts", "tpk": "weekly_tpk", "tl": "weekly_loots"}
    cat_labels = {"ts": "TS", "tpk": "TPK", "tl": "TL", "streak": "S"}

    new_medals = []   # list of (username, tier, short_label, is_event, event_text)
    for r in all_rows:
        uname   = r["username"]
        cur_ts  = safe_int(r["weekly_ts"]); cur_tpk = safe_int(r["weekly_tpk"])
        cur_tl  = safe_int(r["weekly_loots"]); cur_str = safe_int(r["best_streak"])

        if prev_week:
            ps = conn.execute(
                "SELECT weekly_ts, weekly_tpk, weekly_loots "
                "FROM weekly_snapshots WHERE username=? AND week<=?",
                (uname, prev_week)
            ).fetchall()
            prev_ts  = max((safe_int(s["weekly_ts"])    for s in ps), default=0)
            prev_tpk = max((safe_int(s["weekly_tpk"])   for s in ps), default=0)
            prev_tl  = max((safe_int(s["weekly_loots"]) for s in ps), default=0)
            ps2      = conn.execute(
                "SELECT MAX(best_streak) as bs FROM weekly_analysis WHERE username=? AND week<=?",
                (uname, prev_week)
            ).fetchone()
            prev_str = safe_int(ps2["bs"]) if ps2 else 0
        else:
            prev_ts = prev_tpk = prev_tl = prev_str = 0

        for cat, tiers in thresholds.items():
            if cat not in col_map and cat != "streak":
                continue
            if cat == "streak":
                cv, pv = cur_str, prev_str
            else:
                dbc = col_map[cat]
                cv  = {"weekly_ts": cur_ts, "weekly_tpk": cur_tpk, "weekly_loots": cur_tl}[dbc]
                pv  = {"weekly_ts": prev_ts, "weekly_tpk": prev_tpk, "weekly_loots": prev_tl}[dbc]
            for tier, thresh in reversed(tiers):
                if cv >= thresh and pv < thresh:
                    new_medals.append((uname, tier, cat_labels.get(cat, cat), False, ""))
                    break

    return {
        "week":       week,
        "active":     len(all_rows),
        "top3_sp":    top3_sp,
        "ts_top3":    ts_top3,
        "tpk_top3":   tpk_top3,
        "tl_top3":    tl_top3,
        "rank_ups":   rank_ups,
        "new_medals": new_medals,
    }


def build_weekly_summary_image(data: dict) -> bytes:
    # ── colours ──────────────────────────────────────────────
    BG         = (13,  13,  13)
    PANEL      = (20,  20,  20)
    DARK_PANEL = (10,  10,  10)
    WHITE      = (255, 255, 255)
    MUTED      = (100, 100, 100)
    SEC_FG     = (190, 190, 190)
    GOLD       = (241, 196,  15)
    SILVER     = (149, 165, 166)
    BRONZE_C   = (160,  82,  45)
    GREEN      = ( 46, 204, 113)
    DIV        = ( 35,  35,  35)
    ACCENT     = (231,  76,  60)

    TIER_COLS  = {
        "Platinum": (116, 185, 255),
        "Gold":     (241, 196,  15),
        "Silver":   (189, 195, 199),
        "Bronze":   (176, 106,  53),
    }

    # ── fonts ─────────────────────────────────────────────────
    fnt_title   = _font(_BOLD,    24)
    fnt_week    = _font(_BOLD,    13)
    fnt_sec     = _font(_BOLD,    11)
    fnt_sub     = _font(_MONO_SM,  9)
    fnt_pos     = _font(_BOLD,    28)
    fnt_pod_nm  = _font(_BOLD,    17)
    fnt_subrank = _font(_MONO_SM, 10)
    fnt_change  = _font(_BOLD,    16)
    fnt_sptotal = _font(_MONO_SM, 10)
    fnt_cat_hdr = _font(_BOLD,    11)
    fnt_cat_row = _font(_BOLD,    14)
    fnt_cat_val = _font(_MONO_SM, 13)
    fnt_cat_pos = _font(_BOLD,    12)
    fnt_ru_name = _font(_BOLD,    14)
    fnt_ru_rank = _font(_MONO_SM, 11)
    fnt_medal   = _font(_BOLD,    10)   # same as stats card
    fnt_event   = _font(_BOLD,    12)
    fnt_footer  = _font(_MONO_SM,  9)

    # ── layout constants ──────────────────────────────────────
    W          = 700
    PAD        = 22
    HDR_H      = 66
    SEC_H      = 28
    POD_H      = 130   # tall enough: pos(28)+name(17)+rank(10)+change(16)+total(10) + padding
    CAT_HDR_H  = 30
    CAT_ROW_H  = 30
    RU_ROW_H   = 36
    MED_ROW_H  = 44    # height per player row in medals section
    FOOT_H     = 30
    GAP        = 10

    n_ru  = len(data["rank_ups"])
    # Group medals by player for height calculation
    med_by_player = {}
    for uname, tier, lbl, is_ev, ev_txt in data["new_medals"]:
        med_by_player.setdefault(uname, []).append((tier, lbl, is_ev, ev_txt))
    n_med_players = len(med_by_player)

    H = (HDR_H + GAP
       + SEC_H + POD_H + GAP
       + SEC_H + CAT_HDR_H + CAT_ROW_H * 3 + GAP
       + SEC_H + (RU_ROW_H * max(n_ru, 1) if n_ru else 28) + GAP
       + SEC_H + (MED_ROW_H * max(n_med_players, 1) if n_med_players else 28) + GAP
       + FOOT_H + 6)
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    def sec_label(y, txt):
        draw.text((PAD, y + 6), txt, font=fnt_sec, fill=SEC_FG)
        lx = PAD + int(draw.textlength(txt, font=fnt_sec)) + 10
        draw.rectangle([lx, y + 13, W - PAD, y + 14], fill=DIV)
        return y + SEC_H

    # ── header ────────────────────────────────────────────────
    draw.rectangle([0, 0, W, 3], fill=ACCENT)
    draw.text((PAD, 12), "WEEKLY REPORT", font=fnt_title, fill=WHITE)
    draw.text((PAD, 40),
              f"// APEX CLAN  ·  DEAD FRONTIER  ·  {data['active']} ACTIVE MEMBERS //",
              font=fnt_sub, fill=MUTED)
    badge = data["week"]
    bw    = int(draw.textlength(badge, font=fnt_week)) + 22
    draw.rectangle([W - PAD - bw, 16, W - PAD, 50], fill=(25, 18, 0), outline=(60, 48, 0))
    draw.text((W - PAD - bw + 11, 24), badge, font=fnt_week, fill=GOLD)
    draw.rectangle([0, HDR_H, W, HDR_H + 1], fill=DIV)
    y = HDR_H + GAP

    # ══ TOP 3 SP GAIN ════════════════════════════════════════
    y      = sec_label(y, "TOP SP GAIN THIS WEEK")
    top3   = data["top3_sp"]
    pod_w  = (W - PAD * 2 - 4) // 3
    order  = [1, 0, 2]          # left=#2, center=#1, right=#3
    p_cols = [SILVER, GOLD, BRONZE_C]

    for slot, (oi, pc) in enumerate(zip(order, p_cols)):
        if oi >= len(top3):
            continue
        r      = top3[oi]; pos = oi + 1
        px     = PAD + slot * (pod_w + 2)
        offset = 0 if pos == 1 else 16      # #1 taller

        draw.rectangle([px, y + offset, px + pod_w, y + POD_H], fill=PANEL)
        draw.rectangle([px, y + POD_H - 4, px + pod_w, y + POD_H], fill=pc)

        # position number
        pos_t = f"#{pos}"
        pw2   = int(draw.textlength(pos_t, font=fnt_pos))
        draw.text((px + (pod_w - pw2) // 2, y + offset + 5), pos_t, font=fnt_pos, fill=pc)

        # name
        name = r["username"]
        while int(draw.textlength(name, font=fnt_pod_nm)) > pod_w - 8 and len(name) > 3:
            name = name[:-1]
        if name != r["username"]: name += "…"
        nw = int(draw.textlength(name, font=fnt_pod_nm))
        draw.text((px + (pod_w - nw) // 2, y + offset + 38), name, font=fnt_pod_nm, fill=WHITE)

        # rank
        rk = (r["sp_rank"] or "").upper()
        rw = int(draw.textlength(rk, font=fnt_subrank))
        draw.text((px + (pod_w - rw) // 2, y + offset + 58), rk, font=fnt_subrank, fill=MUTED)

        # SP change
        chg   = safe_float(r["sp_change"])
        chg_t = f"+{chg:.1f} SP" if chg >= 0 else f"{chg:.1f} SP"
        cw    = int(draw.textlength(chg_t, font=fnt_change))
        draw.text((px + (pod_w - cw) // 2, y + offset + 74), chg_t, font=fnt_change, fill=GREEN)

        # total SP — stays well above the 4px bottom bar
        tot_t = f"{safe_float(r['star_points']):.1f} SP total"
        tw    = int(draw.textlength(tot_t, font=fnt_sptotal))
        draw.text((px + (pod_w - tw) // 2, y + offset + 96), tot_t, font=fnt_sptotal, fill=MUTED)

    y += POD_H + GAP

    # ══ CATEGORY TOP 3 ═══════════════════════════════════════
    y    = sec_label(y, "CATEGORY TOP 3")
    cats = [
        ("TOP SURVIVOR ⚔",  data["ts_top3"],  "weekly_ts",    (231,  76,  60), fmt),
        ("MOST KILLS 💀",    data["tpk_top3"], "weekly_tpk",   (155,  89, 182), lambda v: str(safe_int(v))),
        ("TOP LOOTER 📦",    data["tl_top3"],  "weekly_loots", ( 52, 152, 219), lambda v: str(safe_int(v))),
    ]
    col_w    = (W - PAD * 2 - 4) // 3
    pos_cols = [GOLD, SILVER, BRONZE_C]

    for ci, (lbl, _, _, col, _) in enumerate(cats):
        cx = PAD + ci * (col_w + 2)
        draw.rectangle([cx, y, cx + col_w, y + CAT_HDR_H], fill=DARK_PANEL)
        draw.rectangle([cx, y, cx + col_w, y + 3], fill=col)
        lw = int(draw.textlength(lbl, font=fnt_cat_hdr))
        draw.text((cx + (col_w - lw) // 2, y + 8), lbl, font=fnt_cat_hdr, fill=col)
    y += CAT_HDR_H

    for ri in range(3):
        for ci, (_, rows, db_col, col, fmt_fn) in enumerate(cats):
            cx = PAD + ci * (col_w + 2)
            draw.rectangle([cx, y, cx + col_w, y + CAT_ROW_H],
                           fill=PANEL if ri % 2 == 0 else (24, 24, 24))
            if ri < len(rows):
                r  = rows[ri]; pc = pos_cols[ri]
                draw.text((cx + 7,  y + (CAT_ROW_H - 12) // 2), f"#{ri+1}", font=fnt_cat_pos, fill=pc)
                name = r["username"]
                while int(draw.textlength(name, font=fnt_cat_row)) > col_w - 66 and len(name) > 2:
                    name = name[:-1]
                if name != r["username"]: name += "…"
                draw.text((cx + 30, y + (CAT_ROW_H - 14) // 2), name, font=fnt_cat_row, fill=WHITE)
                val = fmt_fn(r[db_col])
                vw  = int(draw.textlength(val, font=fnt_cat_val))
                draw.text((cx + col_w - vw - 7, y + (CAT_ROW_H - 13) // 2),
                          val, font=fnt_cat_val, fill=col)
        y += CAT_ROW_H
    y += GAP

    # ══ RANK UPS ═════════════════════════════════════════════
    y = sec_label(y, "RANK UPS")
    if data["rank_ups"]:
        for uname, from_r, to_r in data["rank_ups"]:
            draw.rectangle([0, y, W, y + RU_ROW_H], fill=PANEL)
            draw.rectangle([0, y, 4, y + RU_ROW_H], fill=GREEN)
            draw.text((PAD + 10, y + (RU_ROW_H - 14) // 2), uname,         font=fnt_ru_name, fill=WHITE)
            draw.text((260,      y + (RU_ROW_H - 11) // 2), from_r,        font=fnt_ru_rank, fill=MUTED)
            draw.text((390,      y + (RU_ROW_H - 11) // 2), "──▶",         font=fnt_ru_rank, fill=(55,55,55))
            draw.text((430,      y + (RU_ROW_H - 11) // 2), to_r.upper(),  font=fnt_ru_rank, fill=GREEN)
            y += RU_ROW_H
            draw.rectangle([0, y, W, y + 1], fill=DIV)
    else:
        draw.text((PAD, y + 8), "No rank ups this week.", font=fnt_sec, fill=MUTED)
        y += 28
    y += GAP

    # ══ NEW MEDALS — one row per player ═════════════════════
    y = sec_label(y, "NEW MEDALS EARNED")
    if med_by_player:
        r_circ  = 18
        spacing = 8
        for row_i, (uname, medals_list) in enumerate(med_by_player.items()):
            row_bg = PANEL if row_i % 2 == 0 else (24, 24, 24)
            draw.rectangle([0, y, W, y + MED_ROW_H], fill=row_bg)
            draw.rectangle([0, y, 4, y + MED_ROW_H], fill=GOLD)

            # Player name on the left
            draw.text((PAD + 10, y + (MED_ROW_H - 14) // 2), uname, font=fnt_ru_name, fill=WHITE)

            # Circles to the right of name
            cx = 240
            cy = y + MED_ROW_H // 2
            for tier, lbl, is_ev, ev_txt in medals_list:
                if is_ev:
                    # Event winner rectangular badge
                    t_txt = ev_txt if ev_txt else "Event Winner"
                    tw    = int(draw.textlength(t_txt, font=fnt_event)) + 16
                    draw.rounded_rectangle([cx, cy - r_circ, cx + tw, cy + r_circ],
                                           radius=r_circ, fill=(55, 42, 0))
                    draw.rounded_rectangle([cx, cy - r_circ, cx + tw, cy + r_circ],
                                           radius=r_circ, outline=GOLD, width=2)
                    lw2 = int(draw.textlength(t_txt, font=fnt_event))
                    draw.text((cx + (tw - lw2) // 2, cy - 7), t_txt, font=fnt_event, fill=GOLD)
                    cx += tw + spacing
                else:
                    col  = TIER_COLS.get(tier, MUTED)
                    dark = tuple(max(0, c - 90) for c in col)
                    mid  = tuple(max(0, c - 40) for c in col)
                    for i in range(3, 0, -1):
                        glow = tuple(max(0, c - 130 + i * 10) for c in col)
                        draw.ellipse([cx - i, cy - r_circ - i, cx + r_circ * 2 + i, cy + r_circ + i],
                                     outline=glow, width=1)
                    draw.ellipse([cx, cy - r_circ, cx + r_circ * 2, cy + r_circ], fill=dark)
                    draw.ellipse([cx, cy - r_circ, cx + r_circ * 2, cy + r_circ], outline=col, width=2)
                    draw.ellipse([cx + 4, cy - r_circ + 4, cx + r_circ * 2 - 4, cy + r_circ - 4],
                                 outline=mid, width=1)
                    lw2 = int(draw.textlength(lbl, font=fnt_medal))
                    draw.text((cx + r_circ - lw2 // 2, cy - 6), lbl, font=fnt_medal, fill=WHITE)
                    cx += r_circ * 2 + spacing

            y += MED_ROW_H
            draw.rectangle([0, y, W, y + 1], fill=DIV)
    else:
        draw.text((PAD, y + 8), "No new medals this week.", font=fnt_sec, fill=MUTED)
        y += 28
    y += GAP

    # ══ FOOTER ═══════════════════════════════════════════════
    draw.rectangle([0, y, W, y + FOOT_H], fill=DARK_PANEL)
    draw.rectangle([0, y, W, y + 1], fill=DIV)
    draw.text((PAD, y + (FOOT_H - 9) // 2),
              f"APEX CLAN  ·  DEAD FRONTIER  ·  {data['week']}", font=fnt_footer, fill=MUTED)

    img = img.crop((0, 0, W, y + FOOT_H))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


# ══════════════════════════════════════════════
#  LEADERBOARD
# ══════════════════════════════════════════════
LEADERBOARD_CATEGORIES = {
    "sp":  {"label": "SP Gain",       "col": "sp_change",    "source": "analysis", "fmt": lambda v: f"{v:+.1f} SP"},
    "ts":  {"label": "Top Survivor",  "col": "weekly_ts",    "source": "snapshot", "fmt": lambda v: fmt(v)},
    "tpk": {"label": "Total Kills",   "col": "weekly_tpk",   "source": "snapshot", "fmt": lambda v: fmt(v)},
    "tl":  {"label": "Total Loots",   "col": "weekly_loots", "source": "snapshot", "fmt": lambda v: fmt(v)},
}

def get_leaderboard_data(conn, category="sp"):
    week = get_current_week(conn)
    if not week:
        return None, None

    cat = LEADERBOARD_categories = LEADERBOARD_CATEGORIES[category]

    if cat["source"] == "analysis":
        rows = conn.execute(f"""
            SELECT wa.username, wa.sp_rank, wa.{cat['col']} as val
            FROM weekly_analysis wa
            WHERE wa.week = ?
            ORDER BY wa.{cat['col']} DESC
            LIMIT 10
        """, (week,)).fetchall()
    else:
        rows = conn.execute(f"""
            SELECT ws.username, wa.sp_rank, ws.{cat['col']} as val
            FROM weekly_snapshots ws
            JOIN weekly_analysis wa ON wa.week = ws.week AND wa.username = ws.username
            WHERE ws.week = ?
            ORDER BY ws.{cat['col']} DESC
            LIMIT 10
        """, (week,)).fetchall()

    return [dict(r) for r in rows], week


def build_leaderboard_image(conn, category="sp") -> bytes | None:
    rows, week = get_leaderboard_data(conn, category)
    if not rows:
        return None

    cat      = LEADERBOARD_CATEGORIES[category]
    cat_label = cat["label"].upper()
    val_fmt   = cat["fmt"]

    # ── colours (match existing card aesthetic) ──
    BG       = _CARD_BG
    PANEL    = (20, 20, 20)
    PANEL_B  = (17, 17, 17)
    WHITE    = _CARD_WHITE
    MUTED    = (90, 90, 90)
    GOLD_C   = _CARD_GOLD
    SILVER_C = (180, 180, 180)
    BRONZE_C = (160, 106, 53)
    GREEN    = _CARD_GREEN
    ACCENT   = _CARD_RED
    DIV      = (35, 35, 35)
    GOLD_DRK = (40, 32, 0)

    MEDAL_COLS = [GOLD_C, SILVER_C, BRONZE_C]

    # ── fonts ──
    fnt_title  = _font(_BOLD,    28)
    fnt_sub    = _font(_MONO_SM, 11)
    fnt_cat    = _font(_BOLD,    13)
    fnt_pos    = _font(_BOLD,    22)
    fnt_name   = _font(_BOLD,    16)
    fnt_rank   = _font(_MONO_SM, 10)
    fnt_val    = _font(_BOLD,    16)
    fnt_footer = _font(_MONO_SM, 10)

    # ── layout ──
    W       = 560
    PAD     = 22
    HDR_H   = 72
    TAB_H   = 32
    COL_H   = 24
    ROW_H   = 46
    FOOT_H  = 28
    n_rows  = len(rows)
    H       = HDR_H + TAB_H + COL_H + n_rows * ROW_H + FOOT_H + 8

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # ── top accent ──
    draw.rectangle([0, 0, W, 4], fill=ACCENT)

    # ── header ──
    draw.text((PAD, 14), "APEX LEADERBOARD", font=fnt_title, fill=WHITE)
    draw.text((PAD, 48), f"// DEAD FRONTIER  ·  {week}  ·  TOP {n_rows} MEMBERS //",
              font=fnt_sub, fill=(80, 80, 80))

    # ── category tab bar ──
    tab_y  = HDR_H
    tab_w  = W // len(LEADERBOARD_CATEGORIES)
    for i, (key, meta) in enumerate(LEADERBOARD_CATEGORIES.items()):
        tx1 = i * tab_w
        tx2 = tx1 + tab_w
        is_active = key == category
        draw.rectangle([tx1, tab_y, tx2, tab_y + TAB_H],
                       fill=(28, 22, 0) if is_active else (14, 14, 14))
        if is_active:
            draw.rectangle([tx1, tab_y, tx2, tab_y + 3], fill=GOLD_C)
        lbl   = meta["label"].upper()
        lbl_w = draw.textlength(lbl, font=fnt_cat)
        draw.text((tx1 + (tab_w - lbl_w) / 2, tab_y + 8), lbl,
                  font=fnt_cat, fill=GOLD_C if is_active else (70, 70, 70))

    draw.rectangle([0, tab_y + TAB_H, W, tab_y + TAB_H + 1], fill=DIV)

    # ── column headers ──
    col_y = HDR_H + TAB_H + 4
    draw.text((PAD + 36, col_y), "#  MEMBER", font=fnt_sub, fill=(60, 60, 60))
    val_lbl = cat_label
    vl_w    = draw.textlength(val_lbl, font=fnt_sub)
    draw.text((W - PAD - vl_w, col_y), val_lbl, font=fnt_sub, fill=(60, 60, 60))

    # ── rows ──
    row_y = HDR_H + TAB_H + COL_H + 4
    for i, row in enumerate(rows):
        pos      = i + 1
        bg_col   = PANEL if i % 2 == 0 else PANEL_B
        draw.rectangle([0, row_y, W, row_y + ROW_H], fill=bg_col)

        # left accent stripe for top 3
        if pos <= 3:
            stripe_col = MEDAL_COLS[pos - 1]
            draw.rectangle([0, row_y, 4, row_y + ROW_H], fill=stripe_col)

        # position number
        pos_col = MEDAL_COLS[pos - 1] if pos <= 3 else MUTED
        draw.text((PAD, row_y + (ROW_H - 22) // 2), str(pos),
                  font=fnt_pos, fill=pos_col)

        # name + rank badge
        uname    = row["username"]
        sp_rank  = row.get("sp_rank") or "Scout"
        rank_col = _CARD_RANK_COLORS.get(sp_rank.lower(), (150, 150, 150))

        name_x = PAD + 36
        name_y = row_y + 8
        draw.text((name_x, name_y), uname, font=fnt_name, fill=WHITE)

        badge_txt = sp_rank.upper()
        badge_w   = int(draw.textlength(badge_txt, font=fnt_rank)) + 10
        badge_y   = name_y + 18
        draw.rounded_rectangle([name_x, badge_y, name_x + badge_w, badge_y + 14],
                               radius=3, fill=(30, 30, 30), outline=(45, 45, 45))
        draw.text((name_x + 5, badge_y + 1), badge_txt, font=fnt_rank, fill=rank_col)

        # value (right-aligned)
        raw_val = safe_float(row["val"]) if category == "sp" else safe_int(row["val"])
        val_str = val_fmt(raw_val)
        val_col = GREEN if category == "sp" and raw_val > 0 else WHITE
        val_w   = draw.textlength(val_str, font=fnt_val)
        draw.text((W - PAD - val_w, row_y + (ROW_H - 16) // 2),
                  val_str, font=fnt_val, fill=val_col)

        row_y += ROW_H

    # ── divider + footer ──
    draw.rectangle([0, row_y, W, row_y + 1], fill=DIV)
    draw.text((PAD, row_y + 8),
              f"APEX CLAN  ·  DEAD FRONTIER  ·  use !leaderboard to view",
              font=fnt_footer, fill=(55, 55, 55))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


class LeaderboardView(discord.ui.View):
    """Tabbed buttons to switch leaderboard category."""

    CATS = [("sp", "⭐ SP Gain"), ("ts", "⚔️ Top Survivor"),
            ("tpk", "💀 Total Kills"), ("tl", "📦 Total Loots")]

    def __init__(self, active: str = "sp"):
        super().__init__(timeout=None)
        self.active = active
        for key, label in self.CATS:
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.success if key == active else discord.ButtonStyle.secondary,
                custom_id=f"lb_{key}"
            )
            btn.callback = self._make_callback(key)
            self.add_item(btn)

    def _make_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            conn      = get_conn()
            img_bytes = build_leaderboard_image(conn, key)
            conn.close()
            if not img_bytes:
                await interaction.response.send_message("❌ No leaderboard data available.", ephemeral=True)
                return
            new_view = LeaderboardView(active=key)
            await interaction.response.edit_message(
                attachments=[discord.File(io.BytesIO(img_bytes), filename="leaderboard.png")],
                view=new_view
            )
        return callback


# ══════════════════════════════════════════════
#  BEST WEEK LEADERBOARD
# ══════════════════════════════════════════════
BEST_CATEGORIES = {
    "ts":  {"label": "Top Survivor", "col": "weekly_ts",    "fmt": lambda v: fmt(v)},
    "tpk": {"label": "Total Kills",  "col": "weekly_tpk",   "fmt": lambda v: fmt(v)},
    "tl":  {"label": "Total Loots",  "col": "weekly_loots", "fmt": lambda v: fmt(v)},
}

def get_best_week_data(conn, category="ts"):
    """Top 10 single-week performances across all weeks — same player can appear multiple times."""
    cat = BEST_CATEGORIES[category]
    col = cat["col"]
    rows = conn.execute(f"""
        SELECT ws.username, wa.sp_rank, CAST(ws.{col} AS INTEGER) as val, ws.week
        FROM weekly_snapshots ws
        LEFT JOIN weekly_analysis wa
            ON wa.week = ws.week AND wa.username = ws.username
        WHERE ws.{col} IS NOT NULL AND ws.{col} != '' AND ws.{col} != '-'
          AND CAST(ws.{col} AS INTEGER) > 0
        ORDER BY CAST(ws.{col} AS INTEGER) DESC
        LIMIT 10
    """).fetchall()
    return [dict(r) for r in rows]


def build_best_image(conn, category="ts") -> bytes | None:
    rows = get_best_week_data(conn, category)
    if not rows:
        return None

    cat     = BEST_CATEGORIES[category]
    val_fmt = cat["fmt"]

    BG         = _CARD_BG
    PANEL      = (20, 20, 20)
    PANEL_B    = (17, 17, 17)
    WHITE      = _CARD_WHITE
    MUTED      = (90, 90, 90)
    GOLD_C     = _CARD_GOLD
    SILVER_C   = (180, 180, 180)
    BRONZE_C   = (160, 106, 53)
    DIV        = (35, 35, 35)
    MEDAL_COLS = [GOLD_C, SILVER_C, BRONZE_C]

    fnt_title  = _font(_BOLD,    28)
    fnt_sub    = _font(_MONO_SM, 10)
    fnt_cat    = _font(_BOLD,    13)
    fnt_pos    = _font(_BOLD,    22)
    fnt_name   = _font(_BOLD,    16)
    fnt_rank   = _font(_MONO_SM, 10)
    fnt_val    = _font(_BOLD,    16)
    fnt_week   = _font(_MONO_SM, 10)
    fnt_footer = _font(_MONO_SM, 10)

    W      = 580
    PAD    = 22
    HDR_H  = 72
    TAB_H  = 32
    COL_H  = 24
    ROW_H  = 46
    FOOT_H = 28
    H      = HDR_H + TAB_H + COL_H + len(rows) * ROW_H + FOOT_H + 8

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # accent bar — gold to distinguish from !leaderboard red
    draw.rectangle([0, 0, W, 4], fill=GOLD_C)
    draw.text((PAD, 14), "APEX BEST WEEK", font=fnt_title, fill=WHITE)
    draw.text((PAD, 48), "// DEAD FRONTIER  ·  TOP 10 SINGLE-WEEK RECORDS  ·  PLAYER CAN APPEAR MULTIPLE TIMES //",
              font=fnt_sub, fill=(75, 75, 75))

    # tab bar
    tab_y = HDR_H
    tab_w = W // len(BEST_CATEGORIES)
    for i, (key, meta) in enumerate(BEST_CATEGORIES.items()):
        tx1 = i * tab_w
        tx2 = tx1 + tab_w
        is_active = key == category
        draw.rectangle([tx1, tab_y, tx2, tab_y + TAB_H],
                       fill=(28, 22, 0) if is_active else (14, 14, 14))
        if is_active:
            draw.rectangle([tx1, tab_y, tx2, tab_y + 3], fill=GOLD_C)
        lbl   = meta["label"].upper()
        lbl_w = draw.textlength(lbl, font=fnt_cat)
        draw.text((tx1 + (tab_w - lbl_w) / 2, tab_y + 8), lbl,
                  font=fnt_cat, fill=GOLD_C if is_active else (70, 70, 70))

    draw.rectangle([0, tab_y + TAB_H, W, tab_y + TAB_H + 1], fill=DIV)

    # column headers
    col_y = HDR_H + TAB_H + 4
    draw.text((PAD + 36, col_y), "#  MEMBER", font=fnt_sub, fill=(60, 60, 60))
    rh_txt = "WEEK  |  VALUE"
    rh_w   = draw.textlength(rh_txt, font=fnt_sub)
    draw.text((W - PAD - rh_w, col_y), rh_txt, font=fnt_sub, fill=(60, 60, 60))

    # rows
    row_y = HDR_H + TAB_H + COL_H + 4
    for i, row in enumerate(rows):
        pos    = i + 1
        bg_col = PANEL if i % 2 == 0 else PANEL_B
        draw.rectangle([0, row_y, W, row_y + ROW_H], fill=bg_col)

        if pos <= 3:
            draw.rectangle([0, row_y, 4, row_y + ROW_H], fill=MEDAL_COLS[pos - 1])

        pos_col = MEDAL_COLS[pos - 1] if pos <= 3 else MUTED
        draw.text((PAD, row_y + (ROW_H - 22) // 2), str(pos), font=fnt_pos, fill=pos_col)

        uname    = row["username"]
        sp_rank  = row.get("sp_rank") or "Scout"
        rank_col = _CARD_RANK_COLORS.get(sp_rank.lower(), (150, 150, 150))

        name_x = PAD + 36
        name_y = row_y + 8
        draw.text((name_x, name_y), uname, font=fnt_name, fill=WHITE)

        badge_txt = sp_rank.upper()
        badge_w   = int(draw.textlength(badge_txt, font=fnt_rank)) + 10
        badge_y   = name_y + 18
        draw.rounded_rectangle([name_x, badge_y, name_x + badge_w, badge_y + 14],
                               radius=3, fill=(30, 30, 30), outline=(45, 45, 45))
        draw.text((name_x + 5, badge_y + 1), badge_txt, font=fnt_rank, fill=rank_col)

        # right side: week tag | value
        raw_val  = safe_int(row["val"])
        val_str  = val_fmt(raw_val)
        week_str = str(row.get("week") or "")
        val_w    = draw.textlength(val_str, font=fnt_val)
        week_w   = draw.textlength(week_str, font=fnt_week)
        sep_w    = draw.textlength("  |  ", font=fnt_week)
        bx       = W - PAD - week_w - sep_w - val_w
        mid_y    = row_y + (ROW_H - 16) // 2

        draw.text((bx, mid_y + 3), week_str, font=fnt_week, fill=MUTED)
        draw.text((bx + week_w, mid_y + 3), "  |  ", font=fnt_week, fill=(50, 50, 50))
        draw.text((bx + week_w + sep_w, mid_y), val_str, font=fnt_val, fill=GOLD_C)

        row_y += ROW_H

    draw.rectangle([0, row_y, W, row_y + 1], fill=DIV)
    draw.text((PAD, row_y + 8),
              "APEX CLAN  ·  DEAD FRONTIER  ·  use !best to view best week records",
              font=fnt_footer, fill=(55, 55, 55))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


class BestView(discord.ui.View):
    """Tabbed buttons for !best command."""

    CATS = [("ts", "⚔️ Top Survivor"), ("tpk", "💀 Total Kills"), ("tl", "📦 Total Loots")]

    def __init__(self, active: str = "ts"):
        super().__init__(timeout=None)
        self.active = active
        for key, label in self.CATS:
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.success if key == active else discord.ButtonStyle.secondary,
                custom_id=f"best_{key}"
            )
            btn.callback = self._make_callback(key)
            self.add_item(btn)

    def _make_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            conn      = get_conn()
            img_bytes = build_best_image(conn, key)
            conn.close()
            if not img_bytes:
                await interaction.response.send_message("❌ No data available.", ephemeral=True)
                return
            await interaction.response.edit_message(
                attachments=[discord.File(io.BytesIO(img_bytes), filename="best.png")],
                view=BestView(active=key)
            )
        return callback


# ══════════════════════════════════════════════
#  DUE DATE NOTIFICATIONS
# ══════════════════════════════════════════════
# This marker is embedded in every due DM so the bot can detect it in DM history
# and avoid sending duplicates — format: APEX_DUE::<item_name>::<due_date>
DUE_MARKER_PREFIX = "APEX_DUE::"

def _make_marker(item_name: str, due_date: str) -> str:
    return f"{DUE_MARKER_PREFIX}{item_name}::{due_date}"

async def _already_notified(user: discord.User, item_name: str, due_date: str) -> bool:
    """Check the bot's DM history with this user for the unique marker in embed footers."""
    marker = _make_marker(item_name, due_date)
    try:
        dm = await user.create_dm()
        async for msg in dm.history(limit=50):
            if msg.author != client.user:
                continue
            # marker is stored in embed footer text
            for embed in msg.embeds:
                if embed.footer and embed.footer.text and marker in embed.footer.text:
                    return True
    except Exception:
        pass
    return False

@tasks.loop(hours=24, reconnect=True)
async def due_date_check():
    """Fetch armory daily and DM borrowers whose items are due today."""
    today = date.today()

    items, err = await asyncio.get_event_loop().run_in_executor(None, fetch_armory)
    if err or not items:
            return

    conn = get_conn()
    all_items = [i for v in items.values() for i in v]
    borrowed  = [i for i in all_items if i["status"] == "borrowed"]

    for item in all_items:
        if item["status"] != "borrowed" or not item["due_date"] or not item["borrowed_by"]:
            continue

        due_date_str = item["due_date"].strip()
        due = None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y", "%d/%m/%y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
            try:
                due = datetime.strptime(due_date_str, fmt).date()
                break
            except ValueError:
                continue


        if due is None or due != today:
            continue

        row = conn.execute(
            "SELECT discord_id FROM discord_members WHERE LOWER(username) = LOWER(?)",
            (item["borrowed_by"],)
        ).fetchone()

        if not row:
                    continue


        try:
            user = await client.fetch_user(int(row["discord_id"]))
        except Exception as e:
            continue

        already = await _already_notified(user, item["name"], due_date_str)
        if already:
            continue

        marker = _make_marker(item["name"], due_date_str)
        desc = (
            f"Hey **{item['borrowed_by']}**, your borrowed item is due back today!\n\n"
            f"Please return **{item['name']}** to the clan armory or contact an Officer "
            f"to arrange an extension."
        )
        embed = discord.Embed(
            title="⏰  Armory Item Due Today",
            description=desc,
            color=0xe74c3c
        )
        embed.add_field(name="Item",     value=f"**{item['name']}** ({item['section'].capitalize()})", inline=True)
        embed.add_field(name="Due Date", value=due_date_str, inline=True)
        embed.set_footer(text=f"APEX Clan · Dead Frontier · {marker}")

        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass
        except Exception:
            pass

    conn.close()

@due_date_check.before_loop
async def before_due_check():
    await client.wait_until_ready()
    await due_date_check()  # run once immediately on startup


@client.event
async def on_ready():
    # Re-register persistent views so fulfill buttons work after restarts
    client.add_view(ArmoryFulfillView(requester_id=0, requester_name="", item_name=""))
    client.add_view(LeaderboardView())
    client.add_view(BestView())
    due_date_check.start()
    print(f"✅ {client.user} is online.")
    print(f"   Listening for: !help, !register, !unregister, !stats, !mystats, !armory, !applyofficer, !assignroles, !weeklysummary, !leaderboard, !best")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.strip()
    parts   = content.split(maxsplit=1)
    cmd     = parts[0].lower() if parts else ""

    # ── !help ──
    if cmd == "!help":
        embed = discord.Embed(
            title="⚔️  APEX Clan Bot — Commands",
            description="`// Dead Frontier · APEX Clan tracker bot //`",
            color=0xe74c3c
        )
        embed.add_field(
            name="👤  Member Commands",
            value=(
                "`!register <ingame_username>` — Link your Discord to your in-game name\n"
                "`!mystats` — View your own stats card (requires `!register` first)\n"
                "`!stats <ingame_username>` — View stats card for any clan member\n"
                "`!leaderboard` — View clan top 10 rankings (SP, TS, Kills, Loots)\n"
                "`!best` — View all-time best single-week records (TS, Kills, Loots)"
            ),
            inline=False
        )
        embed.add_field(
            name="⚔️  Armory Commands",
            value=(
                "`!armory` — View the full clan armory inventory\n"
                "`!armory request <item name>` — Request to borrow an item (requires `!register`)"
            ),
            inline=False
        )
        embed.add_field(
            name="🔒  Admin Only Commands",
            value=(
                "`!unregister <ingame_username>` — Remove or correct a registration\n"
                "`!assignroles` — Assign Discord roles based on current SP ranks\n"
                "`!weeklysummary` — Post the weekly summary image"
            ),
            inline=False
        )
        embed.add_field(
            name="⭐  Promotion",
            value="`!applyofficer` — Check eligibility and apply for Officer promotion",
            inline=False
        )
        embed.add_field(
            name="⭐  SP Rank Tiers",
            value=(
                "`Scout` → `Apex Scout` → `Ranger` → `Apex Ranger` → `Templar`\n"
                "→ `Apex Templar` → `Officer` → `Apex Officer` → `Axiom`"
            ),
            inline=False
        )
        embed.set_footer(text="APEX Clan · Dead Frontier")
        await message.channel.send(embed=embed)
        return

    # ── !register ──
    elif cmd == "!register":
        if len(parts) < 2:
            await message.channel.send("Usage: `!register <ingame_username>`")
            return

        query = parts[1].strip()
        conn  = get_conn()
        ensure_discord_table(conn)

        # Check 1: this Discord account already registered
        existing = conn.execute(
            "SELECT username FROM discord_members WHERE discord_id = ?", (str(message.author.id),)
        ).fetchone()
        if existing:
            conn.close()
            await message.channel.send(
                f"❌ You are already registered as **{existing['username']}**. "
                f"Contact an admin if you need to change this."
            )
            return

        username = find_username(conn, query)
        if not username:
            conn.close()
            await message.channel.send(f"❌ **{query}** not found in APEX roster. Check your in-game name spelling.")
            return

        # Check 2: this in-game name already claimed by someone else
        claimed = conn.execute(
            "SELECT discord_id FROM discord_members WHERE username = ?", (username,)
        ).fetchone()
        if claimed:
            conn.close()
            await message.channel.send(
                f"❌ **{username}** is already registered by another Discord account. "
                f"Contact an admin if this is a mistake."
            )
            return

        register_member(conn, message.author.id, username)
        conn.close()
        await message.channel.send(
            f"✅ **{message.author.display_name}** registered as **{username}**. "
            f"You can now use `!mystats` to see your stats."
        )

    # ── !unregister (admin only) ──
    elif cmd == "!unregister":
        if message.author.id != ADMIN_ID:
            await message.channel.send("❌ Only the clan admin can use this command.")
            return
        if len(parts) < 2:
            await message.channel.send("Usage: `!unregister <ingame_username>`")
            return

        ingame = parts[1].strip()
        conn   = get_conn()
        unregister_member(conn, ingame)
        conn.close()
        await message.channel.send(f"✅ Registration for **{ingame}** has been removed.")

    # ── !stats ──
    elif cmd == "!stats":
        if len(parts) < 2:
            await message.channel.send("Usage: `!stats <ingame_username>`")
            return

        query = parts[1].strip()
        conn  = get_conn()
        username = find_username(conn, query)

        if not username:
            conn.close()
            await message.channel.send(f"❌ Player **{query}** not found in APEX roster.")
            return

        img_bytes = build_stats_image(conn, username)
        conn.close()

        if not img_bytes:
            await message.channel.send(f"❌ No data found for **{username}** this week.")
            return

        await message.channel.send(file=discord.File(io.BytesIO(img_bytes), filename="stats.png"))

    # ── !mystats ──
    elif cmd == "!mystats":
        conn     = get_conn()
        username = get_ingame_name(conn, message.author.id)

        if not username:
            conn.close()
            await message.channel.send(
                f"❌ You're not registered yet. Use `!register <ingame_username>` first."
            )
            return

        img_bytes = build_stats_image(conn, username)
        conn.close()

        if not img_bytes:
            await message.channel.send(f"❌ No data found for **{username}** this week.")
            return

        await message.channel.send(file=discord.File(io.BytesIO(img_bytes), filename="stats.png"))

    # ── !assignroles (admin only) ──

    elif cmd == "!armory":
        sub = parts[1].strip().split()[0].lower() if len(parts) > 1 else ""

        if sub == "request":
            req_parts  = message.content.split(None, 2)
            item_query = req_parts[2].strip() if len(req_parts) > 2 else ""

            if not item_query:
                await message.channel.send("Usage: `!armory request <item name>`")
                return

            conn     = get_conn()
            username = get_ingame_name(conn, message.author.id)
            # Also fetch member's current SP rank
            member_rank = None
            if username:
                cur = conn.execute(
                    "SELECT sp_rank FROM weekly_analysis WHERE username=? ORDER BY week DESC LIMIT 1",
                    (username,)
                )
                row = cur.fetchone()
                if row:
                    member_rank = row[0]
            conn.close()
            if not username:
                await message.channel.send("❌ You need to `!register` first.")
                return

            items, err = fetch_armory()
            if err or items is None:
                await message.channel.send(f"❌ Could not fetch armory: `{err}`")
                return

            item = find_armory_item(items, item_query)
            if not item:
                await message.channel.send(f"❌ **{item_query}** not found. Check spelling and try again.")
                return

            req_channel = discord.utils.get(message.guild.channels, name=ARMORY_REQUEST_CHANNEL)
            if not req_channel:
                await message.channel.send(f"❌ Channel #{ARMORY_REQUEST_CHANNEL} not found.")
                return

            # Check rank requirement
            if item["rank_req"] and member_rank:
                req_idx    = SP_RANKS.index(item["rank_req"]) if item["rank_req"] in SP_RANKS else 0
                member_idx = SP_RANKS.index(member_rank) if member_rank in SP_RANKS else 0
                if member_idx < req_idx:
                    await message.channel.send(
                        f"❌ You don't meet the rank requirement for **{item['name']}**. "
                        f"Required: **{item['rank_req']}** · Your rank: **{member_rank}**"
                    )
                    return

            if item["status"] == "available":
                status_note = "✅ Currently available"
                confirm     = f"✅ Request for **{item['name']}** sent. Admin will be in touch shortly."
            else:
                status_note = (f"⊘ Borrowed by **{item['borrowed_by']}**"
                               + (f" · due {item['due_date']}" if item["due_date"] else "")
                               + "\n📋 Queue request — fulfilled when returned.")
                confirm = f"✅ **{item['name']}** is borrowed. You've been queued and will be notified when available."

            req_embed = discord.Embed(title="📥  New Armory Request",
                                      color=0xf1c40f if item["status"] == "available" else 0xe74c3c)
            req_embed.add_field(name="Member", value=f"{message.author.mention} ({username})", inline=True)
            req_embed.add_field(name="Item",   value=f"**{item['name']}** ({item['section'].capitalize()})", inline=True)
            req_embed.add_field(name="Status", value=status_note, inline=False)
            if item["rank_req"]:
                rank_met = "✅ Met" if (not member_rank or SP_RANKS.index(member_rank if member_rank in SP_RANKS else "Scout") >= SP_RANKS.index(item["rank_req"] if item["rank_req"] in SP_RANKS else "Scout")) else "❌ Not met"
                req_embed.add_field(name="Min Rank", value=f"{item['rank_req']} · {rank_met}", inline=True)
            req_embed.set_footer(text=f"Requested {message.created_at.strftime('%Y-%m-%d %H:%M UTC')}")

            # Post to #armory-requests (no button — just the log)
            await req_channel.send(embed=req_embed)

            # Post to #applications with the fulfill button for officers
            app_channel = discord.utils.get(message.guild.channels, name=PROMOTION_APP_CHANNEL)
            if app_channel:
                officer_embed = discord.Embed(
                    title="📥  Armory Request — Pending Fulfillment",
                    description=(
                        f"{message.author.mention} (**{username}**) has requested an item from the armory.\n"
                        f"An Officer or above can click the button below once it has been handed off."
                    ),
                    color=0xf1c40f if item["status"] == "available" else 0xe74c3c
                )
                officer_embed.add_field(name="Item",   value=f"**{item['name']}** ({item['section'].capitalize()})", inline=True)
                officer_embed.add_field(name="Status", value=status_note, inline=True)
                if item["rank_req"]:
                    officer_embed.add_field(name="Min Rank", value=item["rank_req"], inline=True)
                officer_embed.set_footer(text=f"Requested {message.created_at.strftime('%Y-%m-%d %H:%M UTC')} · APEX Clan")

                view = ArmoryFulfillView(
                    requester_id=message.author.id,
                    requester_name=username,
                    item_name=item["name"]
                )
                await app_channel.send(embed=officer_embed, view=view)

            await message.channel.send(confirm)
            return

        items, err = fetch_armory()
        if err or items is None:
            await message.channel.send(f"❌ Could not load armory: `{err}`")
            return
        img_bytes = build_armory_image(items)
        await message.channel.send(file=discord.File(io.BytesIO(img_bytes), filename="armory.png"))

    elif cmd == "!applyofficer":
        conn     = get_conn()
        username = get_ingame_name(conn, message.author.id)

        if not username:
            conn.close()
            await message.channel.send("❌ You need to `!register` first before applying.")
            return

        eligible, failures = check_promotion_eligibility(conn, username, message.author)
        conn.close()

        if not eligible:
            embed = discord.Embed(
                title="❌  Officer Promotion — Requirements Not Met",
                description=f"**{message.author.display_name}**, you do not meet all the requirements to apply for Officer.\n",
                color=0xe74c3c
            )
            embed.add_field(
                name="Unmet Requirements",
                value="\n".join(failures),
                inline=False
            )
            embed.add_field(
                name="Full Requirements",
                value=(
                    f"✅ Minimum SP Rank: **{OFFICER_MIN_RANK}**\n"
                    f"✅ Discord Role: **@{OFFICER_DISCORD_ROLE}**\n"
                    f"✅ Unique Medals: **{OFFICER_MIN_MEDALS}** or more"
                ),
                inline=False
            )
            embed.set_footer(text="APEX Clan · Keep grinding and apply when you're ready.")
            await message.channel.send(embed=embed)
            return

        # Requirements met — send application form via DM
        try:
            dm = await message.author.create_dm()
            await dm.send(embed=discord.Embed(
                title="⭐  APEX Clan — Officer Promotion Application",
                description=(
                    f"Welcome, **{username}**. You have met the requirements for Officer promotion.\n\n"
                    f"Please answer each question below. Reply to each one individually — "
                    f"I will collect your answers and submit your application automatically.\n\n"
                    f"Type `cancel` at any time to abort."
                ),
                color=0xffd700
            ))

            answers = {}
            for i, question in enumerate(OFFICER_APP_QUESTIONS, 1):
                await dm.send(f"**Q{i}/{len(OFFICER_APP_QUESTIONS)}: {question}**")

                def check(m):
                    return m.author == message.author and isinstance(m.channel, discord.DMChannel)

                try:
                    response = await client.wait_for("message", check=check, timeout=300)
                except asyncio.TimeoutError:
                    await dm.send("⏰ Application timed out. Run `!applyofficer` again to restart.")
                    return

                if response.content.strip().lower() == "cancel":
                    await dm.send("❌ Application cancelled.")
                    return

                answers[f"Q{i}"] = response.content.strip()

            # Post completed application to officer-applications channel
            app_channel = discord.utils.get(message.guild.channels, name=PROMOTION_APP_CHANNEL)
            if not app_channel:
                await dm.send(f"⚠️ Application completed but could not find #{PROMOTION_APP_CHANNEL} channel. Contact an admin.")
                return

            app_embed = discord.Embed(
                title="📋  Officer Promotion Application",
                description=f"{message.author.mention} · In-game: **{username}**",
                color=0xffd700
            )
            for i, question in enumerate(OFFICER_APP_QUESTIONS, 1):
                app_embed.add_field(
                    name=f"Q{i}: {question}",
                    value=answers[f"Q{i}"] or "—",
                    inline=False
                )
            app_embed.set_footer(text=f"Submitted {message.created_at.strftime('%Y-%m-%d %H:%M UTC')} · APEX Clan")

            await app_channel.send(embed=app_embed)
            await dm.send("✅ Your application has been submitted! The admin team will review it shortly. Good luck! 🏆")
            await message.channel.send(f"✅ **{message.author.display_name}** — your application has been submitted. Check your DMs.")

        except discord.Forbidden:
            await message.channel.send("❌ Could not send you a DM. Please enable DMs from server members and try again.")

    elif cmd == "!leaderboard":
        conn      = get_conn()
        img_bytes = build_leaderboard_image(conn, "sp")
        conn.close()
        if not img_bytes:
            await message.channel.send("❌ No leaderboard data available yet.")
            return
        view = LeaderboardView(active="sp")
        await message.channel.send(
            file=discord.File(io.BytesIO(img_bytes), filename="leaderboard.png"),
            view=view
        )

    elif cmd == "!best":
        conn      = get_conn()
        img_bytes = build_best_image(conn, "ts")
        conn.close()
        if not img_bytes:
            await message.channel.send("❌ No best week data available yet.")
            return
        await message.channel.send(
            file=discord.File(io.BytesIO(img_bytes), filename="best.png"),
            view=BestView(active="ts")
        )

    elif cmd == "!weeklysummary":
        if message.author.id != ADMIN_ID:
            await message.channel.send("❌ Only the clan admin can use this command.")
            return
        conn = get_conn()
        data = get_weekly_summary_data(conn)
        conn.close()
        if not data:
            await message.channel.send("❌ No weekly data found in the database.")
            return
        await message.channel.send("⏳ Generating weekly summary...")
        img_bytes = build_weekly_summary_image(data)
        await message.channel.send(file=discord.File(io.BytesIO(img_bytes), filename="weekly_summary.png"))

    elif cmd == "!assignroles":
        if message.author.id != ADMIN_ID:
            await message.channel.send("❌ Only the clan admin can use this command.")
            return

        await message.channel.send("⏳ Assigning roles, please wait...")
        conn    = get_conn()
        results = await assign_roles_for_guild(message.guild, conn)
        conn.close()

        lines = []
        if results["updated"]:
            lines.append("✅ **Updated:**\n" + "\n".join(f"  • {r}" for r in results["updated"]))
        if results["not_found"]:
            lines.append("⚠️ **Not found in Discord:**\n" + "\n".join(f"  • {r}" for r in results["not_found"]))
        if results["no_role"]:
            lines.append("⚠️ **Missing roles in server:**\n" + "\n".join(f"  • {r}" for r in results["no_role"]))
        if results["already_set"] and not results["updated"]:
            lines.append(f"✅ All {len(results['already_set'])} member(s) already have the correct role.")
        if not lines:
            lines.append("No registered members found.")

        await message.channel.send("\n\n".join(lines) or "Done.")

    # Required for commands.Bot to process prefix commands
    await client.process_commands(message)

if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_TOKEN not found in .env file.")
    else:
        client.run(TOKEN)
