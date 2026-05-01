"""
APEX CLAN - SP Calculator v3
Reads weekly_snapshots → computes all SP/activity/streak/rank logic → writes to weekly_analysis
"""

import sqlite3
from collections import defaultdict
from datetime import datetime

DB_FILE = "apex_clan_v3.db"

print("=" * 70)
print("⚙️  APEX CLAN - SP CALCULATOR v3")
print("=" * 70)

# ===== RANK TABLES =====
RANK_TABLE = [
    (0,   50,  'Scout'),
    (50,  120, 'Apex Scout'),
    (120, 200, 'Ranger'),
    (200, 300, 'Apex Ranger'),
    (300, 400, 'Templar'),
    (400, float('inf'), 'Apex Templar'),
]

# Players with these in-game ranks retain them as their SP rank directly
BYPASS_RANKS = {'Axiom', 'Apex Officer', 'Officer'}

def get_sp_rank(star_points, game_rank):
    if game_rank in BYPASS_RANKS:
        return game_rank
    for min_sp, max_sp, rank_name in RANK_TABLE:
        if min_sp <= star_points < max_sp:
            return rank_name
    return 'Scout'

def rank_str_to_sp(rank_str):
    """Convert rank string like '#3' to SP points"""
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

def safe_int(val, default=0):
    if val is None or val == '':
        return default
    try:
        return int(float(val))
    except:
        return default

def safe_float(val, default=0):
    if val is None or val == '':
        return default
    try:
        return float(val)
    except:
        return default

def calculate_activity_status(recent_activity):
    """recent_activity = list of is_active values most recent first, up to 4"""
    not_in_clan = recent_activity.count('🚫')
    active = recent_activity.count('✓')
    missed = recent_activity.count('✗')
    valid = active + missed
    if not_in_clan == 4:
        return "❌ Left >1 Month"
    if recent_activity and recent_activity[0] == '🚫' and not_in_clan < 4:
        return "🚫 Not in Clan"
    if valid == 0:
        return "❌ Inactive (0/0)"
    if active == valid:
        return f"🔥 Perfect ({active}/{valid})"
    if active / valid >= 0.75:
        return f"✅ Active ({active}/{valid})"
    if active / valid >= 0.5:
        return f"⚠️ Spotty ({active}/{valid})"
    if active >= 1:
        return f"🟡 At Risk ({active}/{valid})"
    return f"❌ Inactive (0/{valid})"

# ===== CONNECT =====
conn = sqlite3.connect(DB_FILE)
conn.row_factory = sqlite3.Row

# ===== LOAD DATA =====
print("📂 Loading data from weekly_snapshots...")

all_weeks = [r[0] for r in conn.execute(
    "SELECT DISTINCT week FROM weekly_snapshots ORDER BY week ASC"
).fetchall()]
all_usernames = [r[0] for r in conn.execute(
    "SELECT DISTINCT username FROM weekly_snapshots ORDER BY username ASC"
).fetchall()]

# Load event rewards into a map: (week, username) → total sp
event_map = defaultdict(float)
for er in conn.execute("SELECT week, username, sp_awarded FROM event_rewards").fetchall():
    event_map[(er['week'], er['username'])] += safe_float(er['sp_awarded'])

# Load existing sp_carryover values so we don't overwrite manual entries
carryover_map = {}
for r in conn.execute("SELECT week, username, sp_carryover FROM weekly_analysis").fetchall():
    carryover_map[(r['week'], r['username'])] = safe_float(r['sp_carryover'])

print(f"  Weeks: {len(all_weeks)} | Players: {len(all_usernames)}")

# ===== COMPUTE PER PLAYER =====
print("⚙️  Computing SP calculations...")

analysis_records = []

for username in all_usernames:
    player_rows = conn.execute("""
        SELECT * FROM weekly_snapshots
        WHERE username = ?
        ORDER BY week ASC
    """, (username,)).fetchall()

    # Running accumulators
    cum_sp_clan    = 0.0
    cum_sp_events  = 0.0
    cum_sp_weekly  = 0.0
    prev_ats       = 0
    prev_atpk      = 0
    prev_atl       = 0
    prev_sp_rank   = None
    prev_star_points = 0.0
    current_streak = 0
    best_streak    = 0
    best_ts        = 0
    best_tpk       = 0
    best_tl        = 0
    week_number    = 0

    for snap in player_rows:
        week_number += 1
        week          = snap['week']
        level         = safe_int(snap['level'])
        weekly_ts     = safe_int(snap['weekly_ts'])
        weekly_tpk    = safe_int(snap['weekly_tpk'])
        weekly_loots  = safe_int(snap['weekly_loots'])
        alltime_ts    = safe_int(snap['alltime_ts'])
        alltime_tpk   = safe_int(snap['alltime_tpk'])
        alltime_loots = safe_int(snap['alltime_loots'])
        game_rank     = snap['rank'] or ''
        ts_rank_str   = snap['weekly_ts_rank'] or ''
        tpk_rank_str  = snap['weekly_tpk_rank'] or ''
        tl_rank_str   = snap['weekly_tl_rank'] or ''

        # ── Base Scores ──
        level_sp        = round(100 * level / 415, 6)           if level        else 0.0
        weekly_ts_base  = round(20  * weekly_ts   / (weekly_ts   + 2_000_000_000), 6) if weekly_ts   else 0.0
        weekly_tpk_base = round(20  * weekly_tpk  / (weekly_tpk  + 12_000),        6) if weekly_tpk  else 0.0
        weekly_tl_base  = round(20  * weekly_loots / (weekly_loots + 8_000),        6) if weekly_loots else 0.0
        alltime_ts_base  = round(100 * alltime_ts   / (alltime_ts   + 30_000_000_000), 6) if alltime_ts   else 0.0
        alltime_tpk_base = round(100 * alltime_tpk  / (alltime_tpk  + 600_000),        6) if alltime_tpk  else 0.0
        alltime_tl_base  = round(100 * alltime_loots / (alltime_loots + 400_000),        6) if alltime_loots else 0.0

        # ── Activity ──
        is_active  = '✓' if (alltime_tpk - prev_atpk) + (alltime_loots - prev_atl) > 0 else '✗'
        cons_active = 1 if is_active == '✓' else 0
        if is_active == '✓':
            current_streak += 1
            best_streak = max(best_streak, current_streak)
        else:
            current_streak = 0

        # ── SP All Time ──
        sp_alltime = round(level_sp + alltime_ts_base + alltime_tpk_base + alltime_tl_base, 6)

        # ── SP Clan ──
        sp_clan_multiplier = 2.0 if sp_alltime < 60 else (1.5 if sp_alltime < 120 else 1.0)
        sp_clan     = round((weekly_ts_base + weekly_tpk_base + weekly_tl_base) * sp_clan_multiplier, 6)
        cum_sp_clan = round(cum_sp_clan + sp_clan, 6)

        # ── SP Events ──
        sp_events     = safe_float(event_map.get((week, username), 0))
        cum_sp_events = round(cum_sp_events + sp_events, 6)

        # ── SP Weekly (leaderboard) ──
        sp_weekly     = rank_str_to_sp(ts_rank_str) + rank_str_to_sp(tpk_rank_str) + rank_str_to_sp(tl_rank_str)
        cum_sp_weekly = round(cum_sp_weekly + sp_weekly, 6)

        # ── SP Carryover (preserve manual entries) ──
        sp_carryover = carryover_map.get((week, username), 0.0)

        # ── Star Points ──
        star_points = round(cum_sp_clan + sp_alltime + cum_sp_events + cum_sp_weekly + sp_carryover, 6)

        # ── SP Change ──
        sp_change = round(star_points - prev_star_points, 6)

        # ── SP Rank ──
        sp_rank    = get_sp_rank(star_points, game_rank)
        is_promoted = 1 if (prev_sp_rank is not None and sp_rank != prev_sp_rank) else 0

        # ── Personal Bests ──
        ts_pb  = 1 if weekly_ts     > best_ts  else 0
        tpk_pb = 1 if weekly_tpk    > best_tpk else 0
        tl_pb  = 1 if weekly_loots  > best_tl  else 0
        if ts_pb:  best_ts  = weekly_ts
        if tpk_pb: best_tpk = weekly_tpk
        if tl_pb:  best_tl  = weekly_loots

        analysis_records.append({
            'week':             week,
            'username':         username,
            'prev_ats':         prev_ats,
            'prev_atpk':        prev_atpk,
            'prev_atl':         prev_atl,
            'is_active':        is_active,
            'cons_active':      cons_active,
            'level_sp':         level_sp,
            'weekly_ts_base':   weekly_ts_base,
            'weekly_tpk_base':  weekly_tpk_base,
            'weekly_tl_base':   weekly_tl_base,
            'alltime_ts_base':  alltime_ts_base,
            'alltime_tpk_base': alltime_tpk_base,
            'alltime_tl_base':  alltime_tl_base,
            'sp_clan_multiplier': sp_clan_multiplier,
            'sp_clan':          sp_clan,
            'cum_sp_clan':      cum_sp_clan,
            'sp_alltime':       sp_alltime,
            'sp_events':        sp_events,
            'cum_sp_events':    cum_sp_events,
            'sp_weekly':        sp_weekly,
            'cum_sp_weekly':    cum_sp_weekly,
            'sp_carryover':     sp_carryover,
            'star_points':      star_points,
            'current_streak':   current_streak,
            'best_streak':      best_streak,
            'sp_rank':          sp_rank,
            'sp_rank_prev':     prev_sp_rank or '',
            'sp_change':        sp_change,
            'best_weekly_ts':   best_ts,
            'best_weekly_tpk':  best_tpk,
            'best_weekly_tl':   best_tl,
            'activity_status':  '',       # filled below
            'week_number':      week_number,
            'ts_pb':            ts_pb,
            'tpk_pb':           tpk_pb,
            'tl_pb':            tl_pb,
            'ts_clan_rank':     None,     # filled below
            'tpk_clan_rank':    None,
            'tl_clan_rank':     None,
            'is_promoted':      is_promoted,
            # internal only — raw weekly stats for clan rank computation
            '_weekly_ts':    weekly_ts,
            '_weekly_tpk':   weekly_tpk,
            '_weekly_loots': weekly_loots,
        })

        # Update rolling values for next week
        prev_ats         = alltime_ts
        prev_atpk        = alltime_tpk
        prev_atl         = alltime_loots
        prev_sp_rank     = sp_rank
        prev_star_points = star_points

# ── Clan Ranks per week (position within clan for TS/TPK/TL) ──
week_groups = defaultdict(list)
for r in analysis_records:
    week_groups[r['week']].append(r)

for week, records in week_groups.items():
    for stat_key, col_key in [
        ('_weekly_ts',    'ts_clan_rank'),
        ('_weekly_tpk',   'tpk_clan_rank'),
        ('_weekly_loots', 'tl_clan_rank'),
    ]:
        sorted_recs = sorted(records, key=lambda x: x[stat_key], reverse=True)
        for i, rec in enumerate(sorted_recs):
            rec[col_key] = i + 1

# ── Activity Status (last 4 weeks per player at each week point) ──
player_history = defaultdict(list)
for r in analysis_records:
    player_history[r['username']].append(r)

for username, records in player_history.items():
    # Records are already in week order (oldest first)
    for i, rec in enumerate(records):
        # Take up to 4 most recent weeks up to and including this one
        recent = records[max(0, i - 3): i + 1][::-1]  # reverse to most recent first
        activity_vals = [x['is_active'] for x in recent]
        # Pad with '🚫' if fewer than 4 weeks
        while len(activity_vals) < 4:
            activity_vals.append('🚫')
        rec['activity_status'] = calculate_activity_status(activity_vals)

# ===== WRITE TO weekly_analysis =====
print("💾 Writing to weekly_analysis...")

for r in analysis_records:
    conn.execute("""
        INSERT OR REPLACE INTO weekly_analysis (
            week, username,
            prev_ats, prev_atpk, prev_atl,
            is_active, cons_active,
            level_sp, weekly_ts_base, weekly_tpk_base, weekly_tl_base,
            alltime_ts_base, alltime_tpk_base, alltime_tl_base,
            sp_clan_multiplier, sp_clan, cum_sp_clan,
            sp_alltime, sp_events, cum_sp_events,
            sp_weekly, sp_carryover, cum_sp_weekly, star_points,
            current_streak, best_streak,
            sp_rank, sp_rank_prev, sp_change,
            best_weekly_ts, best_weekly_tpk, best_weekly_tl,
            activity_status, week_number,
            ts_pb, tpk_pb, tl_pb,
            ts_clan_rank, tpk_clan_rank, tl_clan_rank,
            is_promoted
        ) VALUES (
            :week, :username,
            :prev_ats, :prev_atpk, :prev_atl,
            :is_active, :cons_active,
            :level_sp, :weekly_ts_base, :weekly_tpk_base, :weekly_tl_base,
            :alltime_ts_base, :alltime_tpk_base, :alltime_tl_base,
            :sp_clan_multiplier, :sp_clan, :cum_sp_clan,
            :sp_alltime, :sp_events, :cum_sp_events,
            :sp_weekly, :sp_carryover, :cum_sp_weekly, :star_points,
            :current_streak, :best_streak,
            :sp_rank, :sp_rank_prev, :sp_change,
            :best_weekly_ts, :best_weekly_tpk, :best_weekly_tl,
            :activity_status, :week_number,
            :ts_pb, :tpk_pb, :tl_pb,
            :ts_clan_rank, :tpk_clan_rank, :tl_clan_rank,
            :is_promoted
        )
    """, {k: v for k, v in r.items() if not k.startswith('_')})

conn.commit()
conn.close()

print(f"  ✅ Written {len(analysis_records)} records to weekly_analysis")
print(f"\n{'=' * 70}")
print("✅ SUCCESS")
print(f"{'=' * 70}")
