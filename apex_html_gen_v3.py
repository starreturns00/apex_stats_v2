"""
APEX CLAN - HTML Generator v3
Reads from weekly_analysis + weekly_snapshots → generates apex_dashboard.html
No calculations — all data comes pre-computed from weekly_analysis
"""

import sqlite3
import json
from datetime import datetime

# ===== CONFIGURATION =====
DB_FILE = "apex_clan_v3.db"
OUTPUT_FILE = "index.html"

print("=" * 70)
print("🏆 A P E X CLAN - HTML GENERATOR v3 🏆")
print("=" * 70)

# ===== HELPERS =====
def safe_float(val, default=0):
    if val is None or val == '' or val == '-':
        return default
    try:
        return float(val)
    except:
        return default

def safe_int(val, default=0):
    if val is None or val == '' or val == '-':
        return default
    try:
        return int(float(val))
    except:
        return default

RANK_NEXT = {
    'Scout':        ('Apex Scout',   50),
    'Apex Scout':   ('Ranger',       120),
    'Ranger':       ('Apex Ranger',  200),
    'Apex Ranger':  ('Templar',      300),
    'Templar':      ('Apex Templar', 400),
    'Apex Templar': (None, None),
    'Officer':      (None, None),
    'Apex Officer': (None, None),
    'Axiom':        (None, None),
}

def get_progress_to_next(star_points, sp_rank):
    next_rank, threshold = RANK_NEXT.get(sp_rank, (None, None))
    if next_rank is None:
        return 'Max Rank'
    return f'{threshold - star_points:.1f} SP to {next_rank}'

def get_badge_class(sp_rank):
    r = (sp_rank or '').lower()
    if 'axiom' in r:            return 'badge-axiom'
    if 'apex officer' in r:     return 'badge-apex-officer'
    if 'officer' in r:          return 'badge-officer'
    if 'apex templar' in r:     return 'badge-apex-templar'
    if 'templar' in r:          return 'badge-templar'
    if 'apex ranger' in r:      return 'badge-apex-ranger'
    if 'ranger' in r:           return 'badge-ranger'
    if 'apex scout' in r:       return 'badge-apex-scout'
    if 'scout' in r:            return 'badge-scout'
    return 'badge-scout'

def rank_str_to_sp(rank_str):
    if not rank_str:
        return 0
    try:
        r = int(str(rank_str).replace('#', '').strip())
        if r == 1:   return 50
        if r <= 5:   return 30
        if r <= 10:  return 20
        if r <= 25:  return 10
    except:
        pass
    return 0

def enhance_story(story_text):
    if not story_text or "No story" in story_text:
        return story_text
    raw_lines = story_text.split('\n')
    enhanced_lines = []
    keywords = [
        ('PROMOTED TO', '#e74c3c'), ('promoted to', '#e74c3c'),
        ('Woohoo!', '#27ae60'), ('On fire!', '#e74c3c'),
        ('Building heat', '#f39c12'), ('Gaining momentum', '#3498db'),
        ('Steady climb', '#27ae60'), ('MAXIMUM MOMENTUM!', '#27ae60'),
        ('Huge gains!', '#e74c3c'), ('personal best', '#9b59b6')
    ]
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        for keyword, color in keywords:
            line = line.replace(keyword, f'<strong style="color: {color}; font-weight: 800;">{keyword}</strong>')
        line = line.replace('personal best TS',  '<strong style="color: #e74c3c;">💎 personal best TS</strong>')
        line = line.replace('personal best TPK', '<strong style="color: #e74c3c;">⚔️ personal best TPK</strong>')
        line = line.replace('personal best TL',  '<strong style="color: #e74c3c;">📦 personal best TL</strong>')
        if "📅 ━━" in line:
            line = f'<div style="background: linear-gradient(90deg, #e74c3c 0%, #c0392b 100%); color: white; padding: 10px 15px; border-radius: 8px; margin: 15px 0; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">{line}</div>'
        elif "🎖️" in line:
            line = f'<div style="background: #ffd700; color: #8b6914; padding: 12px 15px; border-radius: 8px; margin: 20px 0; font-weight: bold; border-left: 5px solid #daa520; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">{line} 🎉</div>'
        elif "🏆" in line:
            line = f'<div style="background: #8e44ad; color: white; padding: 12px 15px; border-radius: 8px; margin: 10px 0; font-weight: bold; border-left: 5px solid #713391; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">{line}</div>'
        elif line.startswith('→'):
            line = f'<span style="display: block; margin-left: 10px; margin-bottom: 5px;">{line}</span>'
        enhanced_lines.append(line)
    return "".join(enhanced_lines)

# ===== CONNECT =====
conn = sqlite3.connect(DB_FILE)
conn.row_factory = sqlite3.Row

# ===== CURRENT WEEK =====
row = conn.execute("SELECT week FROM weekly_analysis ORDER BY week DESC LIMIT 1").fetchone()
if not row:
    print("❌ No data in weekly_analysis. Run apex_calc_v3.py first.")
    conn.close()
    exit(1)
current_week = row['week']
print(f"📅 Current game week: {current_week}")

# ===== ALL WEEKS =====
all_weeks = [r['week'] for r in conn.execute(
    "SELECT DISTINCT week FROM weekly_analysis ORDER BY week ASC"
).fetchall()]

# ===== READ CURRENT WEEK DATA =====
print("📊 Reading current week data...")

current_rows = conn.execute("""
    SELECT wa.*, ws.level, ws.rank as game_rank,
           ws.weekly_ts, ws.weekly_tpk, ws.weekly_loots,
           ws.weekly_ts_rank, ws.weekly_tpk_rank, ws.weekly_tl_rank,
           ws.alltime_ts, ws.alltime_tpk, ws.alltime_loots, ws.day_joined
    FROM weekly_analysis wa
    JOIN weekly_snapshots ws ON wa.week = ws.week AND wa.username = ws.username
    WHERE wa.week = ?
    AND (ws.day_left IS NULL OR ws.day_left = '')
    ORDER BY wa.star_points DESC
""", (current_week,)).fetchall()

# ===== BUILD PLAYERS LIST =====
players = []
player_list = []
for i, row in enumerate(current_rows):
    sp = round(safe_float(row['star_points']), 1)
    sp_rank = row['sp_rank'] or 'Scout'
    # Progress bar percentage
    next_rank, threshold = RANK_NEXT.get(sp_rank, (None, None))
    if threshold:
        prev_thresholds = {
            'Apex Scout':   50,
            'Ranger':       120,
            'Apex Ranger':  200,
            'Templar':      300,
            'Apex Templar': 400,
        }
        prev_thresh = prev_thresholds.get(sp_rank, 0)
        progress_pct = min(100, round((sp - prev_thresh) / (threshold - prev_thresh) * 100, 1))
    else:
        progress_pct = 100
    players.append({
        'rank':             i + 1,
        'username':         row['username'],
        'level':            safe_int(row['level']),
        'game_rank':        row['game_rank'] or 'Unknown',
        'sp_rank':          sp_rank,
        'sp':               sp,
        'change':           round(safe_float(row['sp_change']), 1),
        'progress_to_next': get_progress_to_next(sp, sp_rank),
        'progress_pct':     progress_pct,
        'streak':           safe_int(row['current_streak']),
        'activity':         row['activity_status'] or '—',
        'is_promoted':      safe_int(row['is_promoted']),
        'cum_sp_clan':      round(safe_float(row['cum_sp_clan']), 6),
        'sp_alltime':       round(safe_float(row['sp_alltime']), 6),
        'cum_sp_events':    round(safe_float(row['cum_sp_events']), 6),
        'cum_sp_weekly':    round(safe_float(row['cum_sp_weekly']), 6),
        'sp_carryover':     round(safe_float(row['sp_carryover']), 6),
        'sp_clan':          round(safe_float(row['sp_clan']), 6),
        'weekly_ts':        safe_int(row['weekly_ts']),
        'weekly_tpk':       safe_int(row['weekly_tpk']),
        'weekly_loots':     safe_int(row['weekly_loots']),
        'level_sp':         round(safe_float(row['level_sp']), 6),
        'alltime_ts_base':  round(safe_float(row['alltime_ts_base']), 6),
        'alltime_tpk_base': round(safe_float(row['alltime_tpk_base']), 6),
        'alltime_tl_base':  round(safe_float(row['alltime_tl_base']), 6),
        'alltime_ts':       safe_int(row['alltime_ts']),
        'alltime_tpk':      safe_int(row['alltime_tpk']),
        'alltime_loots':    safe_int(row['alltime_loots']),
        'day_joined':       row['day_joined'] or '',
        'ts_rank':          row['weekly_ts_rank'] or '',
        'tpk_rank':         row['weekly_tpk_rank'] or '',
        'tl_rank':          row['weekly_tl_rank'] or '',
    })
    player_list.append(row['username'])

# ===== ACTIVITY DASHBOARD =====
print("🔥 Building activity data...")

# Build per-player activity map: username -> {week: is_active}
all_activity_map = {}
for r in conn.execute("SELECT username, week, is_active FROM weekly_analysis ORDER BY week ASC").fetchall():
    all_activity_map.setdefault(r['username'], {})[r['week']] = r['is_active']

# Summary stats
perfect_streak_players = [p for p in players if p['streak'] == len(all_weeks)]
activity_this_week = sum(1 for r in current_rows if r['is_active'] == '✓')
activity_rate_val  = round(activity_this_week / len(current_rows) * 100) if current_rows else 0
inactive_count     = sum(1 for p in players if p['streak'] == 0)
max_streak_val     = max((p['streak'] for p in players), default=0)

activity_data = []
for row in current_rows:
    username = row['username']
    # Build ordered list of (week_label, is_active) for all weeks
    week_cells = []
    for w in all_weeks:
        act = all_activity_map.get(username, {}).get(w, '🚫')
        week_cells.append((w, act))
    activity_data.append({
        'username':        username,
        'current_streak':  safe_int(row['current_streak']),
        'best_streak':     safe_int(row['best_streak']),
        'week_cells':      week_cells,
        'activity_status': row['activity_status'] or '—',
    })

# Sort by streak desc
activity_sorted = sorted(activity_data, key=lambda x: x['current_streak'], reverse=True)

# ===== CHART DATA =====
print("📈 Building chart data...")

# CAROT - activity rate per week
carot_data = {'weeks': [], 'activity_rate': []}
for week in all_weeks:
    recs = conn.execute("""
        SELECT wa.is_active FROM weekly_analysis wa
        JOIN weekly_snapshots ws ON wa.week = ws.week AND wa.username = ws.username
        WHERE wa.week = ?
        AND (ws.day_left IS NULL OR ws.day_left = '')
    """, (week,)).fetchall()
    if recs:
        active = sum(1 for r in recs if r['is_active'] == '✓')
        carot_data['weeks'].append(week)
        carot_data['activity_rate'].append(round(active / len(recs) * 100, 1))

# SPDR - SP rank distribution current week
spdr_counts = {}
for row in current_rows:
    sp_rank = row['sp_rank'] or 'Scout'
    spdr_counts[sp_rank] = spdr_counts.get(sp_rank, 0) + 1
spdr_data = {'ranks': list(spdr_counts.keys()), 'counts': list(spdr_counts.values())}

# CSBS - current vs best streaks
best_streak_map = {
    r['username']: safe_int(r['best'])
    for r in conn.execute("SELECT username, MAX(best_streak) as best FROM weekly_analysis GROUP BY username").fetchall()
}
csbs_data = {'current': [], 'best': []}
for p in players:
    csbs_data['current'].append({'user': p['username'], 'value': p['streak']})
    csbs_data['best'].append({'user': p['username'], 'value': best_streak_map.get(p['username'], 0)})

# SP over time per player
all_player_sp_data = {}
for username in player_list:
    sp_hist = conn.execute("""
        SELECT week, star_points FROM weekly_analysis
        WHERE username = ? ORDER BY week ASC
    """, (username,)).fetchall()
    all_player_sp_data[username] = {
        'weeks': [r['week'] for r in sp_hist],
        'sp':    [round(safe_float(r['star_points']), 1) for r in sp_hist]
    }

# ===== MEDALS OF HONOR DATA =====
print("🎖️  Building Medals of Honor data...")

# ── Load medal definitions from DB ──
# Sorted by sort_order ASC so Bronze < Silver < Gold < Platinum within each category
_medal_defs_raw = conn.execute(
    "SELECT category, tier, display_name, icon, threshold, cash_reward, sort_order "
    "FROM medal_definitions ORDER BY category, sort_order ASC"
).fetchall()

# Build per-category threshold lists: {category: [(tier, threshold, cash_reward), ...]}
# TS/TPK/TL/Streak: higher value = higher tier (normal)
# Global: lower rank number = higher tier (lower_is_better)
_LOWER_IS_BETTER_CATS = {'global'}
_medal_thresholds = {}  # {cat: [(tier, threshold, cash_reward), ...]} sorted Bronze→Platinum
_medal_icons = {}
_medal_display_names = {}
for r in _medal_defs_raw:
    cat = r['category']
    _medal_thresholds.setdefault(cat, []).append((r['tier'], safe_int(r['threshold']), safe_int(r['cash_reward'])))
    _medal_icons[cat]         = r['icon']
    _medal_display_names[cat] = r['display_name']

# ── Historical data needed for detection ──

# TS / TPK / TL — check each week in weekly_snapshots
# A player earns a tier if they crossed that threshold in ANY single week
_all_snaps = conn.execute(
    "SELECT username, weekly_ts, weekly_tpk, weekly_loots FROM weekly_snapshots"
).fetchall()
_snaps_by_user = {}
for r in _all_snaps:
    _snaps_by_user.setdefault(r['username'], []).append(r)

# Streak — check best_streak from weekly_analysis
# A player earns a tier if their best_streak ever >= threshold
_best_streaks = {r['username']: safe_int(r['bs']) for r in conn.execute(
    "SELECT username, MAX(best_streak) as bs FROM weekly_analysis GROUP BY username"
).fetchall()}

# Global — check weekly_ts_rank, weekly_tpk_rank, weekly_tl_rank in weekly_snapshots
# A player earns a tier if their best rank ever <= threshold (lower rank number = better)
_all_rank_rows = conn.execute(
    "SELECT username, weekly_ts_rank, weekly_tpk_rank, weekly_tl_rank FROM weekly_snapshots"
).fetchall()
_best_global = {}
for r in _all_rank_rows:
    for col in ('weekly_ts_rank', 'weekly_tpk_rank', 'weekly_tl_rank'):
        val = r[col]
        if val:
            try:
                n = int(str(val).replace('#', '').strip())
                if n > 0:
                    u = r['username']
                    _best_global[u] = min(_best_global.get(u, 9999), n)
            except:
                pass

# Event wins — count rows in event_rewards WHERE event_id NOT LIKE 'W%'
# Badge shows total win count, no tiers
_event_wins = {r['username']: r['wins'] for r in conn.execute(
    "SELECT username, COUNT(*) as wins FROM event_rewards "
    "WHERE event_id NOT LIKE 'W%' GROUP BY username"
).fetchall()}

# ===== BEST WEEK DATA =====
print("🏆 Building best week data...")

def fetch_best_week(col, limit=10):
    return [dict(r) for r in conn.execute(f"""
        SELECT ws.username, wa.sp_rank, CAST(ws.{col} AS INTEGER) as val, ws.week
        FROM weekly_snapshots ws
        LEFT JOIN weekly_analysis wa
            ON wa.week = ws.week AND wa.username = ws.username
        WHERE ws.{col} IS NOT NULL AND ws.{col} != '' AND ws.{col} != '-'
          AND CAST(ws.{col} AS INTEGER) > 0
        ORDER BY CAST(ws.{col} AS INTEGER) DESC
        LIMIT {limit}
    """).fetchall()]

best_week_ts  = fetch_best_week("weekly_ts")
best_week_tpk = fetch_best_week("weekly_tpk")
best_week_tl  = fetch_best_week("weekly_loots")
print(f"  ✅ Best week: {len(best_week_ts)} TS · {len(best_week_tpk)} TPK · {len(best_week_tl)} TL records")

# ===== GENERATE STORIES =====
print("📖 Generating stories...")

# Compute clan-wide all-time bests for ranking PBs against current clan records
clan_all_bests_ts  = {r['username']: safe_int(r['best']) for r in conn.execute(
    "SELECT username, MAX(weekly_ts) as best FROM weekly_snapshots GROUP BY username").fetchall()}
clan_all_bests_tpk = {r['username']: safe_int(r['best']) for r in conn.execute(
    "SELECT username, MAX(weekly_tpk) as best FROM weekly_snapshots GROUP BY username").fetchall()}
clan_all_bests_tl  = {r['username']: safe_int(r['best']) for r in conn.execute(
    "SELECT username, MAX(weekly_loots) as best FROM weekly_snapshots GROUP BY username").fetchall()}

def clan_rank_for(player_val, all_bests_dict):
    """Rank this player's value among all clan members' all-time bests"""
    if player_val == 0:
        return None
    sorted_vals = sorted(all_bests_dict.values(), reverse=True)
    try:
        return sorted_vals.index(player_val) + 1
    except ValueError:
        return None

def generate_story(username, conn):
    history = conn.execute("""
        SELECT wa.*, ws.weekly_ts, ws.weekly_tpk, ws.weekly_loots,
               ws.weekly_ts_rank, ws.weekly_tpk_rank, ws.weekly_tl_rank
        FROM weekly_analysis wa
        JOIN weekly_snapshots ws ON wa.week = ws.week AND wa.username = ws.username
        WHERE wa.username = ?
        ORDER BY wa.week ASC
    """, (username,)).fetchall()

    if not history:
        return f"No story data available for {username}."

    lines = []
    for row in history:
        week_num   = row['week_number']
        week_label = row['week']
        sp         = round(safe_float(row['star_points']), 1)
        sp_change  = round(safe_float(row['sp_change']), 1)
        is_active  = row['is_active']
        streak     = safe_int(row['current_streak'])
        weekly_ts  = safe_int(row['weekly_ts'])
        weekly_tpk = safe_int(row['weekly_tpk'])
        weekly_loots = safe_int(row['weekly_loots'])
        ts_rank    = row['weekly_ts_rank'] or ''
        tpk_rank   = row['weekly_tpk_rank'] or ''
        tl_rank    = row['weekly_tl_rank'] or ''
        ts_clan_rank  = safe_int(row['ts_clan_rank'])
        tpk_clan_rank = safe_int(row['tpk_clan_rank'])
        tl_clan_rank  = safe_int(row['tl_clan_rank'])
        ts_pb      = row['ts_pb']
        tpk_pb     = row['tpk_pb']
        tl_pb      = row['tl_pb']
        is_promoted = row['is_promoted']
        sp_rank    = row['sp_rank'] or ''
        sp_events  = safe_float(row['sp_events'])

        change_str = f"+{sp_change}" if sp_change > 0 else str(sp_change)
        lines.append(f"\n📅 ━━ Week {week_num} ({week_label}) ━━ {change_str} SP → {sp} SP")

        # Activity narrative
        if is_active == '✓':
            if streak == 1:
                lines.append("→ Began their journey. 🏁 Active this week")
            elif streak == 2:
                lines.append("→ Making progress. 🔄 Gaining momentum - 2 weeks active!")
            elif streak == 3:
                lines.append("→ Steady climb. 🔥 Building heat - 3 weeks active!")
            elif streak == 4:
                lines.append("→ Steady climb. 🔥 🔥 On fire! 4 weeks!")
            elif streak == 5:
                lines.append("→ MAXIMUM MOMENTUM!. 🔥 🔥 🔥 Unstoppable!!! 5 weeks active!!!!")
            else:
                lines.append(f"→ MAXIMUM MOMENTUM!. 🔥 🔥 🔥 Unstoppable!!! {streak} weeks active!!!!")
        else:
            lines.append("→ Inactive this week. 💤")

        # Promotion
        if is_promoted and sp_rank:
            lines.append(f"🎖️ is promoted to {sp_rank}!")

        # Personal bests — only show if this week IS their current all-time best
        player_best_ts  = clan_all_bests_ts.get(username, 0)
        player_best_tpk = clan_all_bests_tpk.get(username, 0)
        player_best_tl  = clan_all_bests_tl.get(username, 0)
        if ts_pb and weekly_ts == player_best_ts:
            rank = clan_rank_for(weekly_ts, clan_all_bests_ts)
            lines.append(f"→ Woohoo! Hit personal best TS of {weekly_ts:,}! That's #{rank} in the clan 🏅")
        if tpk_pb and weekly_tpk == player_best_tpk:
            rank = clan_rank_for(weekly_tpk, clan_all_bests_tpk)
            lines.append(f"→ Woohoo! Hit personal best TPK of {weekly_tpk:,}! That's #{rank} in the clan 🏅")
        if tl_pb and weekly_loots == player_best_tl:
            rank = clan_rank_for(weekly_loots, clan_all_bests_tl)
            lines.append(f"→ Woohoo! Hit personal best TL of {weekly_loots:,}! That's #{rank} in the clan 🏅")

        # Global leaderboard
        if ts_rank:
            lines.append(f"→ DAAAMNNN!!!! Hit {ts_rank} on global TS leaderboard! 🏆! Earned {rank_str_to_sp(ts_rank)} SP from competition!")
        if tpk_rank:
            lines.append(f"→ DAAAMNNN!!!! Hit {tpk_rank} on global TPK leaderboard! 🏆! Earned {rank_str_to_sp(tpk_rank)} SP from competition!")
        if tl_rank:
            lines.append(f"→ DAAAMNNN!!!! Hit {tl_rank} on global TL leaderboard! 🏆! Earned {rank_str_to_sp(tl_rank)} SP from competition!")

        # Event SP
        if sp_events > 0:
            lines.append(f"→ Earned {sp_events} SP from clan events! 🎉")

        # Medals earned this week
        # TS / TPK / TL — check if this week's value crosses any threshold
        _COL_MAP = {'ts': ('weekly_ts', weekly_ts), 'tpk': ('weekly_tpk', weekly_tpk), 'tl': ('weekly_loots', weekly_loots)}
        _TIER_EMOJI = {'Bronze': '🟫', 'Silver': '⬜', 'Gold': '🟨', 'Platinum': '💎'}
        for cat, (_, week_val) in _COL_MAP.items():
            if cat not in _medal_thresholds or week_val == 0:
                continue
            for tier, thresh, _cash in _medal_thresholds[cat]:
                if week_val >= thresh:
                    icon   = _medal_icons.get(cat, '🏅')
                    dname  = _medal_display_names.get(cat, cat.upper())
                    temoji = _TIER_EMOJI.get(tier, '🏅')
                    lines.append(f"→ {temoji} Earned {tier} {icon} {dname} medal! ({week_val:,} this week)")

        # Streak medal — check if best_streak this week qualifies
        if 'streak' in _medal_thresholds:
            best_streak_this_week = safe_int(row['best_streak']) if row['best_streak'] is not None else 0
            for tier, thresh, _cash in _medal_thresholds['streak']:
                if best_streak_this_week >= thresh:
                    temoji = _TIER_EMOJI.get(tier, '🏅')
                    lines.append(f"→ {temoji} Earned {tier} 🔥 Streak medal! (best streak: {best_streak_this_week} weeks)")

        # Global medal — check if any rank column this week qualifies
        if 'global' in _medal_thresholds:
            week_ranks = []
            for rc in (ts_rank, tpk_rank, tl_rank):
                if rc:
                    try:
                        week_ranks.append(int(str(rc).replace('#', '').strip()))
                    except:
                        pass
            if week_ranks:
                best_rank_this_week = min(week_ranks)
                for tier, thresh, _cash in _medal_thresholds['global']:
                    if best_rank_this_week <= thresh:
                        temoji = _TIER_EMOJI.get(tier, '🏅')
                        lines.append(f"→ {temoji} Earned {tier} 🌍 Global medal! (reached #{best_rank_this_week} globally)")

    return "\n".join(lines)

all_player_stories = {}
for i, username in enumerate(player_list, 1):
    print(f"   Generating story {i}/{len(player_list)}: {username}...", end='\r')
    all_player_stories[username] = enhance_story(generate_story(username, conn))
print(f"\n  ✅ Stories generated for {len(all_player_stories)} players")

# Build set of veterans (more than 1 week) to exclude new members from Top 3
veteran_usernames = set()
for username in player_list:
    count = conn.execute(
        "SELECT COUNT(*) FROM weekly_analysis WHERE username = ?", (username,)
    ).fetchone()[0]
    if count > 1:
        veteran_usernames.add(username)
print(f"  👥 {len(veteran_usernames)} veteran players identified")

# ===== EVENTS DATA =====
print("🎉 Building events data...")
events_raw = conn.execute("SELECT * FROM events ORDER BY date DESC").fetchall()
event_rewards_raw = conn.execute("SELECT * FROM event_rewards ORDER BY sp_awarded DESC").fetchall()

from collections import defaultdict as _ddict
rewards_by_event = _ddict(list)
for r in event_rewards_raw:
    rewards_by_event[r['event_id']].append(dict(r))

events_data = []
for e in events_raw:
    events_data.append({
        'event_id':    e['event_id'],
        'event_name':  e['event_name'],
        'week':        e['week'],
        'date':        e['date'],
        'description': e['description'],
        'type':        e['type'],
        'status':      e['status'],
        'image1':      e['image1'] if e['image1'] else '',
        'rewards':     rewards_by_event.get(e['event_id'], [])
    })

# Cumulative event totals for summary bar
total_ev_count   = len(events_data)
total_ev_sp      = round(sum(float(r['sp_awarded']    or 0) for r in event_rewards_raw), 1)
total_ev_cash    = int(sum(float(r['cash_award']      or 0) for r in event_rewards_raw))
total_ev_credits = int(sum(float(r['credit_award']    or 0) for r in event_rewards_raw))

conn.close()

def _best_tier_and_count(username, snap_col, thresholds):
    """
    TS / TPK / TL detection:
    - Finds the HIGHEST tier whose threshold the player crossed in ANY week
    - thresholds: [(tier, threshold, cash_reward), ...] sorted Bronze→Platinum
    """
    snaps = _snaps_by_user.get(username, [])
    for tier, thresh, _cash in reversed(thresholds):  # check highest tier first
        if any(safe_int(r[snap_col]) >= thresh for r in snaps):
            return tier, 0  # count computed per-tier at display time
    return None, 0

def _count_for_specific_tier(username, snap_col, tier, thresholds):
    """Count how many weeks a player crossed a specific tier's threshold."""
    snaps = _snaps_by_user.get(username, [])
    for t, thresh, _cash in thresholds:
        if t == tier:
            return sum(1 for r in snaps if safe_int(r[snap_col]) >= thresh)
    return 0

def _count_for_tier(username, snap_col, threshold, thresholds_list=None):
    """Count how many weeks a player crossed a specific threshold."""
    snaps = _snaps_by_user.get(username, [])
    return sum(1 for r in snaps if safe_int(r[snap_col]) >= threshold)

def _best_tier_simple(value, thresholds, lower_is_better=False):
    """
    Streak / Global detection:
    - Returns the highest tier where value qualifies
    - lower_is_better=True for global rank (rank 1 is best)
    - thresholds: [(tier, threshold, cash_reward), ...] sorted Bronze→Platinum
    """
    earned = None
    for tier, thresh, _cash in thresholds:
        if lower_is_better:
            if value is not None and value <= thresh:
                earned = tier
        else:
            if value is not None and value >= thresh:
                earned = tier
    return earned

def compute_medals(username):
    result = {}

    # TS — any week weekly_ts >= threshold
    if 'ts' in _medal_thresholds:
        tier, count = _best_tier_and_count(username, 'weekly_ts', _medal_thresholds['ts'])
        result['ts_tier'] = tier
        result['ts_count'] = count

    # TPK — any week weekly_tpk >= threshold
    if 'tpk' in _medal_thresholds:
        tier, count = _best_tier_and_count(username, 'weekly_tpk', _medal_thresholds['tpk'])
        result['tpk_tier'] = tier
        result['tpk_count'] = count

    # TL — any week weekly_loots >= threshold
    if 'tl' in _medal_thresholds:
        tier, count = _best_tier_and_count(username, 'weekly_loots', _medal_thresholds['tl'])
        result['tl_tier'] = tier
        result['tl_count'] = count

    # Streak — best_streak ever >= threshold
    streak_val = _best_streaks.get(username, 0)
    result['streak_val'] = streak_val
    if 'streak' in _medal_thresholds:
        result['streak_tier'] = _best_tier_simple(streak_val, _medal_thresholds['streak'])

    # Global — count total times any rank column had a qualifying rank value
    # Each non-null entry in weekly_ts_rank / weekly_tpk_rank / weekly_tl_rank counts separately
    global_best = _best_global.get(username)
    result['global_best'] = global_best
    if 'global' in _medal_thresholds:
        result['global_tier'] = _best_tier_simple(global_best, _medal_thresholds['global'], lower_is_better=True)
        # Count total weeks where player had a qualifying global rank (at least Bronze threshold)
        bronze_threshold = _medal_thresholds['global'][0][1]  # lowest threshold = Bronze
        rank_rows = [r for r in _all_rank_rows if r['username'] == username]
        global_count = 0
        for r in rank_rows:
            row_qualifies = False
            for col in ('weekly_ts_rank', 'weekly_tpk_rank', 'weekly_tl_rank'):
                val = r[col]
                if val:
                    try:
                        n = int(str(val).replace('#', '').strip())
                        if n > 0 and n <= bronze_threshold:
                            row_qualifies = True
                            break
                    except:
                        pass
            if row_qualifies:
                global_count += 1
        result['global_count'] = global_count

    # Event wins — total count, no tiers
    result['event_wins'] = _event_wins.get(username, 0)

    return result

# Precompute for all players ever seen in weekly_snapshots
_all_usernames = list({r['username'] for r in _all_snaps})
medals_data = {u: compute_medals(u) for u in _all_usernames}
print(f"  ✅ Medals computed for {len(medals_data)} players")

# ===== QUICK STATS =====
total_players        = len(players)
perfect_streak_count = sum(1 for p in players if '🔥' in p['activity'] and 'Perfect' in p['activity'])
total_sp_gained      = round(sum(p['change'] for p in players), 1)
activity_rate        = int(carot_data['activity_rate'][-1]) if carot_data['activity_rate'] else 0

print(f"  📊 {total_players} players | ⭐ {activity_rate}% activity | 🔥 {perfect_streak_count} perfect | 💎 {total_sp_gained} SP gained")

# ===== HTML COMPONENTS =====
print("🌐 Generating HTML...")

# Events HTML (Timeline layout)
DEFAULT_EVENT_IMG = "https://via.placeholder.com/80x80/e74c3c/ffffff?text=EVENT"

def build_event_card(e, idx):
    status   = e['status']
    img_url  = e['image1'] if e['image1'] else DEFAULT_EVENT_IMG
    is_ongoing = status.lower() == 'ongoing'

    status_badge = (
        '<span class="ev-badge ev-badge-ongoing"><span class="ev-pulse"></span>Live Now</span>'
        if is_ongoing else
        '<span class="ev-badge ev-badge-completed">✅ Completed</span>'
    )
    type_badge = f'<span class="ev-badge ev-badge-type">{e["type"]}</span>'
    week_badge = f'<span class="ev-badge ev-badge-week">{e["week"]} · {e["date"]}</span>'

    # Winners table
    winners_html = ''
    if e['rewards']:
        rows = ''
        for r in e['rewards']:
            sp      = round(float(r.get('sp_awarded', 0) or 0), 1)
            cash    = int(float(r.get('cash_award', 0) or 0))
            credits = int(float(r.get('credit_award', 0) or 0))
            notes   = r.get('notes', '') or ''
            role    = r.get('role', '') or ''
            rows += f"""            <tr>
                <td><strong>{r['username']}</strong></td>
                <td><span class="ev-role-badge">{role}</span></td>
                <td class="ev-sp-val">⭐ {sp} SP</td>
                <td class="ev-cash-val">{f"💰 {cash:,}" if cash > 0 else "—"}</td>
                <td class="ev-credit-val">{f"💎 {credits:,}" if credits > 0 else "—"}</td>
                <td class="ev-notes-val">{notes}</td>
            </tr>\n"""
        winners_html = f"""        <div class="ev-winners-label">🏆 Results</div>
        <table class="ev-table">
            <thead><tr><th>Player</th><th>Role</th><th>SP</th><th>Cash</th><th>Credits</th><th>Notes</th></tr></thead>
            <tbody>
{rows}            </tbody>
        </table>"""
    else:
        winners_html = '        <p class="ev-no-results">Results will be posted when the event ends.</p>'

    return f"""    <div class="tl-item">
        <div class="tl-dot{'tl-dot-live' if is_ongoing else ''}"></div>
        <div class="tl-card" onclick="toggleTL('tl-exp-{idx}','tl-chev-{idx}')">
            <div class="tl-header">
                <img class="tl-img" src="{img_url}" alt="{e['event_name']}" onerror="this.src='{DEFAULT_EVENT_IMG}'">
                <div class="tl-info">
                    <div class="tl-title">{e['event_name']}</div>
                    <div class="tl-meta">{week_badge} {type_badge} {status_badge}</div>
                    <div class="tl-desc">{e['description']}</div>
                </div>
                <div class="tl-chevron" id="tl-chev-{idx}">▼</div>
            </div>
            <div class="tl-expand" id="tl-exp-{idx}">
                <div class="tl-full-desc">{e['description']}</div>
{winners_html}
            </div>
        </div>
    </div>\n"""

ongoing_events   = [e for e in events_data if e['status'].lower() == 'ongoing']
completed_events = [e for e in events_data if e['status'].lower() == 'completed']

ongoing_cards_html   = ''.join(build_event_card(e, f'on{i}') for i, e in enumerate(ongoing_events))
completed_cards_html = ''.join(build_event_card(e, f'co{i}') for i, e in enumerate(completed_events))

if not ongoing_cards_html:
    ongoing_cards_html = '    <p class="ev-empty">No ongoing events right now. Check back soon!</p>\n'
if not completed_cards_html:
    completed_cards_html = '    <p class="ev-empty">No completed events yet.</p>\n'

# ===== MEDAL BADGE HTML HELPERS =====
_TIER_CSS = {'Bronze':'mab-bronze','Silver':'mab-silver','Gold':'mab-gold','Platinum':'mab-platinum'}

def _medal_circle(icon, label, tier, count=None):
    tc = _TIER_CSS.get(tier, 'mab-bronze')
    extra = '<span class="msh msh2"></span><span class="msh msh3"></span>' if tc == 'mab-platinum' else ''
    tip = f'{label} — {tier}' + (f' · {count} time{"s" if count != 1 else ""}' if count and count >= 1 else '')
    count_label = f'<span class="mab-count">×{count}</span>' if count and count > 1 else ''
    return (f'<span class="mab-wrap" title="{tip}">'
            f'<span class="mab {tc}">'
            f'<span class="msh msh1"></span>{extra}'
            f'<span class="mi">{icon}</span><span class="ml">{label}</span>'
            f'</span>'
            f'{count_label}'
            f'</span>')

def _medal_event_pill(wins):
    return (f'<span class="mev" title="Event Winner — {wins} win{"s" if wins!=1 else ""}">'
            f'<span class="mev-sh"></span>'
            f'<span class="mev-icon">🏆</span>'
            f'<span class="mev-div"></span>'
            f'<span class="mev-num">{wins}</span></span>')

def build_medal_badges(username):
    m = medals_data.get(username, {})
    parts = []
    if m.get('ts_tier'):
        parts.append(_medal_circle('⚔️', 'TS',  m['ts_tier'],  m.get('ts_count')))
    if m.get('tpk_tier'):
        parts.append(_medal_circle('💀', 'TPK', m['tpk_tier'], m.get('tpk_count')))
    if m.get('tl_tier'):
        parts.append(_medal_circle('📦', 'TL',  m['tl_tier'],  m.get('tl_count')))
    if m.get('streak_tier'):
        parts.append(_medal_circle('🔥', 'STK', m['streak_tier']))
    if m.get('global_tier'):
        parts.append(_medal_circle('🌍', 'GL',  m['global_tier'], m.get('global_count')))
    if m.get('event_wins', 0) > 0:
        parts.append(_medal_event_pill(m['event_wins']))
    if not parts:
        return '<span class="moh-empty">—</span>'
    return '<div class="moh-wrap">' + ''.join(parts) + '</div>'

# Statboard rows
statboard_rows = ""
for p in players:
    rank_class   = f' class="rank-{p["rank"]}"' if p['rank'] <= 3 else ''
    badge_class  = get_badge_class(p['sp_rank'])
    change_color = "#27ae60" if p['change'] > 0 else ("#e74c3c" if p['change'] < 0 else "#7f8c8d")
    change_sign  = "+" if p['change'] > 0 else ""
    streak_display = f"🔥 {p['streak']}" if p['streak'] >= 4 else (f"⚡ {p['streak']}" if p['streak'] >= 2 else str(p['streak']))
    row_id = f"breakdown-{p['rank']}"
    moh_html = build_medal_badges(p['username'])
    statboard_rows += (
        f'''        <tr{rank_class} class="expandable-trigger" onclick="toggleBreakdown(\'{row_id}\', \'icon-{row_id}\')">\n'''
        f'''            <td><span class="expand-icon" id="icon-{row_id}">▶</span> {p['rank']}</td>\n'''
        f'''            <td><strong>{p['username']}</strong></td>\n'''
        f'''            <td class="moh-col">{moh_html}</td>\n'''
        f'''            <td>{p['level']}</td>\n'''
        f'''            <td><span class="badge {badge_class}">{p['sp_rank']}</span></td>\n'''
        f'''            <td>{p['sp']}</td>\n'''
        f'''            <td style="color: {change_color};">{change_sign}{p['change']}</td>\n'''
        f'''            <td>\n'''
        f'''                <div class="progress-wrap">\n'''
        f'''                    <span style="font-size:0.82em; color:#7f8c8d;">{p['progress_to_next']}</span>\n'''
        f'''                    <div class="progress-bar-bg"><div class="progress-bar-fill" style="width:{p['progress_pct']}%"></div></div>\n'''
        f'''                </div>\n'''
        f'''            </td>\n'''
        f'''            <td>{streak_display}</td>\n'''
        f'''            <td>{p['activity']}</td>\n'''
        f'''        </tr>\n'''
        f'''        <tr class="breakdown-row" id="{row_id}">\n'''
        f'''            <td colspan="10" style="padding:0;">\n'''
        f'''                <div class="breakdown-inner">\n'''
        f'''                    <div class="inline-panel">\n'''
        f'''                        <div>\n'''
        f'''                            <div class="panel-title">⭐ SP Breakdown</div>\n'''
        f'''                            <div class="sp-cards-grid">\n'''
        f'''                                <div class="sp-card clan"><div class="sc-label">🏰 Clan SP</div><div class="sc-value">{round(p['cum_sp_clan'],2)}</div></div>\n'''
        f'''                                <div class="sp-card alltime"><div class="sc-label">⏳ All Time SP</div><div class="sc-value">{round(p['sp_alltime'],2)}</div></div>\n'''
        f'''                                <div class="sp-card events"><div class="sc-label">🎉 Events SP</div><div class="sc-value">{round(p['cum_sp_events'],2)}</div></div>\n'''
        f'''                                <div class="sp-card weekly"><div class="sc-label">🏆 Weekly LB SP</div><div class="sc-value">{round(p['cum_sp_weekly'],2)}</div></div>\n'''
        f'''                            </div>\n'''
        f'''                        </div>\n'''
        f'''                        <div>\n'''
        f'''                            <div class="panel-title">📊 SP Composition</div>\n'''
        f'''                            <div class="sp-bar-panel">\n'''
        f'''                                <div class="bar-track">\n'''
        f'''                                    <div class="bar-seg s-clan"    style="width:{round(p['cum_sp_clan']  / max(p['cum_sp_clan'] + p['sp_alltime'] + p['cum_sp_events'] + p['cum_sp_weekly'], 0.001) * 100, 1)}%"></div>\n'''
        f'''                                    <div class="bar-seg s-alltime" style="width:{round(p['sp_alltime']   / max(p['cum_sp_clan'] + p['sp_alltime'] + p['cum_sp_events'] + p['cum_sp_weekly'], 0.001) * 100, 1)}%"></div>\n'''
        f'''                                    <div class="bar-seg s-events"  style="width:{round(p['cum_sp_events']/ max(p['cum_sp_clan'] + p['sp_alltime'] + p['cum_sp_events'] + p['cum_sp_weekly'], 0.001) * 100, 1)}%"></div>\n'''
        f'''                                    <div class="bar-seg s-weekly"  style="width:{round(p['cum_sp_weekly']/ max(p['cum_sp_clan'] + p['sp_alltime'] + p['cum_sp_events'] + p['cum_sp_weekly'], 0.001) * 100, 1)}%"></div>\n'''
        f'''                                </div>\n'''
        f'''                                <div class="sp-legend-panel">\n'''
        f'''                                    <div class="sleg-row"><span class="sleg-label"><span class="sleg-dot" style="background:#3498db"></span>Clan SP</span><span class="sleg-val">{round(p['cum_sp_clan'],2)}</span></div>\n'''
        f'''                                    <div class="sleg-row"><span class="sleg-label"><span class="sleg-dot" style="background:#2ecc71"></span>All Time SP</span><span class="sleg-val">{round(p['sp_alltime'],2)}</span></div>\n'''
        f'''                                    <div class="sleg-row"><span class="sleg-label"><span class="sleg-dot" style="background:#f39c12"></span>Events SP</span><span class="sleg-val">{round(p['cum_sp_events'],2)}</span></div>\n'''
        f'''                                    <div class="sleg-row"><span class="sleg-label"><span class="sleg-dot" style="background:#9b59b6"></span>Weekly LB SP</span><span class="sleg-val">{round(p['cum_sp_weekly'],2)}</span></div>\n'''
        f'''                                </div>\n'''
        f'''                            </div>\n'''
        f'''                        </div>\n'''
        f'''                    </div>\n'''
        f'''                </div>\n'''
        f'''            </td>\n'''
        f'''        </tr>\n'''
    )

# Activity rows
activity_sorted = sorted(activity_data, key=lambda x: x['current_streak'], reverse=True)
# Build week header cells
week_th_html = "".join(f'<th class="hm-col-week">{w}</th>\n' for w in all_weeks)

# Build heatmap rows
activity_rows = ""
for a in activity_sorted:
    cs = a['current_streak']
    bs = a['best_streak']

    def streak_pill(val):
        if val >= 4:   return f'<span class="hm-pill hm-pill-hot">🔥 {val}w</span>'
        elif val >= 2: return f'<span class="hm-pill hm-pill-warm">⚡ {val}w</span>'
        elif val > 0:  return f'<span class="hm-pill hm-pill-cold">{val}w</span>'
        else:          return f'<span class="hm-pill hm-pill-cold">💤 0</span>'

    cells = ""
    uname = a['username']
    for (wk, act) in a['week_cells']:
        if act == '✓':
            cells += f'<td class="hm-col-week"><div class="hm-cell hm-active" title="{uname} — {wk}: Active">✓</div></td>\n'
        elif act == '✗':
            cells += f'<td class="hm-col-week"><div class="hm-cell hm-inactive" title="{uname} — {wk}: Missed">✗</div></td>\n'
        else:
            cells += f'<td class="hm-col-week"><div class="hm-cell hm-absent" title="{uname} — {wk}: Not in clan">—</div></td>\n'

    activity_rows += f'''        <tr>
            <td class="hm-col-name">{a['username']}</td>
            {cells}
            <td class="hm-col-cur">{streak_pill(cs)}</td>
            <td class="hm-col-best">{streak_pill(bs)}</td>
            <td class="hm-col-stat" style="font-size:0.82rem;color:var(--text-muted)">{a['activity_status']}</td>
        </tr>\n'''

# Top 3
medals     = ["🥇", "🥈", "🥉"]
tp_classes = ["tp-gold", "tp-silver", "tp-bronze"]
top_3    = sorted([p for p in players if not p['day_joined']], key=lambda x: x['change'], reverse=True)[:3]
top_3_html = ""
for i, p in enumerate(top_3):
    top_3_html += f'''                    <li class="rank-{i+1} {tp_classes[i]}">
                        <div><span class="medal">{medals[i]}</span> <strong>{p['username']}</strong></div>
                        <div><strong>{'+' if p['change'] > 0 else ''}{p['change']} SP</strong> → {p['sp']} SP Total</div>
                    </li>\n'''

# Streak leaders
streak_leaders = sorted([p for p in players if p['streak'] >= 2], key=lambda x: x['streak'], reverse=True)[:5]
streak_html = ""
for p in streak_leaders:
    streak_html += f'''                    <li><strong>{p['username']}:</strong> <span class="streak">{p['streak']} weeks {"🔥" if p['streak'] >= 4 else "⚡"}</span></li>\n'''
if not streak_html:
    streak_html = '                    <li>No active streaks this week</li>\n'

# Dropdowns
player_dropdown_sp    = "".join(f'                    <option value="{p}">{p}</option>\n' for p in player_list)
player_dropdown_story = "".join(f'                    <option value="{p}">{p}</option>\n' for p in player_list)
player_dropdown_sim   = "".join(f'                        <option value="{p}">{p}</option>\n' for p in player_list)

# Simulator data for all players
simulator_data = {}
for p in players:
    simulator_data[p['username']] = {
        'weekly_ts':             p['weekly_ts'],
        'weekly_tpk':            p['weekly_tpk'],
        'weekly_tl':             p['weekly_loots'],
        'level':                 p['level'],
        'level_sp':              p['level_sp'],
        'alltime_ts':            p['alltime_ts'],
        'alltime_tpk':           p['alltime_tpk'],
        'alltime_loots':         p['alltime_loots'],
        'ats_base':              p['alltime_ts_base'],
        'atpk_base':             p['alltime_tpk_base'],
        'atl_base':              p['alltime_tl_base'],
        'sp_alltime':            p['sp_alltime'],
        'cum_sp_clan':           p['cum_sp_clan'],
        'cum_sp_events':         p['cum_sp_events'],
        'cum_sp_weekly':         p['cum_sp_weekly'],
        'sp_carryover':          p['sp_carryover'],
        'current_week_clan_sp':  p['sp_clan'],
        'star_points':           p['sp'],
        'ts_rank':               p['ts_rank'],
        'tpk_rank':              p['tpk_rank'],
        'tl_rank':               p['tl_rank'],
    }

chart_data = {
    'all_players_sp': all_player_sp_data,
    'carot':          carot_data,
    'spdr':           spdr_data,
    'csbs':           csbs_data,
}

# ===== WRITE HTML =====
print("📝 Writing HTML file...")

# Load chart.js inline to avoid external request causing browser spinner
import os as _os
_chart_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'chart.min.js')
if _os.path.exists(_chart_path):
    with open(_chart_path, 'r', encoding='utf-8') as _f:
        chart_js_inline = _f.read()
    print("  ✅ chart.min.js inlined")
else:
    chart_js_inline = 'document.write(\'<script src=\"https://cdn.jsdelivr.net/npm/chart.js\"><\\/script>\');'
    print("  ⚠️  chart.min.js not found, falling back to CDN")

# ===== MEDALS OF HONOR PAGE =====
_TIER_COLOR = {'Bronze':'#cd7f32','Silver':'#b0b8c8','Gold':'#ffd700','Platinum':'#ffffff'}
_TIER_CSS_COL = {'Bronze':'tc-br','Silver':'tc-si','Gold':'tc-go','Platinum':'tc-pl'}

_CAT_LABEL = {
    'ts':     ('⚔️', 'Top Survivor'),
    'tpk':    ('💀', 'Total Player Kills'),
    'tl':     ('📦', 'Total Loots'),
    'streak': ('🔥', 'Streak'),
    'global': ('🌍', 'Global Leaderboard'),
}
_CAT_SHORT = {'ts':'TS','tpk':'TPK','tl':'TL','streak':'STK','global':'GL'}
_TIER_ORDER = ['Bronze','Silver','Gold','Platinum']
_TIER_RANK  = {t: i for i, t in enumerate(_TIER_ORDER)}

def _fmt_cash(val):
    if val >= 1_000_000: return f'{val // 1_000_000}M'
    if val >= 1_000:     return f'{val // 1_000}K'
    return str(val)

def _fmt_thresh(n):
    if n >= 1_000_000_000: return f'{n // 1_000_000_000}B'
    if n >= 1_000_000:     return f'{n // 1_000_000}M'
    if n >= 1_000:         return f'{n // 1_000}K'
    return str(n)

medals_page_html = ""
_cat_order = [c for c in ['ts','tpk','tl','streak','global'] if c in _medal_thresholds]

for cat in _cat_order:
    icon, full_name = _CAT_LABEL.get(cat, ('🏅', cat.upper()))
    short = _CAT_SHORT.get(cat, cat.upper())
    thresholds_for_cat = _medal_thresholds[cat]

    medals_page_html += f'''        <div class="moh-cat-block">
            <div class="moh-cat-header">
                <span class="moh-cat-icon">{icon}</span>
                <span class="moh-cat-name">{full_name}</span>
                <span class="moh-cat-abbr">{short}</span>
            </div>
            <div class="moh-tier-row">\n'''

    for tier in _TIER_ORDER:
        tier_entry = next(((t, th, cash) for t, th, cash in thresholds_for_cat if t == tier), None)
        if tier_entry is None:
            continue
        _, tier_thresh, tier_cash = tier_entry
        tc      = _TIER_CSS.get(tier, 'mab-bronze')
        col_cls = _TIER_CSS_COL.get(tier, 'tc-br')
        is_plat = tc == 'mab-platinum'
        extra_shines = '<span class="msh msh2"></span><span class="msh msh3"></span>' if is_plat else ''

        if cat == 'ts':
            thresh_str = f'{_fmt_thresh(tier_thresh)} Clan Weekly TS'
        elif cat == 'tpk':
            thresh_str = f'{_fmt_thresh(tier_thresh)} Weekly TPK'
        elif cat == 'tl':
            thresh_str = f'{_fmt_thresh(tier_thresh)} Clan Weekly Loots'
        elif cat == 'streak':
            thresh_str = f'{tier_thresh} Week Streak'
        elif cat == 'global':
            thresh_str = f'Top {tier_thresh} Global'
        else:
            thresh_str = _fmt_thresh(tier_thresh)

        cash_str = f'💰 {_fmt_cash(tier_cash)} <span>(one-time)</span>' if tier_cash > 0 else ''

        # Earners: anyone whose highest earned tier >= this tier
        this_rank = _TIER_RANK.get(tier, 0)
        earners = []
        for u, m in medals_data.items():
            earned_tier = None
            val = None
            if cat == 'ts':
                earned_tier = m.get('ts_tier')
                if earned_tier and _TIER_RANK.get(earned_tier, -1) >= this_rank:
                    val = _count_for_specific_tier(u, 'weekly_ts', tier, _medal_thresholds['ts'])
            elif cat == 'tpk':
                earned_tier = m.get('tpk_tier')
                if earned_tier and _TIER_RANK.get(earned_tier, -1) >= this_rank:
                    val = _count_for_specific_tier(u, 'weekly_tpk', tier, _medal_thresholds['tpk'])
            elif cat == 'tl':
                earned_tier = m.get('tl_tier')
                if earned_tier and _TIER_RANK.get(earned_tier, -1) >= this_rank:
                    val = _count_for_specific_tier(u, 'weekly_loots', tier, _medal_thresholds['tl'])
            elif cat == 'streak':
                earned_tier, val = m.get('streak_tier'), m.get('streak_val', 0)
            elif cat == 'global':
                earned_tier, val = m.get('global_tier'), m.get('global_count', 0)
            if earned_tier and _TIER_RANK.get(earned_tier, -1) >= this_rank:
                earners.append((u, val))
        earners.sort(key=lambda x: (-(x[1] or 0), x[0].lower()))

        earners_html = ''
        if earners:
            for uname, val in earners:
                if cat in ('ts','tpk','tl') and val and val >= 1:
                    cnt_tag = f'<span class="moh-earner-count">×{val}</span>'
                elif cat == 'streak' and val:
                    cnt_tag = f'<span class="moh-earner-count">{val}w</span>'
                elif cat == 'global' and val:
                    cnt_tag = f'<span class="moh-earner-count">×{val}</span>'
                else:
                    cnt_tag = ''
                earners_html += f'<div class="moh-earner"><span class="moh-earner-name">{uname}</span>{cnt_tag}</div>'
        else:
            earners_html = '<div class="moh-earner-none">Not yet earned</div>'

        medals_page_html += f'''                <div class="moh-tier-col {col_cls}">
                    <span class="mab {tc}">
                        <span class="msh msh1"></span>{extra_shines}
                        <span class="mi">{icon}</span>
                        <span class="ml">{short}</span>
                    </span>
                    <div class="moh-tier-name {col_cls}">{tier}</div>
                    <div class="moh-tier-thresh">{thresh_str}</div>
                    <div class="moh-tier-cash">{cash_str}</div>
                    <div class="moh-divider"></div>
                    <div class="moh-earners">{earners_html}</div>
                </div>\n'''

    medals_page_html += '            </div>\n        </div>\n'

# Event winners section
ev_earners = sorted(
    [(u, m['event_wins']) for u, m in medals_data.items() if m.get('event_wins', 0) > 0],
    key=lambda x: (-x[1], x[0].lower())
)
medals_page_html += '''        <div class="moh-cat-block">
            <div class="moh-cat-header">
                <span class="moh-cat-icon">🏆</span>
                <span class="moh-cat-name">Event Winners</span>
                <span class="moh-cat-abbr">EV</span>
            </div>
            <div class="moh-ev-grid">\n'''

if ev_earners:
    for uname, wins in ev_earners:
        medals_page_html += f'''                <div class="moh-ev-card">
                    <span class="mev" title="{uname} — {wins} event win{'s' if wins!=1 else ''}">
                        <span class="mev-sh"></span>
                        <span class="mev-icon">🏆</span>
                        <span class="mev-div"></span>
                        <span class="mev-num">{wins}</span>
                    </span>
                    <span class="moh-ev-name">{uname}</span>
                </div>\n'''
else:
    medals_page_html += '                <div class="moh-earner-none">No event wins yet</div>\n'

medals_page_html += '            </div>\n        </div>\n'

# ===== BEST WEEK HTML =====
def build_best_week_rows(rows):
    STRIPE = ['bw-stripe-1', 'bw-stripe-2', 'bw-stripe-3']
    POS_CLS = ['bw-pos-1', 'bw-pos-2', 'bw-pos-3']
    html = ''
    for i, r in enumerate(rows):
        sc  = STRIPE[i] if i < 3 else 'bw-stripe-n'
        pc  = POS_CLS[i] if i < 3 else 'bw-pos-n'
        bc  = get_badge_class(r.get('sp_rank') or 'Scout')
        val = r.get('val', 0)
        if val >= 1_000_000_000: val_str = f"{val/1_000_000_000:.2f}B"
        elif val >= 1_000_000:   val_str = f"{val/1_000_000:.1f}M"
        elif val >= 1_000:       val_str = f"{val/1_000:.1f}K"
        else:                    val_str = str(int(val))
        html += f'''                <tr>
                    <td>
                        <div class="bw-pos-cell">
                            <div class="bw-stripe {sc}"></div>
                            <span class="bw-pos {pc}">{i+1}</span>
                        </div>
                    </td>
                    <td>
                        <div class="bw-name">{r['username']}</div>
                        <span class="badge {bc}">{r.get('sp_rank') or 'Scout'}</span>
                    </td>
                    <td class="bw-val-cell">
                        <span class="bw-week-tag">{r.get('week','')}</span>
                        <span class="bw-val">{val_str}</span>
                    </td>
                </tr>\n'''
    return html

bw_rows_ts  = build_best_week_rows(best_week_ts)
bw_rows_tpk = build_best_week_rows(best_week_tpk)
bw_rows_tl  = build_best_week_rows(best_week_tl)

html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A P E X Clan Stats - {current_week}</title>
    <link href="https://fonts.googleapis.com/css2?family=Black+Ops+One&family=Rajdhani:wght@400;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        :root {{
            --blood:      #c0392b;
            --blood-bright: #e74c3c;
            --bg-base:    rgba(10,10,10,0.55);
            --bg-card:    rgba(20,20,20,0.75);
            --bg-deep:    rgba(13,17,23,0.80);
            --bg-hover:   rgba(33,38,45,0.85);
            --border:     #30363d;
            --border2:    #21262d;
            --text:       #d4c9b8;
            --text-muted: #8b949e;
            --muted:      #6b6055;
            --panel:      rgba(20,20,20,0.75);
        }}
        body.light-mode {{
            --bg-base:    #ffffff;
            --bg-card:    #f0f0f0;
            --bg-deep:    #f8f9fa;
            --bg-hover:   #ecf0f1;
            --border:     #dfe6e9;
            --border2:    #ecf0f1;
            --text:       #1a1a1a;
            --text-muted: #7f8c8d;
            --muted:      #999;
            --panel:      #f0f0f0;
        }}
        body {{ font-family: 'Rajdhani', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: var(--bg-base); background-image: url('background.png'); background-size: 100% auto; background-position: top center; background-attachment: scroll; background-repeat: no-repeat; color: var(--text); line-height: 1.6; transition: background 0.3s, color 0.3s; }}

        /* ── SCANLINES ── */
        body::before {{
            content: '';
            position: fixed;
            inset: 0;
            background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.04) 2px, rgba(0,0,0,0.04) 4px);
            pointer-events: none;
            z-index: 1000;
        }}
        /* ── HEADER ── */
        .site-header {{ position: relative; overflow: hidden; }}
        .site-header::before {{
            content: '';
            position: absolute; inset: 0;
            background-image:
                linear-gradient(rgba(192,57,43,0.04) 1px, transparent 1px),
                linear-gradient(90deg, rgba(192,57,43,0.04) 1px, transparent 1px);
            background-size: 40px 40px;
            animation: gridPulse 4s ease-in-out infinite alternate;
        }}
        .site-header::after {{
            content: '';
            position: absolute;
            top: 40%; left: 50%;
            transform: translate(-50%, -50%);
            width: 700px; height: 220px;
            background: radial-gradient(ellipse, rgba(192,57,43,0.09) 0%, transparent 70%);
            pointer-events: none;
        }}
        @keyframes gridPulse {{ from {{ opacity: 0.5; }} to {{ opacity: 1; }} }}
        .danger-stripe {{
            height: 7px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }}
        .danger-stripe::before,
        .danger-stripe::after {{
            content: '';
            height: 1px;
            background: linear-gradient(90deg, transparent 0%, rgba(192,57,43,0.5) 10%, var(--blood) 30%, var(--blood) 70%, rgba(192,57,43,0.5) 90%, transparent 100%);
        }}
        .hero {{
            position: relative; z-index: 1;
            text-align: center;
            padding: 48px 24px 36px;
        }}
        .hero-badge {{
            display: inline-flex; align-items: center; gap: 10px;
            background: rgba(192,57,43,0.08);
            border: 1px solid rgba(192,57,43,0.3);
            border-radius: 3px;
            padding: 4px 14px; margin-bottom: 20px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 11px; letter-spacing: 3px;
            color: var(--blood-bright); text-transform: uppercase;
            animation: badgeFade 3s ease-in-out infinite alternate;
        }}
        .hero-badge::before, .hero-badge::after {{ content: '//'; opacity: 0.5; }}
        @keyframes badgeFade {{
            from {{ border-color: rgba(192,57,43,0.2); box-shadow: none; }}
            to   {{ border-color: rgba(192,57,43,0.6); box-shadow: 0 0 12px rgba(192,57,43,0.2); }}
        }}
        .title-deco {{ display: flex; align-items: center; justify-content: center; gap: 20px; margin-bottom: 8px; }}
        .title-deco-line {{ flex: 1; max-width: 120px; height: 1px; background: linear-gradient(90deg, transparent, var(--blood), transparent); }}
        .clan-title {{
            font-family: 'Black Ops One', cursive;
            font-size: clamp(42px, 8vw, 88px);
            letter-spacing: 0.12em; line-height: 1;
            color: var(--text);
            text-shadow: 0 0 20px rgba(192,57,43,0.7), 0 0 60px rgba(192,57,43,0.3), 0 2px 0 rgba(0,0,0,0.6);
            animation: titleFlicker 8s ease-in-out infinite;
        }}
        .clan-title span {{ color: var(--blood-bright); text-shadow: 0 0 20px rgba(231,76,60,1), 0 0 50px rgba(231,76,60,0.5); }}
        @keyframes titleFlicker {{
            0%, 95%, 100% {{ opacity: 1; }}
            96% {{ opacity: 0.9; }} 97% {{ opacity: 1; }} 98% {{ opacity: 0.94; }}
        }}
        .hero-sub {{
            margin-top: 16px; display: flex; align-items: center; justify-content: center;
            font-family: 'Share Tech Mono', monospace;
            font-size: 12px; letter-spacing: 2px; color: var(--muted);
        }}
        .hero-sub .sep {{ width: 4px; height: 4px; background: var(--blood); margin: 0 12px; transform: rotate(45deg); }}
        .hero-sub .highlight {{ color: var(--text); }}
        .live-dot {{
            display: inline-flex; align-items: center; gap: 6px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 11px; letter-spacing: 2px; color: #4caf50; margin-top: 8px;
        }}
        .live-dot::before {{
            content: ''; width: 7px; height: 7px;
            background: #4caf50; border-radius: 50%;
            box-shadow: 0 0 8px #4caf50;
            animation: livePulse 1.5s ease-in-out infinite;
        }}
        @keyframes livePulse {{ 0%, 100% {{ transform: scale(1); opacity: 1; }} 50% {{ transform: scale(1.4); opacity: 0.7; }} }}
        /* ── NAV ── */
        .nav {{
            position: relative; z-index: 1;
            border-top: 1px solid rgba(192,57,43,0.25);
            border-bottom: 1px solid rgba(192,57,43,0.25);
            background: rgba(0,0,0,0.5);
            backdrop-filter: blur(4px);
        }}
        body.light-mode .nav {{
            background: rgba(255,255,255,0.8);
            border-top-color: rgba(192,57,43,0.2);
            border-bottom-color: rgba(192,57,43,0.2);
        }}
        .nav-inner {{ display: flex; justify-content: center; align-items: stretch; max-width: 1100px; margin: 0 auto; flex-wrap: wrap; }}
        .nav button {{
            position: relative; display: flex; align-items: center; gap: 7px;
            padding: 14px 20px;
            font-family: 'Rajdhani', sans-serif; font-weight: 700;
            font-size: 13px; letter-spacing: 1.5px; text-transform: uppercase;
            color: var(--muted); background: none; border: none;
            cursor: pointer; transition: color 0.2s; white-space: nowrap;
        }}
        .nav button:hover {{ color: var(--text); }}
        .nav button.active {{ color: var(--text); }}
        .nav button.active::after {{
            content: ''; position: absolute;
            bottom: 0; left: 0; right: 0; height: 2px;
            background: var(--blood-bright);
            box-shadow: 0 0 8px var(--blood-bright);
        }}
        .nav button.active::before {{
            content: ''; position: absolute;
            top: 6px; left: 6px; width: 8px; height: 8px;
            border-top: 1px solid var(--blood);
            border-left: 1px solid var(--blood);
        }}
        .container {{ max-width: 1400px; margin: 2rem auto; padding: 0 2rem; }}
        .page {{ display: none; animation: fadeIn 0.3s; }}
        .page.active {{ display: block; }}
        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }}
        /* ── STAT CARDS ── */
        .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 2px; margin-bottom: 2rem; }}
        .stat-card {{
            position: relative;
            background: var(--panel);
            border: 1px solid rgba(255,255,255,0.04);
            padding: 28px 24px;
            overflow: hidden;
            animation: cardReveal 0.6s ease both;
            transition: background 0.2s, border-color 0.2s;
            text-align: left;
        }}
        .stat-card:nth-child(1) {{ animation-delay: 0.1s; }}
        .stat-card:nth-child(2) {{ animation-delay: 0.2s; }}
        .stat-card:nth-child(3) {{ animation-delay: 0.3s; }}
        .stat-card:nth-child(4) {{ animation-delay: 0.4s; }}
        @keyframes cardReveal {{ from {{ opacity: 0; transform: translateY(12px); }} to {{ opacity: 1; transform: translateY(0); }} }}
        .stat-card::before {{
            content: ''; position: absolute;
            top: 0; left: 0; right: 0; height: 2px;
            background: linear-gradient(90deg, var(--blood), transparent);
        }}
        .stat-card::after {{
            content: ''; position: absolute;
            bottom: 8px; right: 8px; width: 12px; height: 12px;
            border-bottom: 1px solid rgba(192,57,43,0.3);
            border-right: 1px solid rgba(192,57,43,0.3);
        }}
        .stat-card:hover {{ border-color: rgba(192,57,43,0.2); }}
        .stat-card h3,
        .stat-card .stat-label {{
            font-family: 'Share Tech Mono', monospace;
            font-size: 10px; letter-spacing: 2.5px; text-transform: uppercase;
            color: var(--muted); margin-bottom: 14px;
            display: flex; align-items: center; gap: 8px;
            font-weight: normal;
        }}
        .stat-card h3::before,
        .stat-card .stat-label::before {{
            content: ''; display: inline-block;
            width: 14px; height: 1px; background: var(--blood); flex-shrink: 0;
        }}
        .stat-card .value,
        .stat-card .stat-value {{
            font-family: 'Black Ops One', cursive;
            font-size: clamp(28px, 4vw, 42px);
            color: var(--blood-bright);
            text-shadow: 0 0 20px rgba(231,76,60,0.5);
            line-height: 1; font-weight: normal;
        }}
        .stat-card .label,
        .stat-card .stat-sub {{
            margin-top: 8px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 10px; color: var(--muted); letter-spacing: 1px;
        }}
        .section {{
            position: relative;
            background: var(--panel);
            padding: 2rem; margin-bottom: 2rem;
            border: 1px solid rgba(255,255,255,0.04);
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            transition: background 0.3s;
            overflow: hidden;
        }}
        .section::before {{
            content: ''; position: absolute;
            top: 0; left: 0; right: 0; height: 2px;
            background: linear-gradient(90deg, var(--blood), transparent);
        }}
        .section::after {{
            content: ''; position: absolute;
            bottom: 8px; right: 8px; width: 14px; height: 14px;
            border-bottom: 1px solid rgba(192,57,43,0.25);
            border-right: 1px solid rgba(192,57,43,0.25);
        }}
        .section h2 {{
            font-family: 'Rajdhani', sans-serif;
            font-weight: 700; letter-spacing: 2px; text-transform: uppercase;
            color: var(--text); margin-bottom: 1.5rem; font-size: 1.4rem;
            display: flex; align-items: center; gap: 0.5rem;
            border-bottom: 1px solid rgba(192,57,43,0.15);
            padding-bottom: 0.8rem;
        }}
        table {{ width: 100%; border-collapse: collapse; background: var(--bg-deep); border-radius: 8px; overflow: hidden; }}
        th {{ background: var(--blood); color: white; padding: 1rem; text-align: left; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; font-family: 'Share Tech Mono', monospace; font-size: 0.78rem; cursor: pointer; user-select: none; transition: background 0.2s; }}
        th:hover {{ background: #c0392b; }}
        td {{ padding: 1rem; border-bottom: 1px solid var(--border2); color: var(--text); }}
        tr:hover td {{ background: var(--bg-hover); }}
        .rank-1 td {{ background: rgba(255,215,0,0.08); }}
        .rank-2 td {{ background: rgba(192,192,192,0.05); }}
        .rank-3 td {{ background: rgba(205,127,50,0.05); }}
        .rank-1:hover td, .rank-2:hover td, .rank-3:hover td {{ background: #21262d; }}
        .search-box {{ width: 100%; padding: 1rem; background: var(--bg-deep); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: 1rem; margin-bottom: 1rem; }}
        .search-box:focus {{ outline: none; border-color: #e74c3c; box-shadow: 0 0 10px rgba(231,76,60,0.15); }}
        select {{ padding: 1rem; background: var(--bg-deep); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: 1rem; cursor: pointer; width: 100%; max-width: 400px; margin-bottom: 1.5rem; }}
        select:focus {{ outline: none; border-color: #e74c3c; }}
        .story-display {{ background: var(--bg-deep); padding: 2rem; border-radius: 8px; margin-top: 1.5rem; border: 1px solid var(--border); min-height: 300px; color: var(--text); line-height: 1.8; }}
        .badge {{ display: inline-block; padding: 0.3rem 0.8rem; border-radius: 20px; font-size: 0.85rem; font-weight: 600; }}
        .badge-axiom        {{ background: rgba(147,112,219,0.25); color: #c9b8ff; border: 2px solid rgba(147,112,219,0.9); box-shadow: 0 0 8px rgba(147,112,219,0.5), inset 0 0 6px rgba(147,112,219,0.15); font-weight: 800; }}
        .badge-apex-officer {{ background: rgba(255,200,0,0.2);    color: #ffd700; border: 2px solid rgba(255,200,0,0.9);    box-shadow: 0 0 8px rgba(255,200,0,0.45),    inset 0 0 6px rgba(255,200,0,0.1);    font-weight: 800; }}
        .badge-officer      {{ background: rgba(255,220,80,0.15);  color: #ffe680; border: 2px solid rgba(255,220,80,0.8);   box-shadow: 0 0 6px rgba(255,220,80,0.35),   inset 0 0 4px rgba(255,220,80,0.08);  font-weight: 800; }}
        .badge-apex-templar {{ background: rgba(139,0,0,0.35);     color: #ff9999; border: 1px solid #8b0000; }}
        .badge-templar      {{ background: rgba(200,50,50,0.2);    color: #ff8080; border: 1px solid rgba(200,50,50,0.4); }}
        .badge-apex-ranger  {{ background: rgba(0,0,180,0.35);     color: #99bbff; border: 1px solid #0000b4; }}
        .badge-ranger       {{ background: rgba(100,160,255,0.15); color: #74b9ff; border: 1px solid rgba(100,160,255,0.3); }}
        .badge-apex-scout   {{ background: rgba(0,100,0,0.35);     color: #90ee90; border: 1px solid #006400; }}
        .badge-scout        {{ background: rgba(100,200,100,0.15); color: #55efc4; border: 1px solid rgba(100,200,100,0.3); }}
        .streak {{ color: #ff6b6b; font-weight: bold; }}
        .expandable-trigger {{ cursor: pointer; }}
        .expand-icon {{ display: inline-block; transition: transform 0.2s; color: #e74c3c; font-size: 0.7em; }}
        .expand-icon.open {{ transform: rotate(90deg); }}
        .breakdown-row {{ display: none; }}
        .breakdown-row.open {{ display: table-row; }}
        .breakdown-inner {{ padding: 0; }}
        .inline-panel {{
            background: var(--panel-bg, #0d1117);
            padding: 1.2rem 1.5rem;
            border-top: 2px solid #e74c3c;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.2rem;
            transition: background 0.3s;
        }}
        body.light-mode .inline-panel {{ --panel-bg: #f0ece8; }}
        .panel-title {{ font-size: 0.68rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 0.7rem; font-weight: 600; }}
        .sp-cards-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; }}
        .sp-card {{ background: var(--bg-card); border-radius: 8px; padding: 0.7rem 0.9rem; border-left: 4px solid #e74c3c; transition: background 0.3s; }}
        .sp-card.clan    {{ border-left-color: #3498db; }}
        .sp-card.alltime {{ border-left-color: #2ecc71; }}
        .sp-card.events  {{ border-left-color: #f39c12; }}
        .sp-card.weekly  {{ border-left-color: #9b59b6; }}
        .sp-card .sc-label {{ font-size: 0.7rem; color: var(--text-muted); margin-bottom: 0.2rem; }}
        .sp-card .sc-value {{ font-size: 1.3rem; font-weight: bold; color: var(--text); line-height: 1; }}
        .sp-bar-panel {{ margin-top: 0.5rem; }}
        .sp-bar-panel .bar-track {{ height: 10px; border-radius: 5px; background: var(--bg-hover); overflow: hidden; display: flex; margin-bottom: 0.5rem; }}
        .sp-bar-panel .bar-seg {{ height: 100%; transition: width 0.5s ease; }}
        .bar-seg.s-clan    {{ background: #3498db; }}
        .bar-seg.s-alltime {{ background: #2ecc71; }}
        .bar-seg.s-events  {{ background: #f39c12; }}
        .bar-seg.s-weekly  {{ background: #9b59b6; }}
        .sp-legend-panel {{ display: flex; flex-direction: column; gap: 0.3rem; }}
        .sleg-row {{ display: flex; justify-content: space-between; font-size: 0.78rem; }}
        .sleg-label {{ display: flex; align-items: center; gap: 0.4rem; color: var(--text-muted); }}
        .sleg-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
        .sleg-val {{ color: var(--text); font-weight: 600; }}
        .progress-wrap {{ min-width: 120px; }}
        .progress-bar-bg {{ background: var(--bg-hover); border-radius: 4px; height: 6px; margin-top: 4px; }}
        .progress-bar-fill {{ background: #e74c3c; border-radius: 4px; height: 6px; transition: width 0.3s; }}
        .top-performers {{ list-style: none; padding: 0; }}
        .top-performers li {{ padding: 1rem; background: var(--bg-deep); margin-bottom: 0.5rem; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; border: 1px solid var(--border); transition: border-color 0.2s; }}
        .top-performers li:hover {{ border-color: #e74c3c; }}
        .top-performers .medal {{ font-size: 1.5rem; margin-right: 1rem; }}
        .top-performers li.tp-gold   {{ background: rgba(184,148,20,0.12); border-color: rgba(184,148,20,0.35); }}
        .top-performers li.tp-silver {{ background: rgba(160,160,160,0.10); border-color: rgba(160,160,160,0.30); }}
        .top-performers li.tp-bronze {{ background: rgba(155,95,40,0.12);  border-color: rgba(155,95,40,0.30); }}
        .top-performers li.tp-gold:hover   {{ border-color: rgba(184,148,20,0.65); }}
        .top-performers li.tp-silver:hover {{ border-color: rgba(160,160,160,0.55); }}
        .top-performers li.tp-bronze:hover {{ border-color: rgba(155,95,40,0.55); }}
        .promotion-list {{ list-style: none; padding: 0; }}
        .promotion-list li {{ padding: 1rem; background: var(--bg-deep); margin-bottom: 0.5rem; border-radius: 8px; border-left: 4px solid #e74c3c; color: var(--text); }}
        .chart-container {{ position: relative; height: 400px; margin-bottom: 2rem; }}
        .chart-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(500px, 1fr)); gap: 2rem; }}
        .footer {{ text-align: center; padding: 2rem; color: var(--text-muted); font-size: 0.9rem; border-top: 1px solid var(--border2); }}
        /* ── HEATMAP ── */
        .hm-table {{ border-collapse: collapse; table-layout: auto; white-space: nowrap; }}
        .hm-table th {{ font-size: 0.7rem; color: white; font-weight: 600; letter-spacing: 1px; padding: 0.4rem 6px; background: #e74c3c; }}
        .hm-table td {{ padding: 3px 4px; border-bottom: 1px solid var(--border2); background: var(--bg-card); }}
        .hm-table tbody tr:hover td {{ background: var(--bg-hover); }}
        .hm-col-name {{ position: sticky; left: 0; z-index: 3; min-width: 140px; text-align: left; box-shadow: 2px 0 6px rgba(0,0,0,0.4); }}
        .hm-table th.hm-col-name {{ background: #e74c3c; }}
        .hm-table td.hm-col-name {{ background: var(--bg-card); font-weight: 600; font-size: 0.85rem; }}
        .hm-table tbody tr:hover td.hm-col-name {{ background: var(--bg-hover); }}
        .hm-col-week   {{ min-width: 40px; text-align: left; }}
        .hm-col-cur  {{ position: sticky; right: 310px; z-index: 2; width: 80px;  min-width: 80px;  max-width: 80px;  text-align: center; box-shadow: -2px 0 6px rgba(0,0,0,0.3); }}
        .hm-col-best {{ position: sticky; right: 155px; z-index: 2; width: 155px; min-width: 155px; max-width: 155px; text-align: center; }}
        .hm-col-stat {{ position: sticky; right: 0;     z-index: 2; width: 155px; min-width: 155px; max-width: 155px; text-align: left; padding-left: 8px; }}
        .hm-table th.hm-col-cur, .hm-table th.hm-col-best, .hm-table th.hm-col-stat {{ background: #e74c3c; }}
        .hm-table td.hm-col-cur, .hm-table td.hm-col-best, .hm-table td.hm-col-stat {{ background: var(--bg-card); }}
        .hm-table tbody tr:hover td.hm-col-cur,
        .hm-table tbody tr:hover td.hm-col-best,
        .hm-table tbody tr:hover td.hm-col-stat {{ background: var(--bg-hover); }}
        .hm-cell {{
            display: inline-flex; align-items: center; justify-content: center;
            width: 36px; height: 28px; border-radius: 5px;
            font-size: 0.78rem; font-weight: 700;
            transition: transform 0.15s;
            cursor: default;
        }}
        .hm-cell:hover {{ transform: scale(1.2); }}
        .hm-active   {{ background: rgba(46,204,113,0.2);   color: #2ecc71; border: 1px solid rgba(46,204,113,0.4); }}
        .hm-inactive {{ background: rgba(231,76,60,0.15);   color: #e74c3c; border: 1px solid rgba(231,76,60,0.3); }}
        .hm-absent   {{ background: rgba(255,255,255,0.03); color: #555;    border: 1px solid rgba(255,255,255,0.07); }}
        .hm-pill {{ display: inline-block; padding: 0.1rem 0.4rem; border-radius: 20px; font-size: 0.72rem; font-weight: 700; white-space: nowrap; }}
        .hm-pill-hot  {{ background: rgba(255,107,107,0.15); color: #ff6b6b; border: 1px solid rgba(255,107,107,0.3); }}
        .hm-pill-warm {{ background: rgba(243,156,18,0.15);  color: #f39c12; border: 1px solid rgba(243,156,18,0.3); }}
        .hm-pill-cold {{ background: rgba(255,255,255,0.05); color: var(--text-muted); border: 1px solid var(--border); }}
        /* ── EVENTS TIMELINE ── */
        .tl-container {{ position: relative; padding-left: 2rem; }}
        .tl-container::before {{ content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 2px; background: linear-gradient(to bottom, #e74c3c, #21262d); border-radius: 2px; }}
        .tl-item {{ position: relative; margin-bottom: 1.2rem; }}
        .tl-dot {{ position: absolute; left: -2.4rem; top: 1.2rem; width: 13px; height: 13px; border-radius: 50%; border: 2px solid #e74c3c; background: var(--bg-deep); z-index: 1; transition: background 0.2s; }}
        .tl-dot-live {{ background: #e74c3c !important; box-shadow: 0 0 8px rgba(231,76,60,0.6); }}
        .tl-item:hover .tl-dot {{ background: #e74c3c; }}
        .tl-card {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; cursor: pointer; transition: border-color 0.2s, box-shadow 0.2s; }}
        .tl-card:hover {{ border-color: #e74c3c; box-shadow: 0 4px 20px rgba(231,76,60,0.08); }}
        .tl-header {{ display: grid; grid-template-columns: 64px 1fr auto; gap: 1rem; align-items: center; padding: 1rem 1.2rem; }}
        .tl-img {{ width: 64px; height: 64px; border-radius: 8px; object-fit: cover; background: #21262d; flex-shrink: 0; }}
        .tl-info {{ min-width: 0; }}
        .tl-title {{ font-weight: 700; font-size: 1rem; color: var(--text); margin-bottom: 0.4rem; }}
        .tl-meta {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.4rem; }}
        .tl-desc {{ font-size: 0.78rem; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .tl-chevron {{ color: var(--text-muted); font-size: 0.75rem; transition: transform 0.2s; padding: 0.3rem; flex-shrink: 0; }}
        .tl-chevron.open {{ transform: rotate(180deg); color: #e74c3c; }}
        .tl-expand {{ display: none; border-top: 1px solid var(--border); padding: 1.2rem; background: var(--bg-deep); }}
        .tl-full-desc {{ font-size: 0.83rem; color: var(--text); line-height: 1.6; margin-bottom: 1.2rem; padding: 0.8rem 1rem; background: var(--bg-card); border-radius: 8px; border: 1px solid var(--border); }}
        .ev-badge {{ display: inline-block; padding: 0.12rem 0.55rem; border-radius: 20px; font-size: 0.68rem; font-weight: 600; white-space: nowrap; }}
        .ev-badge-ongoing  {{ background: rgba(231,76,60,0.15); color: #e74c3c; border: 1px solid rgba(231,76,60,0.3); }}
        .ev-badge-completed {{ background: rgba(46,204,113,0.15); color: #2ecc71; border: 1px solid rgba(46,204,113,0.3); }}
        .ev-badge-type {{ background: rgba(116,185,255,0.12); color: #74b9ff; border: 1px solid rgba(116,185,255,0.25); }}
        .ev-badge-week {{ background: rgba(255,255,255,0.05); color: var(--text-muted); border: 1px solid var(--border); }}
        .ev-pulse {{ display: inline-block; width: 7px; height: 7px; background: #e74c3c; border-radius: 50%; margin-right: 4px; animation: evpulse 1.5s infinite; vertical-align: middle; }}
        @keyframes evpulse {{ 0%,100%{{opacity:1;transform:scale(1)}} 50%{{opacity:0.3;transform:scale(1.5)}} }}
        .ev-winners-label {{ font-family: 'Bebas Neue', sans-serif; font-size: 1rem; color: #ffd700; letter-spacing: 1px; margin-bottom: 0.7rem; }}
        .ev-table {{ width: 100%; border-collapse: collapse; font-size: 0.83rem; }}
        .ev-table th {{ text-align: left; padding: 0.4rem 0.7rem; color: var(--text-muted); font-size: 0.68rem; font-weight: 600; letter-spacing: 1px; border-bottom: 1px solid var(--border); background: transparent; cursor: default; }}
        .ev-table td {{ padding: 0.5rem 0.7rem; border-bottom: 1px solid var(--border2); background: transparent; }}
        .ev-table tbody tr:hover td {{ background: var(--bg-hover); }}
        .ev-role-badge {{ display: inline-block; padding: 0.1rem 0.45rem; border-radius: 20px; font-size: 0.68rem; font-weight: 600; background: rgba(255,215,0,0.1); color: #ffd700; border: 1px solid rgba(255,215,0,0.25); }}
        .ev-sp-val {{ color: #ffd700; font-weight: 700; }}
        .ev-cash-val {{ color: #2ecc71; font-weight: 600; }}
        .ev-credit-val {{ color: #74b9ff; font-weight: 600; }}
        .ev-notes-val {{ color: var(--text-muted); font-size: 0.78rem; }}
        .ev-no-results {{ color: var(--text-muted); font-size: 0.83rem; }}
        .ev-empty {{ color: var(--text-muted); font-size: 0.85rem; padding: 0.5rem 0; }}
        /* ── SIMULATOR ── */
        .sim-layout {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; }}
        .sim-left {{ display: flex; flex-direction: column; gap: 1.2rem; }}
        .sim-block {{ background: var(--bg-deep); border-radius: 10px; padding: 1.5rem; border: 1px solid var(--border); }}
        .sim-block h3 {{ font-size: 1rem; margin-bottom: 1.2rem; display: flex; align-items: center; gap: 0.5rem; color: var(--text); }}
        .sim-block-num {{ background: #e74c3c; color: white; width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 0.75rem; font-weight: bold; flex-shrink: 0; }}
        .sim-fixed-note {{ font-size: 0.75rem; color: var(--text-muted); font-weight: normal; margin-left: 0.3rem; }}
        .sim-input-row {{ margin-bottom: 1.1rem; }}
        .sim-input-row:last-child {{ margin-bottom: 0; }}
        .sim-input-row label {{ display: flex; justify-content: space-between; font-size: 0.88rem; font-weight: 600; margin-bottom: 0.4rem; color: var(--text); }}
        .sim-cur {{ color: #3498db; font-size: 0.78rem; }}
        .sim-val {{ color: #e74c3c; }}
        .sim-input-row input[type=range] {{ width: 100%; accent-color: #e74c3c; }}
        .sim-hint {{ font-size: 0.75rem; color: var(--text-muted); margin-top: 0.2rem; }}
        .sim-fixed-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; }}
        .sim-fixed-item {{ background: var(--bg-card); border-radius: 8px; padding: 0.6rem 0.8rem; border: 1px solid var(--border); }}
        .sim-fi-label {{ font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; margin-bottom: 0.2rem; }}
        .sim-fi-value {{ font-size: 1.1rem; font-weight: bold; color: var(--text); }}
        .sim-fi-sub {{ font-size: 0.78rem; color: var(--text-muted); }}
        .sim-fi-sp {{ font-size: 0.78rem; color: #2ecc71; font-weight: bold; }}
        .sim-right {{ display: flex; flex-direction: column; gap: 1.2rem; }}
        .sim-card {{ background: var(--bg-deep); border-radius: 10px; padding: 1.5rem; border: 1px solid var(--border); border-left: 5px solid #e74c3c; }}
        .sim-card.blue   {{ border-left-color: #3498db; }}
        .sim-card.orange {{ border-left-color: #f39c12; }}
        .sim-card.purple {{ border-left-color: #9b59b6; }}
        .sim-card h4 {{ font-size: 0.82rem; color: var(--text-muted); text-transform: uppercase; margin-bottom: 0.8rem; }}
        .sim-total-row {{ display: flex; align-items: baseline; gap: 0.8rem; flex-wrap: wrap; }}
        .sim-big {{ font-size: 2.4rem; font-weight: bold; color: #e74c3c; line-height: 1; }}
        .sim-change {{ font-size: 1.2rem; font-weight: bold; padding: 0.2rem 0.7rem; border-radius: 8px; }}
        .sim-pos  {{ background: rgba(46,204,113,0.15); color: #2ecc71; }}
        .sim-neg  {{ background: rgba(231,76,60,0.15); color: #ff6b6b; }}
        .sim-zero {{ background: var(--bg-hover); color: var(--text-muted); }}
        .sim-rank-line {{ margin-top: 0.5rem; font-size: 0.9rem; color: var(--text-muted); }}
        .sim-rank-line strong {{ color: var(--text); }}
        .sim-mult {{ display: inline-block; background: rgba(243,156,18,0.15); color: #f39c12; padding: 0.2rem 0.7rem; border-radius: 12px; font-size: 0.85rem; font-weight: bold; margin-left: 0.5rem; border: 1px solid rgba(243,156,18,0.3); }}
        .sim-mini-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.5rem; margin-top: 0.8rem; }}
        .sim-mini-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; margin-top: 0.8rem; }}
        .sim-mini {{ background: var(--bg-card); border-radius: 6px; padding: 0.5rem 0.6rem; border: 1px solid var(--border); }}
        .sim-mini .sm-label {{ font-size: 0.7rem; color: var(--text-muted); }}
        .sim-mini .sm-val {{ font-size: 1rem; font-weight: bold; color: var(--text); }}
        .sim-mini .sm-delta {{ font-size: 0.75rem; font-weight: bold; }}
        .sim-bar-section {{ margin-top: 0.6rem; }}
        .sim-bar-row {{ margin-bottom: 0.6rem; }}
        .sim-bar-label {{ display: flex; justify-content: space-between; font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.2rem; }}
        .sim-load-bar {{ display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; margin-bottom: 2rem; padding: 1rem 1.5rem; background: var(--bg-deep); border-radius: 10px; border: 1px solid var(--border); }}
        .sim-load-bar label {{ font-weight: 600; color: var(--text); }}
        .sim-load-bar select {{ padding: 0.6rem 1rem; border: 1px solid var(--border); border-radius: 8px; font-size: 1rem; cursor: pointer; min-width: 200px; color: var(--text); background: var(--bg-card); width: auto; margin-bottom: 0; }}
        .sim-load-btn {{ background: #e74c3c; color: white; border: none; padding: 0.6rem 1.4rem; border-radius: 8px; font-size: 1rem; cursor: pointer; font-weight: 600; }}
        .sim-load-btn:hover {{ background: #c0392b; }}
        .sim-loaded-tag {{ background: rgba(46,204,113,0.15); color: #2ecc71; padding: 0.3rem 0.9rem; border-radius: 20px; font-size: 0.82rem; font-weight: 600; display: none; border: 1px solid rgba(46,204,113,0.3); }}
        .sim-loaded-tag.show {{ display: inline-block; }}
        .sim-bar-bg {{ background: var(--bg-hover); border-radius: 4px; height: 8px; }}
        .sim-bar-f {{ height: 8px; border-radius: 4px; transition: width 0.4s; }}
        .sb-clan    {{ background: #3498db; }}
        .sb-alltime {{ background: #2ecc71; }}
        .sb-events  {{ background: #f39c12; }}
        .sb-weekly  {{ background: #9b59b6; }}
        @media (max-width: 768px) {{ .sim-layout {{ grid-template-columns: 1fr; }} }}

        @media (max-width: 768px) {{
            .nav {{ flex-direction: column; }}
            .stat-grid {{ grid-template-columns: 1fr; }}
            .chart-grid {{ grid-template-columns: 1fr; }}
            .header h1 {{ font-size: 1.8rem; }}
            table {{ font-size: 0.85rem; }}
            th, td {{ padding: 0.5rem; }}
            .chart-container {{ height: 300px; }}
        }}

        /* ═══════════════════════════════════════════
           MEDALS OF HONOR — BADGE ANIMATIONS
        ═══════════════════════════════════════════ */
        @keyframes mshine   {{ 0%{{left:-80%}} 40%{{left:120%}} 100%{{left:120%}} }}
        @keyframes mgold    {{ from{{box-shadow:inset 0 -2px 6px rgba(0,0,0,0.7),0 0 5px rgba(255,200,0,0.25)}} to{{box-shadow:inset 0 -2px 6px rgba(0,0,0,0.7),0 0 14px rgba(255,200,0,0.55)}} }}
        @keyframes msh-a    {{ 0%{{left:-80%;opacity:0}} 5%{{opacity:1}} 14%{{left:120%;opacity:0.9}} 16%{{opacity:0;left:120%}} 100%{{left:120%;opacity:0}} }}
        @keyframes msh-b    {{ 0%{{left:-80%;opacity:0}} 16%{{left:-80%;opacity:0}} 18%{{opacity:0.75}} 28%{{left:120%;opacity:0.6}} 30%{{opacity:0;left:120%}} 100%{{left:120%;opacity:0}} }}
        @keyframes msh-c    {{ 0%{{left:-80%;opacity:0}} 30%{{left:-80%;opacity:0}} 32%{{opacity:0.5}} 40%{{left:120%;opacity:0.35}} 42%{{opacity:0;left:120%}} 100%{{left:120%;opacity:0}} }}
        @keyframes mevglow  {{ from{{box-shadow:0 0 4px rgba(162,155,254,0.3)}} to{{box-shadow:0 0 12px rgba(162,155,254,0.6)}} }}
        @keyframes mevshine {{ 0%{{left:-80%;opacity:0}} 10%{{opacity:1}} 45%{{left:130%;opacity:0.7}} 50%{{opacity:0;left:130%}} 100%{{left:130%;opacity:0}} }}

        /* ── circle badge base ── */
        .moh-wrap {{ display:flex; gap:5px; align-items:center; flex-wrap:wrap; }}
        .moh-empty {{ color:var(--muted); font-family:'Share Tech Mono',monospace; font-size:11px; }}
        .mab {{
            display:inline-flex; flex-direction:column; align-items:center; justify-content:center;
            width:36px; height:36px; border-radius:50%; border:2px solid;
            gap:0; cursor:default; position:relative; overflow:hidden; flex-shrink:0;
        }}
        .mab::before {{ content:''; position:absolute; inset:0; border-radius:50%;
            background:radial-gradient(circle at 38% 28%,rgba(255,255,255,0.14),transparent 58%);
            pointer-events:none; z-index:2; }}
        .mab::after {{ content:''; position:absolute; bottom:0; left:0; right:0; height:2px; z-index:2; }}
        .mab .msh {{ position:absolute; top:-10%; height:120%; transform:skewX(-15deg);
            z-index:3; pointer-events:none; background:linear-gradient(90deg,transparent,rgba(255,255,255,0.28),transparent); }}
        .mab .msh1 {{ width:28%; animation:mshine 3.5s ease-in-out infinite; }}
        .mab .mi {{ font-size:13px; line-height:1; position:relative; z-index:4; }}
        .mab .ml {{ font-family:'Black Ops One',cursive; font-size:7px; letter-spacing:0.5px; line-height:1; position:relative; z-index:4; }}
        .mab-wrap {{ display:inline-flex; flex-direction:column; align-items:center; gap:2px; cursor:default; }}
        .mab-count {{ font-family:'Share Tech Mono',monospace; font-size:8px; color:var(--text-muted); line-height:1; }}
        /* TS — silver */
        .mab-silver {{ border-color:#b0b8c8; background:radial-gradient(circle at 40% 32%,#5a6070,#1a1e24 70%); color:#d0d8e8;
            box-shadow:inset 0 1px 4px rgba(180,200,220,0.15),inset 0 -2px 6px rgba(0,0,0,0.6),0 2px 6px rgba(0,0,0,0.5); }}
        .mab-silver::after {{ background:linear-gradient(90deg,transparent,#b0c0d8,transparent); }}
        /* TPK + GL — gold */
        .mab-gold {{ border-color:#ffd700; background:radial-gradient(circle at 40% 32%,#4a3000,#100b00 72%); color:#ffd700;
            box-shadow:inset 0 -2px 6px rgba(0,0,0,0.7),0 2px 6px rgba(0,0,0,0.5);
            animation:mgold 2.5s ease-in-out infinite alternate; }}
        .mab-gold::after {{ background:linear-gradient(90deg,transparent,#ffd700,transparent); }}
        /* STK — bronze */
        .mab-bronze {{ border-color:#cd7f32; background:radial-gradient(circle at 40% 32%,#5a2e08,#180900 72%); color:#e8a855;
            box-shadow:inset 0 -2px 6px rgba(0,0,0,0.7),0 2px 6px rgba(0,0,0,0.5); }}
        .mab-bronze::after {{ background:linear-gradient(90deg,transparent,#cd7f32,transparent); }}
        /* TL — platinum (triple shine) */
        .mab-platinum {{ border-color:#ffffff; border-width:2.5px;
            background:radial-gradient(circle at 38% 28%,#1c1c28,#000000 68%); color:#ffffff;
            box-shadow:inset 0 0 10px rgba(255,255,255,0.08),inset 0 -2px 8px rgba(0,0,0,0.9),
                       0 0 10px rgba(255,255,255,0.4),0 0 22px rgba(200,200,255,0.2); }}
        .mab-platinum::after {{ background:linear-gradient(90deg,transparent,#ffffff,transparent); box-shadow:0 0 6px rgba(255,255,255,0.8); }}
        .mab-platinum .msh1 {{ width:16%; animation:msh-a 5s ease-in-out infinite; background:linear-gradient(90deg,transparent,rgba(255,255,255,0.7),transparent); }}
        .mab-platinum .msh2 {{ position:absolute; top:-10%; width:10%; height:120%; transform:skewX(-15deg); z-index:3; pointer-events:none;
            animation:msh-b 5s ease-in-out infinite; background:linear-gradient(90deg,transparent,rgba(255,255,255,0.5),transparent); }}
        .mab-platinum .msh3 {{ position:absolute; top:-10%; width:6%; height:120%; transform:skewX(-15deg); z-index:3; pointer-events:none;
            animation:msh-c 5s ease-in-out infinite; background:linear-gradient(90deg,transparent,rgba(255,255,255,0.3),transparent); }}
        /* event pill */
        .mev {{ display:inline-flex; align-items:center; height:36px; border-radius:18px; border:2px solid #a29bfe; overflow:hidden;
            background:linear-gradient(135deg,rgba(80,60,160,0.5) 0%,rgba(20,10,60,0.85) 100%);
            flex-shrink:0; cursor:default; position:relative; animation:mevglow 2.5s ease-in-out infinite alternate; }}
        .mev::before {{ content:''; position:absolute; inset:0; background:radial-gradient(ellipse at 30% 30%,rgba(200,180,255,0.12),transparent 65%); pointer-events:none; z-index:1; }}
        .mev::after  {{ content:''; position:absolute; bottom:0; left:0; right:0; height:2px; background:linear-gradient(90deg,transparent,#a29bfe,transparent); z-index:1; }}
        .mev .mev-sh {{ position:absolute; top:-10%; width:35%; height:120%; transform:skewX(-15deg);
            background:linear-gradient(90deg,transparent,rgba(200,180,255,0.25),transparent); animation:mevshine 4s ease-in-out infinite; z-index:2; pointer-events:none; }}
        .mev .mev-icon {{ display:flex; align-items:center; justify-content:center; width:30px; font-size:14px; position:relative; z-index:3; }}
        .mev .mev-div  {{ width:1px; height:20px; background:rgba(162,155,254,0.35); flex-shrink:0; }}
        .mev .mev-num  {{ display:flex; align-items:center; justify-content:center; padding:0 10px;
            font-family:'Black Ops One',cursive; font-size:13px; color:#c4b8ff; letter-spacing:0.5px;
            position:relative; z-index:3; min-width:26px; text-shadow:0 0 8px rgba(162,155,254,0.6); }}
        /* statboard column */
        .moh-col {{ white-space:nowrap; }}
        /* ── Medals of Honor page ── */
        .moh-cat-block {{ margin-bottom:2.4rem; }}
        .moh-cat-header {{ display:flex; align-items:center; gap:1rem; padding:0.7rem 1.2rem;
            background:linear-gradient(90deg,rgba(192,57,43,0.12),transparent);
            border-left:3px solid var(--blood); border-bottom:1px solid var(--border); }}
        .moh-cat-icon {{ font-size:1.2rem; }}
        .moh-cat-name {{ font-family:'Black Ops One',cursive; font-size:0.95rem; letter-spacing:2px; }}
        .moh-cat-abbr {{ font-family:'Share Tech Mono',monospace; font-size:0.65rem; color:var(--muted); letter-spacing:3px; margin-left:auto; }}
        .moh-tier-row {{ display:grid; grid-template-columns:repeat(4,1fr);
            border:1px solid var(--border); border-top:none; background:var(--bg-card); }}
        .moh-tier-col {{ padding:1.4rem 1rem 1.2rem; border-right:1px solid var(--border2);
            display:flex; flex-direction:column; align-items:center; gap:0.5rem; position:relative;
            transition:background 0.2s; }}
        .moh-tier-col:last-child {{ border-right:none; }}
        .moh-tier-col:hover {{ background:rgba(255,255,255,0.02); }}
        .moh-tier-col::before {{ content:''; position:absolute; top:0; left:0; right:0; height:2px; }}
        .moh-tier-col.tc-br::before {{ background:linear-gradient(90deg,transparent,#cd7f32,transparent); }}
        .moh-tier-col.tc-si::before {{ background:linear-gradient(90deg,transparent,#b0b8c8,transparent); }}
        .moh-tier-col.tc-go::before {{ background:linear-gradient(90deg,transparent,#ffd700,transparent); }}
        .moh-tier-col.tc-pl::before {{ background:linear-gradient(90deg,transparent,#ffffff,transparent); }}
        .moh-tier-name {{ font-family:'Black Ops One',cursive; font-size:0.78rem; letter-spacing:1px; margin-top:0.2rem; }}
        .moh-tier-name.tc-br {{ color:#cd7f32; }}
        .moh-tier-name.tc-si {{ color:#b0b8c8; }}
        .moh-tier-name.tc-go {{ color:#ffd700; }}
        .moh-tier-name.tc-pl {{ color:#ffffff;
            text-shadow:0 0 4px #000,1px 1px 0 #000,-1px -1px 0 #000,1px -1px 0 #000,-1px 1px 0 #000; }}
        .moh-tier-thresh {{ font-family:'Share Tech Mono',monospace; font-size:0.62rem; color:#a93226; letter-spacing:0.3px; text-align:center; line-height:1.3; }}
        .moh-tier-cash {{ font-family:'Share Tech Mono',monospace; font-size:0.65rem; color:#27ae60; }}
        .moh-tier-cash span {{ color:var(--muted); font-size:0.58rem; }}
        .moh-divider {{ width:80%; height:1px; background:var(--border2); margin:0.3rem 0; }}
        .moh-earners {{ display:flex; flex-direction:column; align-items:center; gap:0.25rem; width:100%; }}
        .moh-earner {{ display:flex; align-items:center; justify-content:center; gap:0.4rem; width:100%;
            padding:0.25rem 0.5rem; border-radius:4px; transition:background 0.15s; }}
        .moh-earner:hover {{ background:rgba(255,255,255,0.04); }}
        .moh-earner-name {{ font-family:'Rajdhani',sans-serif; font-weight:700; font-size:0.82rem; color:var(--text); }}
        .moh-earner-count {{ font-family:'Share Tech Mono',monospace; font-size:0.65rem; color:#c0392b; margin-left:auto; }}
        .moh-earner-none {{ font-family:'Share Tech Mono',monospace; font-size:0.68rem; color:var(--muted); letter-spacing:1px; padding:0.4rem 0; opacity:0.5; }}
        /* Event winners */
        .moh-ev-grid {{ display:flex; flex-wrap:wrap; gap:1rem; padding:1.4rem;
            background:var(--bg-card); border:1px solid var(--border); border-top:none; }}
        .moh-ev-card {{ display:flex; flex-direction:column; align-items:center; gap:0.5rem;
            background:var(--bg-deep); border:1px solid rgba(162,155,254,0.15); border-radius:8px;
            padding:1rem 1.4rem; min-width:100px; position:relative; transition:border-color 0.2s,box-shadow 0.2s; }}
        .moh-ev-card:hover {{ border-color:rgba(162,155,254,0.4); box-shadow:0 0 16px rgba(162,155,254,0.1); }}
        .moh-ev-card::before {{ content:''; position:absolute; top:0; left:0; right:0; height:1px;
            background:linear-gradient(90deg,transparent,rgba(162,155,254,0.5),transparent); }}
        .moh-ev-name {{ font-family:'Rajdhani',sans-serif; font-weight:700; font-size:0.85rem; color:var(--text); }}
        /* Platinum badge text outline for light mode */
        .mab-platinum .mi, .mab-platinum .ml {{
            text-shadow:0 0 3px #000,0 0 6px #000,1px 1px 0 #000,-1px -1px 0 #000,1px -1px 0 #000,-1px 1px 0 #000; }}
        @media (max-width:768px) {{ .moh-tier-row {{ grid-template-columns:repeat(2,1fr); }} }}
        /* ── BEST WEEK ── */
        .bw-tabs {{ display:flex; gap:0; margin-bottom:0; border-bottom:1px solid var(--border2); }}
        .bw-tab {{
            padding:10px 24px; font-family:'Rajdhani',sans-serif; font-weight:700;
            font-size:13px; letter-spacing:1px; text-transform:uppercase;
            color:var(--muted); background:none; border:none;
            border-bottom:2px solid transparent; cursor:pointer;
            transition:color 0.15s; margin-bottom:-1px;
        }}
        .bw-tab.active {{ color:#ffd700; border-bottom-color:#ffd700; }}
        .bw-tab:hover:not(.active) {{ color:var(--text); }}
        .bw-table {{ width:100%; border-collapse:collapse; background:transparent; border-radius:0; }}
        .bw-table thead th {{
            font-family:'Share Tech Mono',monospace; font-size:10px; letter-spacing:2px;
            color:var(--muted); text-transform:uppercase; padding:12px 16px;
            text-align:left; border-bottom:1px solid var(--border2); background:transparent;
            cursor:default; user-select:none;
        }}
        .bw-table thead th:last-child {{ text-align:right; }}
        .bw-table tbody td {{ padding:12px 16px; border-bottom:1px solid var(--border2); vertical-align:middle; }}
        .bw-table tbody tr:last-child td {{ border-bottom:none; }}
        .bw-table tbody tr:nth-child(even) td {{ background:rgba(255,255,255,0.015); }}
        .bw-table tbody tr:hover td {{ background:var(--bg-hover); }}
        .bw-pos-cell {{ display:flex; align-items:center; gap:0; }}
        .bw-stripe {{ width:3px; height:38px; flex-shrink:0; margin-right:12px; }}
        .bw-stripe-1 {{ background:#ffd700; }}
        .bw-stripe-2 {{ background:#b0b8c8; }}
        .bw-stripe-3 {{ background:#a0623a; }}
        .bw-stripe-n {{ background:#2a2a2a; }}
        .bw-pos {{ font-family:'Black Ops One',cursive; font-size:18px; min-width:28px; text-align:center; }}
        .bw-pos-1 {{ color:#ffd700; text-shadow:0 0 10px rgba(255,215,0,0.5); }}
        .bw-pos-2 {{ color:#b0b8c8; }}
        .bw-pos-3 {{ color:#a0623a; }}
        .bw-pos-n {{ color:#333; }}
        .bw-name {{ font-family:'Rajdhani',sans-serif; font-weight:700; font-size:16px; color:var(--text); }}
        .bw-val-cell {{ text-align:right; }}
        .bw-week-tag {{ font-family:'Share Tech Mono',monospace; font-size:10px; color:var(--muted); letter-spacing:0.5px; display:block; }}
        .bw-val {{ font-family:'Black Ops One',cursive; font-size:20px; color:#ffd700; text-shadow:0 0 12px rgba(255,215,0,0.35); display:block; margin-top:2px; }}
        .bw-note {{ font-family:'Share Tech Mono',monospace; font-size:10px; color:var(--muted); letter-spacing:1px; margin-top:1.2rem; opacity:0.7; }}
    </style>
</head>
<body>
    <header class="site-header">
        <div class="danger-stripe"></div>
        <div class="hero">
            <button id="themeToggle" onclick="toggleTheme()" style="
                position:absolute; top:1rem; right:1.5rem;
                background: rgba(192,57,43,0.15); border: 1px solid rgba(192,57,43,0.4);
                color: var(--text); padding: 0.4rem 1rem; border-radius: 3px;
                cursor: pointer; font-size: 0.8rem; font-weight:600; letter-spacing:1px;
                font-family: 'Share Tech Mono', monospace; transition: all 0.3s;
                text-transform: uppercase;
            ">☀️ Light</button>
            <div class="hero-badge">Dead Frontier · Clan Operations</div>
            <div class="title-deco">
                <div class="title-deco-line"></div>
                <h1 class="clan-title"><span>APEX</span> CLAN STATS</h1>
                <div class="title-deco-line"></div>
            </div>
            <div class="hero-sub">
                <span class="highlight">{current_week}</span>
                <div class="sep"></div>
                <span>Game Week</span>
                <div class="sep"></div>
                <span class="highlight">Dead Frontier</span>
            </div>
            <div style="display:flex;justify-content:center;margin-top:10px;">
                <div class="live-dot">LIVE DATA</div>
            </div>
        </div>
        <div class="danger-stripe"></div>
        <nav class="nav">
            <div class="nav-inner">
                <button onclick="showPage('home', event)" class="active">🏠 Home</button>
                <button onclick="showPage('statboard', event)">📊 Statboard</button>
                <button onclick="showPage('activity', event)">🔥 Activity</button>
                <button onclick="showPage('charts', event)">📈 Charts</button>
                <button onclick="showPage('stories', event)">📖 Stories</button>
                <button onclick="showPage('events', event)">🎉 Events</button>
                <button onclick="showPage('medals', event)">🎖️ Medals of Honor</button>
                <button onclick="showPage('bestweek', event)">🏆 Best Week</button>
                <button onclick="showPage('simulator', event)">⭐ Simulator</button>
                <button onclick="showPage('armory', event)">⚔️ Armory</button>
            </div>
        </nav>
    </header>
    <div class="container">

        <!-- HOME -->
        <div id="home" class="page active">
            <div class="stat-grid">
                <div class="stat-card">
                    <h3>Total Players</h3>
                    <div class="value" id="cnt-players" data-target="{total_players}" style="color:#2ecc71;text-shadow:0 0 20px rgba(46,204,113,0.5);">0</div>
                    <div class="label">Active Members</div>
                </div>
                <div class="stat-card">
                    <h3>Activity Rate</h3>
                    <div class="value" id="cnt-activity" data-target="{activity_rate}" data-suffix="%" style="color:#74b9ff;text-shadow:0 0 20px rgba(116,185,255,0.5);">0%</div>
                    <div class="label">This week ({current_week})</div>
                </div>
                <div class="stat-card">
                    <h3>Perfect Streaks</h3>
                    <div class="value" id="cnt-streaks" data-target="{perfect_streak_count}" style="color:#ffd700;text-shadow:0 0 20px rgba(255,215,0,0.5);">0</div>
                    <div class="label">🔥 Perfect attendance</div>
                </div>
                <div class="stat-card">
                    <h3>Total SP Gained</h3>
                    <div class="value" id="cnt-sp" data-target="{total_sp_gained}" data-suffix=" SP" style="color:#e74c3c;text-shadow:0 0 20px rgba(231,76,60,0.5);">0 SP</div>
                    <div class="label">Combined this week</div>
                </div>
            </div>
            <div class="section">
                <h2>🏆 Top Performers This Week</h2>
                <ul class="top-performers">
{top_3_html}                </ul>
            </div>
            <div class="section">
                <h2>🔥 Streak Leaders</h2>
                <ul class="promotion-list">
{streak_html}                </ul>
            </div>
        </div>

        <!-- STATBOARD -->
        <div id="statboard" class="page">
            <div class="section">
                <h2>📊 Leaderboard - {current_week}</h2>
                <input type="text" class="search-box" id="searchBox" placeholder="🔍 Search players..." onkeyup="searchTable()">
                <table id="statsTable">
                    <thead>
                        <tr>
                            <th onclick="sortTable(0)">#</th>
                            <th onclick="sortTable(1)">Username</th>
                            <th>🎖️ Medals</th>
                            <th onclick="sortTable(3)">Level</th>
                            <th onclick="sortTable(4)">SP Rank</th>
                            <th onclick="sortTable(5)">SP</th>
                            <th onclick="sortTable(6)">Change</th>
                            <th onclick="sortTable(7)">Progress</th>
                            <th onclick="sortTable(8)">Streak</th>
                            <th onclick="sortTable(9)">Activity</th>
                        </tr>
                    </thead>
                    <tbody>
{statboard_rows}                    </tbody>
                </table>
            </div>
        </div>

        <!-- ACTIVITY -->
        <div id="activity" class="page">
            <div class="stat-grid">
                <div class="stat-card">
                    <h3>Perfect Streaks</h3>
                    <div class="value" style="color:#2ecc71">{perfect_streak_count}</div>
                    <div class="label">🔥 All weeks active</div>
                </div>
                <div class="stat-card">
                    <h3>Activity Rate</h3>
                    <div class="value" style="color:#74b9ff">{activity_rate}%</div>
                    <div class="label">This week ({current_week})</div>
                </div>
                <div class="stat-card">
                    <h3>Longest Streak</h3>
                    <div class="value" style="color:#ffd700">{max_streak_val}</div>
                    <div class="label">Weeks active</div>
                </div>
                <div class="stat-card">
                    <h3>Inactive Players</h3>
                    <div class="value">{inactive_count}</div>
                    <div class="label">💤 0 week streak</div>
                </div>
            </div>
            <div class="section">
                <h2>📅 Weekly Activity Heatmap</h2>
                <p class="section-sub" style="color:var(--text-muted);margin-bottom:0.8rem;font-size:0.85rem;">Each cell = one game week · Sorted by current streak · Hover for details</p>
                <p style="font-size:0.75rem;color:var(--text-muted);margin-bottom:1rem;">Showing {len(all_weeks)} weeks · Scroll right as more weeks are added</p>
                <div style="overflow-x:auto;">
                    <table class="hm-table">
                        <thead>
                            <tr>
                                <th class="hm-col-name">PLAYER</th>
                                {week_th_html}
                                <th class="hm-col-cur">CURRENT</th>
                                <th class="hm-col-best">BEST</th>
                                <th class="hm-col-stat">STATUS</th>
                            </tr>
                        </thead>
                        <tbody>
{activity_rows}                        </tbody>
                    </table>
                </div>
                <div style="display:flex;gap:1.5rem;margin-top:1rem;flex-wrap:wrap;">
                    <div style="display:flex;align-items:center;gap:0.5rem;font-size:0.78rem;color:var(--text-muted)"><div style="width:16px;height:16px;border-radius:4px;background:rgba(46,204,113,0.2);border:1px solid rgba(46,204,113,0.4)"></div>Active</div>
                    <div style="display:flex;align-items:center;gap:0.5rem;font-size:0.78rem;color:var(--text-muted)"><div style="width:16px;height:16px;border-radius:4px;background:rgba(231,76,60,0.15);border:1px solid rgba(231,76,60,0.3)"></div>Missed</div>
                    <div style="display:flex;align-items:center;gap:0.5rem;font-size:0.78rem;color:var(--text-muted)"><div style="width:16px;height:16px;border-radius:4px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07)"></div>Not in clan</div>
                </div>
            </div>
        </div>

        <!-- CHARTS -->
        <div id="charts" class="page">
            <div class="section">
                <h2>📈 SP Over Time</h2>
                <label for="playerSelectSP" style="display: block; margin-bottom: 0.5rem;">Select Player:</label>
                <select id="playerSelectSP" onchange="updateSPChart()">
{player_dropdown_sp}                </select>
                <div class="chart-container"><canvas id="chartSPOT"></canvas></div>
            </div>
            <div class="chart-grid">
                <div class="section">
                    <h2>📊 Clan Activity Rate</h2>
                    <div class="chart-container"><canvas id="chartCAROT"></canvas></div>
                </div>
                <div class="section">
                    <h2>📊 SP Rank Distribution</h2>
                    <div class="chart-container"><canvas id="chartSPDR"></canvas></div>
                </div>
            </div>
            <div class="section">
                <h2>🔥 Current Streak vs Best Streak</h2>
                <div class="chart-container"><canvas id="chartCSBS"></canvas></div>
            </div>
        </div>

        <!-- STORIES -->
        <div id="stories" class="page">
            <div class="section">
                <h2>📖 Player Stories</h2>
                <label for="playerSelectStory" style="display: block; margin-bottom: 0.5rem;">Select Player:</label>
                <select id="playerSelectStory" onchange="updateStory()">
{player_dropdown_story}                </select>
                <div id="storyDisplay" class="story-display"></div>
            </div>
        </div>

        <!-- EVENTS -->
        <div id="events" class="page">
            <div class="stat-grid">
                <div class="stat-card">
                    <h3>Total Events</h3>
                    <div class="value" style="color:#74b9ff">{total_ev_count}</div>
                    <div class="label">🎉 All time</div>
                </div>
                <div class="stat-card">
                    <h3>Total SP Awarded</h3>
                    <div class="value" style="color:#ffd700">{total_ev_sp}</div>
                    <div class="label">⭐ Across all events</div>
                </div>
                <div class="stat-card">
                    <h3>Total Cash Awarded</h3>
                    <div class="value" style="color:#2ecc71">{total_ev_cash:,}</div>
                    <div class="label">💰 Across all events</div>
                </div>
                <div class="stat-card">
                    <h3>Total Credits Awarded</h3>
                    <div class="value" style="color:#e74c3c">{total_ev_credits:,}</div>
                    <div class="label">💎 Across all events</div>
                </div>
            </div>
            <div class="section">
                <h2>🔴 Ongoing Events</h2>
                <p style="color:var(--text-muted);font-size:0.85rem;margin-bottom:1.5rem">Active competitions and challenges</p>
                <div class="tl-container">
{ongoing_cards_html}                </div>
            </div>
            <div class="section">
                <h2>📜 Event History</h2>
                <p style="color:var(--text-muted);font-size:0.85rem;margin-bottom:1.5rem">Click an event to see full details and results</p>
                <div class="tl-container">
{completed_cards_html}                </div>
            </div>
        </div>

        <!-- MEDALS OF HONOR -->
        <div id="medals" class="page">
            <div class="section">
                <h2>🎖️ Medals of Honor</h2>
                <p style="color:var(--muted);font-family:'Share Tech Mono',monospace;font-size:0.72rem;letter-spacing:2px;margin-bottom:2rem;text-transform:uppercase;">Earned by crossing performance thresholds — cash rewards paid once per tier</p>
{medals_page_html}            </div>
        </div>

        <!-- BEST WEEK -->
        <div id="bestweek" class="page">
            <div class="section" style="--blood:#ffd700;">
                <h2>🏆 Best Week — All-Time Records</h2>
                <div class="bw-tabs">
                    <button class="bw-tab active" onclick="bwSwitch(this,'ts')">⚔️ Top Survivor</button>
                    <button class="bw-tab" onclick="bwSwitch(this,'tpk')">💀 Total Kills</button>
                    <button class="bw-tab" onclick="bwSwitch(this,'tl')">📦 Total Loots</button>
                </div>
                <table class="bw-table">
                    <thead>
                        <tr>
                            <th style="width:60px">#</th>
                            <th>Player</th>
                            <th style="text-align:right">Week &nbsp;·&nbsp; Value</th>
                        </tr>
                    </thead>
                    <tbody id="bw-body-ts" style="display:table-row-group">
{bw_rows_ts}                    </tbody>
                    <tbody id="bw-body-tpk" style="display:none">
{bw_rows_tpk}                    </tbody>
                    <tbody id="bw-body-tl" style="display:none">
{bw_rows_tl}                    </tbody>
                </table>
                <div class="bw-note">// same player may appear multiple times · records set across all clan history</div>
            </div>
        </div>

        <!-- SIMULATOR -->
        <div id="simulator" class="page">
            <div class="section">
                <h2>⭐ SP Simulator</h2>
                <p style="margin-bottom:1.5rem; color:#8b949e;">Load your stats, then drag the weekly sliders to see how more activity changes your Star Points.</p>
                <div class="sim-load-bar">
                    <label>👤 Load Player:</label>
                    <select id="simPlayerSelect">
                        <option value="">— Select player —</option>
{player_dropdown_sim}                    </select>
                    <button class="sim-load-btn" onclick="simLoadPlayer()">Load My Stats</button>
                    <span class="sim-loaded-tag" id="simLoadedTag">✅ Stats loaded!</span>
                </div>
                <div class="sim-layout">
                    <div class="sim-left">
                        <div class="sim-block">
                            <h3><span class="sim-block-num">1</span> 📊 Weekly Activity <span class="sim-fixed-note">drag to simulate</span></h3>
                            <div class="sim-input-row">
                                <label>🏹 Weekly TS <span class="sim-val" id="simValTs">0</span> <span class="sim-cur" id="simCurTs"></span></label>
                                <input type="range" id="simSlTs" min="0" max="7000000000" step="1000000" value="0" oninput="simUpdate()">
                                <div class="sim-hint">Contributes to Clan SP via asymptotic TS Base formula</div>
                            </div>
                            <div class="sim-input-row">
                                <label>⚔️ Weekly TPK <span class="sim-val" id="simValTpk">0</span> <span class="sim-cur" id="simCurTpk"></span></label>
                                <input type="range" id="simSlTpk" min="0" max="70000" step="100" value="0" oninput="simUpdate()">
                                <div class="sim-hint">Contributes to Clan SP via asymptotic TPK Base formula</div>
                            </div>
                            <div class="sim-input-row">
                                <label>📦 Weekly Loots <span class="sim-val" id="simValTl">0</span> <span class="sim-cur" id="simCurTl"></span></label>
                                <input type="range" id="simSlTl" min="0" max="40000" step="100" value="0" oninput="simUpdate()">
                                <div class="sim-hint">Contributes to Clan SP via asymptotic Loots Base formula</div>
                            </div>
                        </div>
                        <div class="sim-block">
                            <h3><span class="sim-block-num">2</span> ⏳ All Time Stats <span class="sim-fixed-note">fixed from DB</span></h3>
                            <div class="sim-fixed-grid">
                                <div class="sim-fixed-item"><div class="sim-fi-label">Level</div><div class="sim-fi-value" id="simDispLevel">—</div><div class="sim-fi-sub" id="simDispLevelSp">—</div></div>
                                <div class="sim-fixed-item"><div class="sim-fi-label">All Time TS</div><div class="sim-fi-value" id="simDispAts">—</div><div class="sim-fi-sub" id="simDispAtsSp">—</div></div>
                                <div class="sim-fixed-item"><div class="sim-fi-label">All Time TPK</div><div class="sim-fi-value" id="simDispAtpk">—</div><div class="sim-fi-sub" id="simDispAtpkSp">—</div></div>
                                <div class="sim-fixed-item"><div class="sim-fi-label">All Time Loots</div><div class="sim-fi-value" id="simDispAtl">—</div><div class="sim-fi-sub" id="simDispAtlSp">—</div></div>
                            </div>
                        </div>
                        <div class="sim-block">
                            <h3><span class="sim-block-num">3</span> 🎉 Events SP <span class="sim-fixed-note">fixed from DB</span></h3>
                            <div class="sim-fixed-grid">
                                <div class="sim-fixed-item"><div class="sim-fi-label">Cumulative Events SP</div><div class="sim-fi-value" id="simDispEvents">—</div></div>
                                <div class="sim-fixed-item"><div class="sim-fi-label">SP Carryover</div><div class="sim-fi-value" id="simDispCarryover">—</div></div>
                            </div>
                        </div>
                        <div class="sim-block">
                            <h3><span class="sim-block-num">4</span> 🏆 Weekly Rankings <span class="sim-fixed-note">fixed from DB</span></h3>
                            <div class="sim-fixed-grid">
                                <div class="sim-fixed-item"><div class="sim-fi-label">TS Global Rank</div><div class="sim-fi-value" id="simDispTsRank">—</div><div class="sim-fi-sp" id="simDispTsRankSp">—</div></div>
                                <div class="sim-fixed-item"><div class="sim-fi-label">TPK Global Rank</div><div class="sim-fi-value" id="simDispTpkRank">—</div><div class="sim-fi-sp" id="simDispTpkRankSp">—</div></div>
                                <div class="sim-fixed-item"><div class="sim-fi-label">TL Global Rank</div><div class="sim-fi-value" id="simDispTlRank">—</div><div class="sim-fi-sp" id="simDispTlRankSp">—</div></div>
                                <div class="sim-fixed-item"><div class="sim-fi-label">Cum Weekly LB SP</div><div class="sim-fi-value" id="simDispCumWeekly">—</div></div>
                            </div>
                        </div>
                    </div>
                    <div class="sim-right">
                        <div class="sim-card">
                            <h4>⭐ Projected Total Star Points</h4>
                            <div class="sim-total-row">
                                <div class="sim-big" id="simTotalSp">—</div>
                                <div class="sim-change sim-zero" id="simChangeTag">+0.0</div>
                            </div>
                            <div class="sim-rank-line">Rank: <strong id="simRankName">—</strong></div>
                            <div class="sim-rank-line" id="simNextRank" style="margin-top:0.3rem;">—</div>
                            <div class="progress-bar-bg"><div class="progress-bar-fill" id="simRankProg" style="width:0%"></div></div>
                        </div>
                        <div class="sim-card blue">
                            <h4>🏰 This Week's Clan SP <span class="sim-mult" id="simMultBadge">—</span></h4>
                            <div class="sim-big" style="font-size:1.8rem;" id="simClanSp">—</div>
                            <div class="sim-mini-3">
                                <div class="sim-mini"><div class="sm-label">🏹 TS Base</div><div class="sm-val" id="simTsBase">—</div><div class="sm-delta" id="simTsBaseDelta"></div></div>
                                <div class="sim-mini"><div class="sm-label">⚔️ TPK Base</div><div class="sm-val" id="simTpkBase">—</div><div class="sm-delta" id="simTpkBaseDelta"></div></div>
                                <div class="sim-mini"><div class="sm-label">📦 TL Base</div><div class="sm-val" id="simTlBase">—</div><div class="sm-delta" id="simTlBaseDelta"></div></div>
                            </div>
                        </div>
                        <div class="sim-card orange">
                            <h4>📦 Accumulated SP (all weeks including current)</h4>
                            <div class="sim-big" style="font-size:1.8rem;" id="simAccumVal">—</div>
                            <div class="sim-mini-2">
                                <div class="sim-mini"><div class="sm-label">🏰 Cum Clan SP</div><div class="sm-val" id="simAccClan">—</div></div>
                                <div class="sim-mini"><div class="sm-label">⏳ All Time SP</div><div class="sm-val" id="simAccAlltime">—</div></div>
                                <div class="sim-mini"><div class="sm-label">🎉 Cum Events SP</div><div class="sm-val" id="simAccEvents">—</div></div>
                                <div class="sim-mini"><div class="sm-label">🏆 Cum Weekly LB</div><div class="sm-val" id="simAccWeekly">—</div></div>
                            </div>
                        </div>
                        <div class="sim-card purple">
                            <h4>📊 SP Composition</h4>
                            <div class="sim-bar-section">
                                <div class="sim-bar-row"><div class="sim-bar-label"><span>🏰 Cum Clan SP</span><span id="simPctClan">0%</span></div><div class="sim-bar-bg"><div class="sim-bar-f sb-clan" id="simBarClan" style="width:0%"></div></div></div>
                                <div class="sim-bar-row"><div class="sim-bar-label"><span>⏳ All Time SP</span><span id="simPctAlltime">0%</span></div><div class="sim-bar-bg"><div class="sim-bar-f sb-alltime" id="simBarAlltime" style="width:0%"></div></div></div>
                                <div class="sim-bar-row"><div class="sim-bar-label"><span>🎉 Events SP</span><span id="simPctEvents">0%</span></div><div class="sim-bar-bg"><div class="sim-bar-f sb-events" id="simBarEvents" style="width:0%"></div></div></div>
                                <div class="sim-bar-row"><div class="sim-bar-label"><span>🏆 Weekly LB SP</span><span id="simPctWeekly">0%</span></div><div class="sim-bar-bg"><div class="sim-bar-f sb-weekly" id="simBarWeekly" style="width:0%"></div></div></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- ARMORY -->
        <div id="armory" class="page">
            <style>
                .arm-tab {{ background:transparent;border:none;border-bottom:2px solid transparent;margin-bottom:-1px;color:var(--muted);font-family:'Rajdhani',sans-serif;font-size:13px;font-weight:700;letter-spacing:2px;text-transform:uppercase;padding:12px 28px;cursor:pointer;transition:all 0.2s; }}
                .arm-tab:hover {{ color:var(--text); }}
                .arm-tab.active {{ color:var(--blood-bright) !important; border-bottom-color:var(--blood-bright) !important; }}
                .arm-panel {{ display:none; }}
                .arm-panel.active {{ display:block; }}
                .arm-row {{ border-bottom:1px solid var(--border2); transition:background 0.12s; }}
                .arm-row:hover {{ background:var(--bg-hover); }}
                .arm-row.dimmed {{ opacity:0.38; }}
                .arm-img-cell {{ text-align:center; padding:8px 10px; background:var(--bg-deep); border-right:1px solid var(--border2); width:90px; vertical-align:middle; }}
                .arm-img-cell img {{ max-width:68px; max-height:50px; object-fit:contain; display:block; margin:0 auto; filter:drop-shadow(0 2px 6px rgba(0,0,0,0.9)); }}
                .arm-placeholder {{ width:68px; height:48px; background:var(--bg-card); border:1px dashed var(--border2); display:flex; align-items:center; justify-content:center; font-size:20px; margin:0 auto; color:var(--border); }}
                .arm-td {{ padding:12px 16px; vertical-align:middle; color:var(--text); font-family:'Rajdhani',sans-serif; }}
                .arm-name {{ font-weight:700; font-size:15px; color:var(--text); }}
                .arm-badge {{ font-size:11px; font-weight:700; letter-spacing:1.5px; text-transform:uppercase; padding:3px 10px; border:1px solid; display:inline-block; white-space:nowrap; font-family:'Share Tech Mono',monospace; }}
                .arm-badge.available {{ color:#52b788; border-color:#1f5c3a; background:rgba(31,92,58,0.12); }}
                .arm-badge.borrowed  {{ color:#e56b6f; border-color:#6b1e22; background:rgba(107,30,34,0.12); }}
                .arm-tags {{ display:flex; gap:4px; flex-wrap:wrap; }}
                .arm-tag {{ font-size:10px; font-weight:700; letter-spacing:1px; padding:2px 8px; text-transform:uppercase; border:1px solid; font-family:'Share Tech Mono',monospace; }}
                .arm-tag.looting  {{ color:#52b788; border-color:#1f5c3a; }}
                .arm-tag.grinding {{ color:#e9a44a; border-color:#7b4f1e; }}
                .arm-tag.pvp      {{ color:#e56b6f; border-color:#6b1e22; }}
                .arm-tag.cc       {{ color:#b8a0cc; border-color:#5a3d6e; }}
                .arm-rank {{ font-weight:700; font-size:12px; padding:2px 8px; border:1px solid; display:inline-block; letter-spacing:0.5px; }}
                .arm-rank.rk-scout        {{ background:rgba(100,200,100,0.15); color:#55efc4; border-color:rgba(100,200,100,0.3); }}
                .arm-rank.rk-apex-scout   {{ background:rgba(0,100,0,0.35);      color:#90ee90; border-color:#006400; }}
                .arm-rank.rk-ranger       {{ background:rgba(100,160,255,0.15);  color:#74b9ff; border-color:rgba(100,160,255,0.3); }}
                .arm-rank.rk-apex-ranger  {{ background:rgba(0,0,180,0.35);      color:#99bbff; border-color:#0000b4; }}
                .arm-rank.rk-templar      {{ background:rgba(200,50,50,0.2);     color:#ff8080; border-color:rgba(200,50,50,0.4); }}
                .arm-rank.rk-apex-templar {{ background:rgba(139,0,0,0.35);      color:#ff9999; border-color:#8b0000; }}
                .arm-rank.rk-officer      {{ background:rgba(255,220,80,0.15);   color:#ffe680; border-color:rgba(255,220,80,0.35); }}
                .arm-rank.rk-apex-officer {{ background:rgba(255,200,0,0.2);     color:#ffd700; border-color:rgba(255,200,0,0.45); }}
                .arm-rank.rk-axiom        {{ background:rgba(147,112,219,0.25);  color:#c9b8ff; border-color:rgba(147,112,219,0.5); }}
                .arm-rank.rk-other        {{ background:rgba(150,150,150,0.1);   color:#b2bec3; border-color:rgba(150,150,150,0.3); }}
                .arm-borrower {{ color:#e56b6f; font-weight:700; display:block; }}
                .arm-due {{ color:var(--muted); font-size:12px; font-family:'Share Tech Mono',monospace; }}
            </style>
            <div class="section">
                <h2>⚔️ Clan Armory</h2>
                <p class="section-sub" style="color:var(--text-muted);margin-bottom:1.4rem;font-size:0.85rem;">Clan item lending · Data synced live from Google Sheets</p>

                <div style="display:flex;border-bottom:1px solid rgba(192,57,43,0.35);margin-bottom:24px;">
                    <button class="arm-tab active" onclick="armorySwitch('weapons',this)">⚔️ Weapons</button>
                    <button class="arm-tab" onclick="armorySwitch('armor',this)">🛡️ Armor</button>
                    <button class="arm-tab" onclick="armorySwitch('implants',this)">💉 Implants</button>
                </div>

                <div id="arm-panel-weapons" class="arm-panel active">
                    <div style="display:flex;gap:12px;align-items:flex-end;margin-bottom:20px;flex-wrap:wrap;">
                        <div style="display:flex;flex-direction:column;gap:4px;">
                            <label style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);font-family:'Share Tech Mono',monospace;">Status</label>
                            <select id="aw-status" onchange="armoryFilter('weapons')" style="background:var(--bg-card);border:1px solid var(--border2);color:var(--text);font-family:'Rajdhani',sans-serif;font-size:14px;font-weight:600;padding:7px 32px 7px 14px;outline:none;cursor:pointer;appearance:none;-webkit-appearance:none;background-image:url('data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23666'/%3E%3C/svg%3E');background-repeat:no-repeat;background-position:right 10px center;min-width:150px;transition:border-color 0.15s;">
                                <option value="">All</option><option value="available">Available</option><option value="borrowed">Borrowed</option>
                            </select>
                        </div>
                        <div style="display:flex;flex-direction:column;gap:4px;">
                            <label style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);font-family:'Share Tech Mono',monospace;">Best For</label>
                            <select id="aw-use" onchange="armoryFilter('weapons')" style="background:var(--bg-card);border:1px solid var(--border2);color:var(--text);font-family:'Rajdhani',sans-serif;font-size:14px;font-weight:600;padding:7px 32px 7px 14px;outline:none;cursor:pointer;appearance:none;-webkit-appearance:none;background-image:url('data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23666'/%3E%3C/svg%3E');background-repeat:no-repeat;background-position:right 10px center;min-width:150px;transition:border-color 0.15s;">
                                <option value="">All</option><option value="looting">Looting</option><option value="grinding">Grinding</option><option value="pvp">PVP</option><option value="cc">CC</option>
                            </select>
                        </div>
                        <div style="display:flex;flex-direction:column;gap:4px;">
                            <label style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);font-family:'Share Tech Mono',monospace;">Min Rank</label>
                            <select id="aw-rank" onchange="armoryFilter('weapons')" style="background:var(--bg-card);border:1px solid var(--border2);color:var(--text);font-family:'Rajdhani',sans-serif;font-size:14px;font-weight:600;padding:7px 32px 7px 14px;outline:none;cursor:pointer;appearance:none;-webkit-appearance:none;background-image:url('data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23666'/%3E%3C/svg%3E');background-repeat:no-repeat;background-position:right 10px center;min-width:150px;transition:border-color 0.15s;">
                                <option value="">All</option>
                            </select>
                        </div>
                        <div style="display:flex;align-items:center;gap:12px;margin-left:auto;">
                            <span style="font-size:12px;color:var(--muted);letter-spacing:1px;font-family:'Share Tech Mono',monospace;">Showing <span id="aw-count" style="color:var(--blood-bright);">—</span> items</span>
                            <button onclick="armoryClear('weapons')" style="background:var(--bg-card);border:1px solid var(--border2);color:var(--muted);font-family:'Rajdhani',sans-serif;font-size:13px;font-weight:700;padding:7px 16px;cursor:pointer;letter-spacing:1px;text-transform:uppercase;transition:all 0.15s;" onmouseover="this.style.borderColor='var(--blood)';this.style.color='var(--text)'" onmouseout="this.style.borderColor='var(--border2)';this.style.color='var(--muted)'">✕ Clear</button>
                        </div>
                    </div>
                    <div style="overflow-x:auto;">
                        <table style="width:100%;border-collapse:collapse;">
                            <thead>
                                <tr style="border-top:1px solid rgba(192,57,43,0.4);border-bottom:1px solid rgba(192,57,43,0.4);background:rgba(192,57,43,0.25);">
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:center;width:90px;white-space:nowrap;">Image</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Name</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Status</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Best For</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Min Rank</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Borrowed By</th>
                                </tr>
                            </thead>
                            <tbody id="arm-body-weapons">
                                <tr><td colspan="6" style="text-align:center;padding:48px;color:var(--muted);font-family:'Share Tech Mono',monospace;letter-spacing:2px;font-size:12px;">Loading armory data...</td></tr>
                            </tbody>
                        </table>
                        <div id="arm-nr-weapons" style="display:none;text-align:center;padding:40px;color:var(--border);font-family:'Share Tech Mono',monospace;letter-spacing:2px;font-size:12px;text-transform:uppercase;">No items match your filters</div>
                    </div>
                </div>
                <div id="arm-panel-armor" class="arm-panel">
                    <div style="display:flex;gap:12px;align-items:flex-end;margin-bottom:20px;flex-wrap:wrap;">
                        <div style="display:flex;flex-direction:column;gap:4px;">
                            <label style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);font-family:'Share Tech Mono',monospace;">Status</label>
                            <select id="aa-status" onchange="armoryFilter('armor')" style="background:var(--bg-card);border:1px solid var(--border2);color:var(--text);font-family:'Rajdhani',sans-serif;font-size:14px;font-weight:600;padding:7px 32px 7px 14px;outline:none;cursor:pointer;appearance:none;-webkit-appearance:none;background-image:url('data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23666'/%3E%3C/svg%3E');background-repeat:no-repeat;background-position:right 10px center;min-width:150px;transition:border-color 0.15s;">
                                <option value="">All</option><option value="available">Available</option><option value="borrowed">Borrowed</option>
                            </select>
                        </div>
                        <div style="display:flex;flex-direction:column;gap:4px;">
                            <label style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);font-family:'Share Tech Mono',monospace;">Best For</label>
                            <select id="aa-use" onchange="armoryFilter('armor')" style="background:var(--bg-card);border:1px solid var(--border2);color:var(--text);font-family:'Rajdhani',sans-serif;font-size:14px;font-weight:600;padding:7px 32px 7px 14px;outline:none;cursor:pointer;appearance:none;-webkit-appearance:none;background-image:url('data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23666'/%3E%3C/svg%3E');background-repeat:no-repeat;background-position:right 10px center;min-width:150px;transition:border-color 0.15s;">
                                <option value="">All</option><option value="looting">Looting</option><option value="grinding">Grinding</option><option value="pvp">PVP</option><option value="cc">CC</option>
                            </select>
                        </div>
                        <div style="display:flex;flex-direction:column;gap:4px;">
                            <label style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);font-family:'Share Tech Mono',monospace;">Min Rank</label>
                            <select id="aa-rank" onchange="armoryFilter('armor')" style="background:var(--bg-card);border:1px solid var(--border2);color:var(--text);font-family:'Rajdhani',sans-serif;font-size:14px;font-weight:600;padding:7px 32px 7px 14px;outline:none;cursor:pointer;appearance:none;-webkit-appearance:none;background-image:url('data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23666'/%3E%3C/svg%3E');background-repeat:no-repeat;background-position:right 10px center;min-width:150px;transition:border-color 0.15s;">
                                <option value="">All</option>
                            </select>
                        </div>
                        <div style="display:flex;align-items:center;gap:12px;margin-left:auto;">
                            <span style="font-size:12px;color:var(--muted);letter-spacing:1px;font-family:'Share Tech Mono',monospace;">Showing <span id="aa-count" style="color:var(--blood-bright);">—</span> items</span>
                            <button onclick="armoryClear('armor')" style="background:var(--bg-card);border:1px solid var(--border2);color:var(--muted);font-family:'Rajdhani',sans-serif;font-size:13px;font-weight:700;padding:7px 16px;cursor:pointer;letter-spacing:1px;text-transform:uppercase;transition:all 0.15s;" onmouseover="this.style.borderColor='var(--blood)';this.style.color='var(--text)'" onmouseout="this.style.borderColor='var(--border2)';this.style.color='var(--muted)'">✕ Clear</button>
                        </div>
                    </div>
                    <div style="overflow-x:auto;">
                        <table style="width:100%;border-collapse:collapse;">
                            <thead>
                                <tr style="border-top:1px solid rgba(192,57,43,0.4);border-bottom:1px solid rgba(192,57,43,0.4);background:rgba(192,57,43,0.25);">
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:center;width:90px;white-space:nowrap;">Image</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Name</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Status</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Best For</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Min Rank</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Borrowed By</th>
                                </tr>
                            </thead>
                            <tbody id="arm-body-armor">
                                <tr><td colspan="6" style="text-align:center;padding:48px;color:var(--muted);font-family:'Share Tech Mono',monospace;letter-spacing:2px;font-size:12px;">Loading armory data...</td></tr>
                            </tbody>
                        </table>
                        <div id="arm-nr-armor" style="display:none;text-align:center;padding:40px;color:var(--border);font-family:'Share Tech Mono',monospace;letter-spacing:2px;font-size:12px;text-transform:uppercase;">No items match your filters</div>
                    </div>
                </div>
                <div id="arm-panel-implants" class="arm-panel">
                    <div style="display:flex;gap:12px;align-items:flex-end;margin-bottom:20px;flex-wrap:wrap;">
                        <div style="display:flex;flex-direction:column;gap:4px;">
                            <label style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);font-family:'Share Tech Mono',monospace;">Status</label>
                            <select id="ai-status" onchange="armoryFilter('implants')" style="background:var(--bg-card);border:1px solid var(--border2);color:var(--text);font-family:'Rajdhani',sans-serif;font-size:14px;font-weight:600;padding:7px 32px 7px 14px;outline:none;cursor:pointer;appearance:none;-webkit-appearance:none;background-image:url('data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23666'/%3E%3C/svg%3E');background-repeat:no-repeat;background-position:right 10px center;min-width:150px;transition:border-color 0.15s;">
                                <option value="">All</option><option value="available">Available</option><option value="borrowed">Borrowed</option>
                            </select>
                        </div>
                        <div style="display:flex;flex-direction:column;gap:4px;">
                            <label style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);font-family:'Share Tech Mono',monospace;">Best For</label>
                            <select id="ai-use" onchange="armoryFilter('implants')" style="background:var(--bg-card);border:1px solid var(--border2);color:var(--text);font-family:'Rajdhani',sans-serif;font-size:14px;font-weight:600;padding:7px 32px 7px 14px;outline:none;cursor:pointer;appearance:none;-webkit-appearance:none;background-image:url('data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23666'/%3E%3C/svg%3E');background-repeat:no-repeat;background-position:right 10px center;min-width:150px;transition:border-color 0.15s;">
                                <option value="">All</option><option value="looting">Looting</option><option value="grinding">Grinding</option><option value="pvp">PVP</option><option value="cc">CC</option>
                            </select>
                        </div>
                        <div style="display:flex;flex-direction:column;gap:4px;">
                            <label style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);font-family:'Share Tech Mono',monospace;">Min Rank</label>
                            <select id="ai-rank" onchange="armoryFilter('implants')" style="background:var(--bg-card);border:1px solid var(--border2);color:var(--text);font-family:'Rajdhani',sans-serif;font-size:14px;font-weight:600;padding:7px 32px 7px 14px;outline:none;cursor:pointer;appearance:none;-webkit-appearance:none;background-image:url('data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23666'/%3E%3C/svg%3E');background-repeat:no-repeat;background-position:right 10px center;min-width:150px;transition:border-color 0.15s;">
                                <option value="">All</option>
                            </select>
                        </div>
                        <div style="display:flex;align-items:center;gap:12px;margin-left:auto;">
                            <span style="font-size:12px;color:var(--muted);letter-spacing:1px;font-family:'Share Tech Mono',monospace;">Showing <span id="ai-count" style="color:var(--blood-bright);">—</span> items</span>
                            <button onclick="armoryClear('implants')" style="background:var(--bg-card);border:1px solid var(--border2);color:var(--muted);font-family:'Rajdhani',sans-serif;font-size:13px;font-weight:700;padding:7px 16px;cursor:pointer;letter-spacing:1px;text-transform:uppercase;transition:all 0.15s;" onmouseover="this.style.borderColor='var(--blood)';this.style.color='var(--text)'" onmouseout="this.style.borderColor='var(--border2)';this.style.color='var(--muted)'">✕ Clear</button>
                        </div>
                    </div>
                    <div style="overflow-x:auto;">
                        <table style="width:100%;border-collapse:collapse;">
                            <thead>
                                <tr style="border-top:1px solid rgba(192,57,43,0.4);border-bottom:1px solid rgba(192,57,43,0.4);background:rgba(192,57,43,0.25);">
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:center;width:90px;white-space:nowrap;">Image</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Name</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Status</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Best For</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Min Rank</th>
                                    <th style="font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:2px;color:#f0e6d3;text-transform:uppercase;padding:12px 16px;text-align:left;white-space:nowrap;">Borrowed By</th>
                                </tr>
                            </thead>
                            <tbody id="arm-body-implants">
                                <tr><td colspan="6" style="text-align:center;padding:48px;color:var(--muted);font-family:'Share Tech Mono',monospace;letter-spacing:2px;font-size:12px;">Loading armory data...</td></tr>
                            </tbody>
                        </table>
                        <div id="arm-nr-implants" style="display:none;text-align:center;padding:40px;color:var(--border);font-family:'Share Tech Mono',monospace;letter-spacing:2px;font-size:12px;text-transform:uppercase;">No items match your filters</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <div class="footer">Generated on {datetime.now().strftime('%B %d, %Y')} • A P E X Clan</div>

    <script>
        const chartData = {json.dumps(chart_data)};
        const simulatorData = {json.dumps(simulator_data)};
        const storiesData = {json.dumps(all_player_stories)};
        let spotChart = null;
        let chartsInitialized = false;

        document.addEventListener('DOMContentLoaded', function() {{
            const firstPlayer = Object.keys(chartData.all_players_sp)[0];
            if (firstPlayer) {{
                document.getElementById('playerSelectSP').value = firstPlayer;
                document.getElementById('playerSelectStory').value = firstPlayer;
                updateStory();
            }}
        }});

        function showPage(pageId, event) {{
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));
            document.getElementById(pageId).classList.add('active');
            if (event && event.target) event.target.classList.add('active');
            if (pageId === 'charts') setTimeout(initCharts, 100);
        }}

        function updateSPChart() {{
            const player = document.getElementById('playerSelectSP').value;
            const data = chartData.all_players_sp[player];
            if (!data) return;
            if (spotChart) spotChart.destroy();
            spotChart = new Chart(document.getElementById('chartSPOT'), {{
                type: 'line',
                data: {{
                    labels: data.weeks,
                    datasets: [{{ label: player + ' - Total SP', data: data.sp,
                        borderColor: '#e74c3c', backgroundColor: 'rgba(231,76,60,0.08)',
                        tension: 0, fill: true, borderWidth: 4,
                        pointRadius: 8, pointHoverRadius: 10,
                        pointBackgroundColor: '#fff', pointBorderColor: '#e74c3c', pointBorderWidth: 3 }}]
                }},
                options: {{ responsive: true, maintainAspectRatio: false,
                    plugins: {{ legend: {{ labels: {{ color: '#c9d1d9', font: {{ size: 16, weight: 'bold' }} }} }},
                        tooltip: {{ backgroundColor: 'rgba(231,76,60,0.95)', titleColor: '#fff', bodyColor: '#fff',
                            callbacks: {{ label: function(c) {{ return 'Total SP: ' + c.parsed.y.toFixed(1); }} }} }} }},
                    scales: {{ y: {{ beginAtZero: true, ticks: {{ color: '#8b949e' }}, grid: {{ color: 'rgba(255,255,255,0.06)' }} }},
                               x: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: 'rgba(255,255,255,0.06)' }} }} }} }}
            }});
        }}

        function updateStory() {{
            const player = document.getElementById('playerSelectStory').value;
            document.getElementById('storyDisplay').innerHTML = storiesData[player] || 'No story available.';
        }}

        function initCharts() {{
            if (chartsInitialized) return;
            updateSPChart();
            new Chart(document.getElementById('chartCAROT'), {{
                type: 'bar',
                data: {{ labels: chartData.carot.weeks,
                    datasets: [{{ label: 'Activity Rate %', data: chartData.carot.activity_rate,
                        backgroundColor: '#3498db', borderColor: '#2980b9', borderWidth: 2 }}] }},
                options: {{ responsive: true, maintainAspectRatio: false,
                    plugins: {{ legend: {{ labels: {{ color: '#c9d1d9' }} }} }},
                    scales: {{ y: {{ beginAtZero: true, max: 100, ticks: {{ color: '#8b949e' }}, grid: {{ color: 'rgba(255,255,255,0.06)' }} }},
                               x: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: 'rgba(255,255,255,0.06)' }} }} }} }}
            }});
            new Chart(document.getElementById('chartSPDR'), {{
                type: 'doughnut',
                data: {{ labels: chartData.spdr.ranks,
                    datasets: [{{ data: chartData.spdr.counts,
                        backgroundColor: chartData.spdr.ranks.map(r => {{
                            const map = {{
                                'Axiom':        '#c9b8ff',
                                'Apex Officer': '#ffd700',
                                'Officer':      '#ffe680',
                                'Apex Templar': '#ff9999',
                                'Templar':      '#ff8080',
                                'Apex Ranger':  '#99bbff',
                                'Ranger':       '#74b9ff',
                                'Apex Scout':   '#90ee90',
                                'Scout':        '#55efc4',
                            }};
                            return map[r] || '#8b949e';
                        }}),
                        borderWidth: 2, borderColor: '#161b22' }}] }},
                options: {{ responsive: true, maintainAspectRatio: false,
                    plugins: {{ legend: {{ position: 'right', labels: {{ color: '#c9d1d9' }} }} }} }}
            }});
            new Chart(document.getElementById('chartCSBS'), {{
                type: 'bar',
                data: {{ labels: chartData.csbs.current.map(d => d.user),
                    datasets: [
                        {{ label: 'Current Streak', data: chartData.csbs.current.map(d => d.value), backgroundColor: '#ff6b6b', borderColor: '#e74c3c', borderWidth: 2 }},
                        {{ label: 'Best Streak', data: chartData.csbs.best.map(d => d.value), backgroundColor: '#3498db', borderColor: '#2980b9', borderWidth: 2 }}
                    ] }},
                options: {{ responsive: true, maintainAspectRatio: false,
                    plugins: {{ legend: {{ labels: {{ color: '#c9d1d9' }} }} }},
                    scales: {{ y: {{ beginAtZero: true, ticks: {{ color: '#8b949e' }}, grid: {{ color: 'rgba(255,255,255,0.06)' }} }},
                               x: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: 'rgba(255,255,255,0.06)' }} }} }} }}
            }});
            chartsInitialized = true;
        }}

        function toggleBreakdown(rowId, iconId) {{
            const row = document.getElementById(rowId);
            const icon = document.getElementById(iconId);
            row.classList.toggle('open');
            icon.classList.toggle('open');
        }}

        function searchTable() {{
            const filter = document.getElementById('searchBox').value.toUpperCase();
            const tr = document.getElementById('statsTable').getElementsByTagName('tr');
            for (let i = 1; i < tr.length; i++) {{
                const td = tr[i].getElementsByTagName('td')[1];
                if (td) tr[i].style.display = td.textContent.toUpperCase().indexOf(filter) > -1 ? '' : 'none';
            }}
        }}

        function sortTable(colIndex) {{
            const table = document.getElementById('statsTable');
            const rows = Array.from(table.querySelectorAll('tbody tr'));
            const isNumeric = [0, 2, 4, 5, 7].includes(colIndex);
            rows.sort((a, b) => {{
                let aVal = a.cells[colIndex].textContent.trim();
                let bVal = b.cells[colIndex].textContent.trim();
                if (isNumeric) {{
                    aVal = parseFloat(aVal.replace(/[^0-9.-]/g, '')) || 0;
                    bVal = parseFloat(bVal.replace(/[^0-9.-]/g, '')) || 0;
                    return bVal - aVal;
                }}
                return aVal.localeCompare(bVal);
            }});
            const tbody = table.querySelector('tbody');
            rows.forEach(row => tbody.appendChild(row));
        }}

        // ── SIMULATOR ──
        let simLoaded = null;

        function simFmt(n) {{
            n = parseFloat(n) || 0;
            if (n >= 1000000000) return (n/1000000000).toFixed(1) + 'B';
            if (n >= 1000000)    return (n/1000000).toFixed(1) + 'M';
            if (n >= 1000)       return (n/1000).toFixed(1) + 'K';
            return Math.round(n).toString();
        }}

        const SIM_RANK_TABLE = [
            [0,   50,  'Scout',        50,   0],
            [50,  120, 'Apex Scout',   120,  50],
            [120, 200, 'Ranger',       200,  120],
            [200, 300, 'Apex Ranger',  300,  200],
            [300, 400, 'Templar',      400,  300],
            [400, Infinity, 'Apex Templar', null, 400],
        ];

        function simGetRank(sp) {{
            for (const [min, max, name, next, prev] of SIM_RANK_TABLE) {{
                if (sp >= min && sp < max) return {{ name, next, prev }};
            }}
            return {{ name: 'Apex Templar', next: null, prev: 400 }};
        }}

        function simRankStrToSP(rank) {{
            if (!rank || rank === '') return 0;
            const r = parseInt(String(rank).replace('#',''));
            if (r === 1)  return 50;
            if (r <= 5)   return 30;
            if (r <= 10)  return 20;
            if (r <= 25)  return 10;
            return 0;
        }}

        function simLoadPlayer() {{
            const username = document.getElementById('simPlayerSelect').value;
            if (!username) return;
            simLoaded = simulatorData[username];
            if (!simLoaded) return;

            document.getElementById('simSlTs').value  = simLoaded.weekly_ts;
            document.getElementById('simSlTpk').value = simLoaded.weekly_tpk;
            document.getElementById('simSlTl').value  = simLoaded.weekly_tl;

            document.getElementById('simCurTs').textContent  = '(now: ' + simFmt(simLoaded.weekly_ts) + ')';
            document.getElementById('simCurTpk').textContent = '(now: ' + simFmt(simLoaded.weekly_tpk) + ')';
            document.getElementById('simCurTl').textContent  = '(now: ' + simFmt(simLoaded.weekly_tl) + ')';

            document.getElementById('simDispLevel').textContent    = simLoaded.level;
            document.getElementById('simDispLevelSp').textContent  = simLoaded.level_sp.toFixed(2) + ' SP';
            document.getElementById('simDispAts').textContent      = simFmt(simLoaded.alltime_ts);
            document.getElementById('simDispAtsSp').textContent    = simLoaded.ats_base.toFixed(3) + ' SP';
            document.getElementById('simDispAtpk').textContent     = simFmt(simLoaded.alltime_tpk);
            document.getElementById('simDispAtpkSp').textContent   = simLoaded.atpk_base.toFixed(3) + ' SP';
            document.getElementById('simDispAtl').textContent      = simFmt(simLoaded.alltime_loots);
            document.getElementById('simDispAtlSp').textContent    = simLoaded.atl_base.toFixed(3) + ' SP';

            document.getElementById('simDispEvents').textContent    = simLoaded.cum_sp_events.toFixed(1);
            document.getElementById('simDispCarryover').textContent = simLoaded.sp_carryover.toFixed(1);

            const tsRankSP  = simRankStrToSP(simLoaded.ts_rank);
            const tpkRankSP = simRankStrToSP(simLoaded.tpk_rank);
            const tlRankSP  = simRankStrToSP(simLoaded.tl_rank);
            document.getElementById('simDispTsRank').textContent    = simLoaded.ts_rank  || 'Not ranked';
            document.getElementById('simDispTpkRank').textContent   = simLoaded.tpk_rank || 'Not ranked';
            document.getElementById('simDispTlRank').textContent    = simLoaded.tl_rank  || 'Not ranked';
            document.getElementById('simDispTsRankSp').textContent  = tsRankSP  > 0 ? '+' + tsRankSP  + ' SP earned' : '0 SP earned';
            document.getElementById('simDispTpkRankSp').textContent = tpkRankSP > 0 ? '+' + tpkRankSP + ' SP earned' : '0 SP earned';
            document.getElementById('simDispTlRankSp').textContent  = tlRankSP  > 0 ? '+' + tlRankSP  + ' SP earned' : '0 SP earned';
            document.getElementById('simDispCumWeekly').textContent = simLoaded.cum_sp_weekly.toFixed(1);

            document.getElementById('simLoadedTag').classList.add('show');
            simUpdate();
        }}

        function simUpdate() {{
            const ts  = parseFloat(document.getElementById('simSlTs').value)  || 0;
            const tpk = parseFloat(document.getElementById('simSlTpk').value) || 0;
            const tl  = parseFloat(document.getElementById('simSlTl').value)  || 0;

            document.getElementById('simValTs').textContent  = simFmt(ts);
            document.getElementById('simValTpk').textContent = simFmt(tpk);
            document.getElementById('simValTl').textContent  = simFmt(tl);

            if (!simLoaded) return;

            const ts_base  = ts  ? 20 * ts  / (ts  + 2000000000) : 0;
            const tpk_base = tpk ? 20 * tpk / (tpk + 12000)      : 0;
            const tl_base  = tl  ? 20 * tl  / (tl  + 8000)       : 0;

            const mult = simLoaded.sp_alltime < 60 ? 2 : (simLoaded.sp_alltime < 120 ? 1.5 : 1);
            const sim_clan_sp  = (ts_base + tpk_base + tl_base) * mult;
            const clan_delta   = sim_clan_sp - simLoaded.current_week_clan_sp;
            const sim_cum_clan = simLoaded.cum_sp_clan + clan_delta;

            const total   = sim_cum_clan + simLoaded.sp_alltime + simLoaded.cum_sp_events + simLoaded.cum_sp_weekly + simLoaded.sp_carryover;
            const base_sp = simLoaded.star_points - simLoaded.current_week_clan_sp;
            const change  = total - base_sp;

            const orig_ts  = simLoaded.weekly_ts  ? 20 * simLoaded.weekly_ts  / (simLoaded.weekly_ts  + 2000000000) : 0;
            const orig_tpk = simLoaded.weekly_tpk ? 20 * simLoaded.weekly_tpk / (simLoaded.weekly_tpk + 12000)      : 0;
            const orig_tl  = simLoaded.weekly_tl  ? 20 * simLoaded.weekly_tl  / (simLoaded.weekly_tl  + 8000)       : 0;

            document.getElementById('simTotalSp').textContent = total.toFixed(1);
            const ct = document.getElementById('simChangeTag');
            ct.textContent = (change >= 0 ? '+' : '') + change.toFixed(1);
            ct.className = 'sim-change ' + (change > 0.01 ? 'sim-pos' : (change < -0.01 ? 'sim-neg' : 'sim-zero'));

            const rank = simGetRank(total);
            document.getElementById('simRankName').textContent = rank.name;
            if (rank.next) {{
                document.getElementById('simNextRank').textContent = (rank.next - total).toFixed(1) + ' SP to next rank';
                const pct = Math.min(100, Math.round((total - rank.prev) / (rank.next - rank.prev) * 100));
                document.getElementById('simRankProg').style.width = pct + '%';
            }} else {{
                document.getElementById('simNextRank').textContent = 'Maximum rank reached!';
                document.getElementById('simRankProg').style.width = '100%';
            }}

            document.getElementById('simClanSp').textContent    = sim_clan_sp.toFixed(3) + ' SP';
            document.getElementById('simMultBadge').textContent = mult + 'x Multiplier';
            document.getElementById('simTsBase').textContent    = ts_base.toFixed(4);
            document.getElementById('simTpkBase').textContent   = tpk_base.toFixed(4);
            document.getElementById('simTlBase').textContent    = tl_base.toFixed(4);

            const showDelta = (id, sim, orig) => {{
                const d = sim - orig;
                const el = document.getElementById(id);
                el.textContent = d > 0.0001 ? '+' + d.toFixed(4) : (d < -0.0001 ? d.toFixed(4) : '');
                el.style.color = d > 0 ? '#27ae60' : '#e74c3c';
            }};
            showDelta('simTsBaseDelta',  ts_base,  orig_ts);
            showDelta('simTpkBaseDelta', tpk_base, orig_tpk);
            showDelta('simTlBaseDelta',  tl_base,  orig_tl);

            const accum = sim_cum_clan + simLoaded.sp_alltime + simLoaded.cum_sp_events + simLoaded.cum_sp_weekly + simLoaded.sp_carryover;
            document.getElementById('simAccumVal').textContent  = accum.toFixed(2) + ' SP';
            document.getElementById('simAccClan').textContent    = sim_cum_clan.toFixed(2);
            document.getElementById('simAccAlltime').textContent = simLoaded.sp_alltime.toFixed(2);
            document.getElementById('simAccEvents').textContent  = simLoaded.cum_sp_events.toFixed(1);
            document.getElementById('simAccWeekly').textContent  = simLoaded.cum_sp_weekly.toFixed(1);

            if (total > 0) {{
                const p = (v) => Math.round(v / total * 100);
                document.getElementById('simBarClan').style.width    = p(sim_cum_clan) + '%';
                document.getElementById('simBarAlltime').style.width = p(simLoaded.sp_alltime) + '%';
                document.getElementById('simBarEvents').style.width  = p(simLoaded.cum_sp_events) + '%';
                document.getElementById('simBarWeekly').style.width  = p(simLoaded.cum_sp_weekly) + '%';
                document.getElementById('simPctClan').textContent    = p(sim_cum_clan) + '%';
                document.getElementById('simPctAlltime').textContent = p(simLoaded.sp_alltime) + '%';
                document.getElementById('simPctEvents').textContent  = p(simLoaded.cum_sp_events) + '%';
                document.getElementById('simPctWeekly').textContent  = p(simLoaded.cum_sp_weekly) + '%';
            }}
        }}

        // ── Animated Counters ──
        function animateCounter(el, duration) {{
            const target   = parseFloat(el.dataset.target) || 0;
            const suffix   = el.dataset.suffix || '';
            const decimals = Number.isInteger(target) ? 0 : 1;
            const start    = performance.now();
            function tick(now) {{
                const progress = Math.min((now - start) / duration, 1);
                const ease     = 1 - Math.pow(1 - progress, 3);
                const val      = target * ease;
                el.textContent = (decimals ? val.toFixed(decimals) : Math.round(val)) + suffix;
                if (progress < 1) requestAnimationFrame(tick);
                else el.textContent = (decimals ? target.toFixed(decimals) : target) + suffix;
            }}
            requestAnimationFrame(tick);
        }}
        function runCounters() {{
            ['cnt-players','cnt-activity','cnt-streaks','cnt-sp'].forEach(id => {{
                const el = document.getElementById(id);
                if (el) animateCounter(el, 1200);
            }});
        }}
        // Run on page load and when switching to home tab
        window.addEventListener('DOMContentLoaded', () => setTimeout(runCounters, 100));
        const _origShowPage = showPage;
        let _armoryLoaded = false;
        showPage = function(page, evt) {{
            _origShowPage(page, evt);
            if (page === 'home') setTimeout(runCounters, 100);
            if (page === 'armory' && !_armoryLoaded) {{ _armoryLoaded = true; loadArmory(); }}
        }};

        function toggleTL(expandId, chevId) {{
            const el   = document.getElementById(expandId);
            const chev = document.getElementById(chevId);
            const open = el.style.display === 'block';
            el.style.display = open ? 'none' : 'block';
            chev.classList.toggle('open', !open);
        }}

        // ═══════════════ BEST WEEK ═══════════════
        function bwSwitch(el, cat) {{
            document.querySelectorAll('.bw-tab').forEach(t => t.classList.remove('active'));
            el.classList.add('active');
            ['ts','tpk','tl'].forEach(c => {{
                document.getElementById('bw-body-' + c).style.display = c === cat ? 'table-row-group' : 'none';
            }});
        }}
        // ═══════════════ END BEST WEEK ═══════════════

        function toggleTheme() {{
            const body = document.body;
            const btn  = document.getElementById('themeToggle');
            if (body.classList.contains('light-mode')) {{
                body.classList.remove('light-mode');
                btn.textContent = '☀️ Light';
                localStorage.setItem('apex-theme', 'dark');
            }} else {{
                body.classList.add('light-mode');
                btn.textContent = '🌙 Dark';
                localStorage.setItem('apex-theme', 'light');
            }}
        }}
        // Restore saved theme
        if (localStorage.getItem('apex-theme') === 'light') {{
            document.body.classList.add('light-mode');
            document.getElementById('themeToggle').textContent = '🌙 Dark';
        }}

        // ═══════════════ ARMORY ═══════════════
        const ARMORY_SHEET_ID = '1BJKCAruFvG4Q8gGpo1VMequJwAjthupQO9Ne-FexKw0';
        const ARMORY_API_KEY  = 'AIzaSyBDvRWyiTU_bFxgCRLBQQ4NOoL9FPPXJT8';
        const ARMORY_TAB      = 'Sheet1';
        // Column indices (0-based): img=0, name=1, status=2, looting=3, grinding=4, pvp=5, cc=6, borrowedBy=7, borrowingDate=8, dueDate=9, donatedBy=10, rank=11
        const ACOL = {{img:2,name:3,status:4,looting:5,grinding:6,pvp:7,cc:8,borrowedBy:10,dueDate:12,rank:15}};
        const armoryData = {{weapons:[],armor:[],implants:[]}};
        const armoryPfx  = {{weapons:'aw',armor:'aa',implants:'ai'}};

        async function loadArmory() {{
            try {{
                const url = `https://sheets.googleapis.com/v4/spreadsheets/${{ARMORY_SHEET_ID}}/values/${{ARMORY_TAB}}?key=${{ARMORY_API_KEY}}`;
                const res  = await fetch(url);
                const json = await res.json();
                if (!json.values) {{ armoryError(); return; }}
                let sec = null;
                for (const row of json.values) {{
                    // Check any cell in the row for section markers
                    const rowStr = row.join('|').toLowerCase();
                    const c0 = (row[0]||'').toString().trim().toLowerCase();
                    const c1 = (row[1]||'').toString().trim().toLowerCase();
                    const isWeaponHeader  = c0.includes('weapon')  || c1.includes('weapon');
                    const isArmorHeader   = c0.includes('armor')   || c1.includes('armor');
                    const isImplantHeader = c0.includes('implant') || c1.includes('implant');
                    if (isWeaponHeader && !c1.includes('name'))  {{ sec='weapons';  continue; }}
                    if (isArmorHeader  && !c1.includes('name'))  {{ sec='armor';    continue; }}
                    if (isImplantHeader && !c1.includes('name')) {{ sec='implants'; continue; }}
                    if (!sec) continue;
                    const nm = (row[ACOL.name]||'').toString().trim();
                    const st = (row[ACOL.status]||'').toString().trim().toLowerCase();
                    if (!nm || !st || nm.toLowerCase().includes('name') || nm.toLowerCase()==='column 3') continue;
                    armoryData[sec].push({{
                        img:       (row[ACOL.img]||'').toString().trim(),
                        name:      nm,
                        status:    st.includes('available') ? 'available' : 'borrowed',
                        looting:   (row[ACOL.looting]||'').toString().trim().toUpperCase()==='TRUE',
                        grinding:  (row[ACOL.grinding]||'').toString().trim().toUpperCase()==='TRUE',
                        pvp:       (row[ACOL.pvp]||'').toString().trim().toUpperCase()==='TRUE',
                        cc:        (row[ACOL.cc]||'').toString().trim().toUpperCase()==='TRUE',
                        borrowedBy:(row[ACOL.borrowedBy]||'').toString().trim(),
                        dueDate:   (row[ACOL.dueDate]||'').toString().trim(),
                        rank:      (row[ACOL.rank]||'').toString().trim(),
                    }});
                }}
                ['weapons','armor','implants'].forEach(s => {{ populateArmoryRanks(s); renderArmory(s); }});
            }} catch(e) {{ armoryError(); console.error('Armory error:',e); }}
        }}

        function armoryError() {{
            ['weapons','armor','implants'].forEach(s => {{
                document.getElementById('arm-body-'+s).innerHTML =
                    '<tr><td colspan="6" style="text-align:center;padding:40px;color:#e56b6f;font-family:ShareTechMono,monospace;letter-spacing:2px;font-size:12px;">⚠ Could not load armory data. Check API key and sheet permissions.</td></tr>';
            }});
        }}

        function populateArmoryRanks(sec) {{
            const sel = document.getElementById(armoryPfx[sec]+'-rank');
            const ranks = [...new Set(armoryData[sec].map(i=>i.rank).filter(Boolean))];
            ranks.forEach(r => {{ const o=document.createElement('option'); o.value=r; o.textContent=r; sel.appendChild(o); }});
        }}

        function getRankClass(rank) {{
            const r = (rank||'').toLowerCase();
            if (r.includes('axiom'))        return 'rk-axiom';
            if (r.includes('apex officer')) return 'rk-apex-officer';
            if (r.includes('officer'))      return 'rk-officer';
            if (r.includes('apex templar')) return 'rk-apex-templar';
            if (r.includes('templar'))      return 'rk-templar';
            if (r.includes('apex ranger'))  return 'rk-apex-ranger';
            if (r.includes('ranger'))       return 'rk-ranger';
            if (r.includes('apex scout'))   return 'rk-apex-scout';
            if (r.includes('scout'))        return 'rk-scout';
            return 'rk-other';
        }}
        function renderArmory(sec, sf='', uf='', rf='') {{
            const pfx = armoryPfx[sec];
            let html='', count=0;
            for (const item of armoryData[sec]) {{
                const tags=[];
                if(item.looting)  tags.push('looting');
                if(item.grinding) tags.push('grinding');
                if(item.pvp)      tags.push('pvp');
                if(item.cc)       tags.push('cc');
                if (sf && item.status!==sf) continue;
                if (uf && !tags.includes(uf)) continue;
                if (rf && item.rank!==rf) continue;
                count++;
                const imgHtml = item.img
                    ? `<img src="${{item.img}}" alt="${{item.name}}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
                    + `<div class="arm-placeholder" style="display:none">?</div>`
                    : `<div class="arm-placeholder">?</div>`;
                const tagsHtml = tags.map(t=>`<span class="arm-tag ${{t}}">${{t}}</span>`).join('') || '—';
                const borHtml  = item.status==='borrowed' && item.borrowedBy
                    ? `<span class="arm-borrower">${{item.borrowedBy}}</span>${{item.dueDate?`<span class="arm-due">Due: ${{item.dueDate}}</span>`:''}}` : '—';
                html += `<tr class="arm-row${{item.status==='borrowed' ? ' dimmed' : ''}}">
                    <td class="arm-img-cell">${{imgHtml}}</td>
                    <td class="arm-td"><span class="arm-name">${{item.name}}</span></td>
                    <td class="arm-td"><span class="arm-badge ${{item.status}}">${{item.status==='available'?'Available':'Borrowed'}}</span></td>
                    <td class="arm-td"><div class="arm-tags">${{tagsHtml}}</div></td>
                    <td class="arm-td">${{item.rank ? `<span class="arm-rank ${{getRankClass(item.rank)}}">${{item.rank}}</span>` : '—'}}</td>
                    <td class="arm-td">${{borHtml}}</td>
                </tr>`;
            }}
            document.getElementById('arm-body-'+sec).innerHTML = html || '<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--muted);font-family:monospace;font-size:12px;">—</td></tr>';
            document.getElementById(pfx+'-count').textContent = count;
            document.getElementById('arm-nr-'+sec).style.display = count===0 ? 'block' : 'none';
        }}

        function armoryFilter(sec) {{
            const p=armoryPfx[sec];
            renderArmory(sec, document.getElementById(p+'-status').value, document.getElementById(p+'-use').value, document.getElementById(p+'-rank').value);
        }}
        function armoryClear(sec) {{
            const p=armoryPfx[sec];
            document.getElementById(p+'-status').value='';
            document.getElementById(p+'-use').value='';
            document.getElementById(p+'-rank').value='';
            renderArmory(sec);
        }}
        function armorySwitch(name, btn) {{
            document.querySelectorAll('.arm-tab').forEach(t=>{{t.classList.remove('active');t.style.color='';t.style.borderBottomColor='';}});
            document.querySelectorAll('.arm-panel').forEach(p=>{{p.classList.remove('active');p.style.display='none';}});
            btn.classList.add('active');
            document.getElementById('arm-panel-'+name).classList.add('active');
            document.getElementById('arm-panel-'+name).style.display='block';
        }}
        // ═══════════════ END ARMORY ═══════════════
    </script>
    <script>
{chart_js_inline}
    </script>
</body>
</html>'''

with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    f.write(html_content)

print(f"\n{'=' * 70}")
print("✅ SUCCESS!")
print(f"{'=' * 70}")
print(f"📊 {total_players} players processed")
print(f"🌐 Output: {OUTPUT_FILE}")
print(f"{'=' * 70}")

