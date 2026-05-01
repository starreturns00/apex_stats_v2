#!/usr/bin/env python3
"""
APEX Clan Tracker v3
Features:
- Week-by-week breakdown
- Stores Weekly TS/TPK/Loots snapshots to SQLite database
- Same-week rerun: per-member upsert instead of stopping
- Tracks Day Joined / Day Left per member
- Game-week aligned to Monday 12:10 UTC reset

Scraping: requests + BeautifulSoup (no browser required)
"""

import time
import sqlite3
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

DB_FILE = "apex_clan_v3.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
}

class ApexTrackerV3:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.url = "https://www.dfprofiler.com/clan/view/2194"
        self.current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.current_week = self.get_game_week()

    # ─────────────────────────────────────────────
    # GAME WEEK
    # ─────────────────────────────────────────────
    def get_game_week(self):
        """
        Calculate the current game week ID based on the game's weekly reset.
        The game resets every Monday between 12:00-12:10 PM UTC.
        We use 12:10 PM UTC as the safe anchor.
        Returns a string like '2026-GW08'.
        """
        now = datetime.now(timezone.utc)
        reset_time = now.replace(hour=12, minute=0, second=0, microsecond=0)
        days_since_monday = now.weekday()
        last_reset = reset_time - timedelta(days=days_since_monday)
        if now < last_reset:
            last_reset -= timedelta(weeks=1)
        iso = last_reset.isocalendar()
        game_week = f"{iso[0]}-GW{iso[1]:02d}"
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Game week: {game_week} (reset anchor: {last_reset.strftime('%Y-%m-%d %H:%M UTC')})")
        return game_week

    # ─────────────────────────────────────────────
    # DATABASE
    # ─────────────────────────────────────────────
    def get_connection(self):
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn

    def get_all_known_usernames(self, conn):
        rows = conn.execute("SELECT DISTINCT username FROM weekly_snapshots").fetchall()
        return set(r[0] for r in rows)

    def get_current_week_usernames(self, conn):
        rows = conn.execute(
            "SELECT username FROM weekly_snapshots WHERE week = ?",
            (self.current_week,)
        ).fetchall()
        return set(r[0] for r in rows)

    def get_prev_week_usernames(self, conn):
        row = conn.execute(
            "SELECT week FROM weekly_snapshots WHERE week != ? ORDER BY week DESC LIMIT 1",
            (self.current_week,)
        ).fetchone()
        if not row:
            return set()
        prev_week = row[0]
        rows = conn.execute(
            "SELECT username FROM weekly_snapshots WHERE week = ?",
            (prev_week,)
        ).fetchall()
        return set(r[0] for r in rows)

    # ─────────────────────────────────────────────
    # SCRAPING
    # ─────────────────────────────────────────────
    def scrape_dfprofiler(self):
        """Scrape current clan data from DFProfiler using requests + BeautifulSoup"""
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Starting DFProfiler scrape...")

        response = requests.get(self.url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # The table ID is assigned by JS, so we find it by locating the Members section
        table = None
        for t in soup.find_all("table"):
            headers = [th.get_text(strip=True) for th in t.find_all("th")]
            if "Username" in headers and "Weekly TS" in headers:
                table = t
                break
        if not table:
            raise RuntimeError("Could not find members table on the page.")

        rows = table.find_all("tr")
        new_data = []
        for row in rows:
            cols = row.find_all("td")
            if cols:
                new_data.append([col.get_text(strip=True) for col in cols])

        columns = [
            'Index', 'Username', 'Level', 'Rank', 'Profession',
            'Weekly TS', 'Weekly TPK', 'Weekly Loots', 'All Time TS',
            'All Time TPK', 'All Time Loots', 'GM', 'Gaining', 'Outpost',
            'Armor', 'Total Exp', 'Weapon1', 'Weapon2', 'Weapon3'
        ]
        df = pd.DataFrame(new_data, columns=columns)
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Successfully scraped {len(df)} members")

        leaderboard_ranks = self.scrape_global_leaderboards()
        return df, leaderboard_ranks

    def scrape_global_leaderboards(self):
        """Scrape Weekly TS and Weekly TPK global leaderboards"""
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Checking global leaderboards...")
        leaderboard_ranks = {}

        for url, key in [
            ("https://www.dfprofiler.com/player/weekly-ts",  "Weekly_TS_Rank"),
            ("https://www.dfprofiler.com/player/weekly-tpk", "Weekly_TPK_Rank"),
        ]:
            try:
                time.sleep(1)  # polite delay between requests
                response = requests.get(url, headers=HEADERS, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")

                table = soup.find("table")
                if not table:
                    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Could not find table on {url}")
                    continue

                rows = table.find_all("tr")[1:]  # skip header
                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) >= 3:
                        rank     = cols[1].get_text(strip=True)
                        username = cols[2].get_text(strip=True)
                        if username:
                            if username not in leaderboard_ranks:
                                leaderboard_ranks[username] = {}
                            leaderboard_ranks[username][key] = f"#{rank}"

                print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Scraped {key} leaderboard")

            except Exception as e:
                print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Could not scrape {key} leaderboard: {e}")

        return leaderboard_ranks

    # ─────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────
    def clean_number(self, value):
        if pd.isna(value) or value == '':
            return 0
        try:
            return int(str(value).replace(',', ''))
        except:
            return 0

    def build_snapshot(self, row, leaderboard_ranks, day_joined="", day_left=""):
        username = row['Username']
        weekly_ts_rank  = ""
        weekly_tpk_rank = ""
        if username in leaderboard_ranks:
            weekly_ts_rank  = leaderboard_ranks[username].get('Weekly_TS_Rank',  "")
            weekly_tpk_rank = leaderboard_ranks[username].get('Weekly_TPK_Rank', "")

        return {
            'date':           self.current_date,
            'week':           self.current_week,
            'username':       username,
            'level':          self.clean_number(row['Level']),
            'weekly_ts':      self.clean_number(row['Weekly TS']),
            'weekly_tpk':     self.clean_number(row['Weekly TPK']),
            'weekly_loots':   self.clean_number(row['Weekly Loots']),
            'alltime_ts':     self.clean_number(row['All Time TS']),
            'alltime_tpk':    self.clean_number(row['All Time TPK']),
            'alltime_loots':  self.clean_number(row['All Time Loots']),
            'weekly_ts_rank':  weekly_ts_rank,
            'weekly_tpk_rank': weekly_tpk_rank,
            'weekly_tl_rank':  '',
            'rank':           row['Rank'],
            'day_joined':     day_joined,
            'day_left':       day_left,
        }

    # ─────────────────────────────────────────────
    # CORE UPDATE
    # ─────────────────────────────────────────────
    def update_weekly_snapshots(self, new_df, leaderboard_ranks):
        """
        Upsert current week's data into weekly_snapshots.

        New week  → INSERT for every scraped member
                    - New member (never seen): day_joined = today
                    - Member missing vs last week: day_left = today
        Same week → per-member upsert via INSERT OR REPLACE
                    - New member: day_joined = today
                    - Existing member: update stats, preserve day_joined, clear day_left
                    - Missing member: mark day_left = today
        """
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Updating weekly_snapshots...")

        conn = self.get_connection()
        try:
            all_known             = self.get_all_known_usernames(conn)
            current_week_usernames = self.get_current_week_usernames(conn)
            scraped_usernames      = set(new_df['Username'].values)
            week_exists            = len(current_week_usernames) > 0

            if week_exists:
                print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] ⚠️  Week {self.current_week} exists ({len(current_week_usernames)} rows). Running per-member upsert...")
            else:
                print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] ✅ New week {self.current_week}. Inserting snapshot...")

            updated = inserted = skipped = 0

            for _, row in new_df.iterrows():
                username = row['Username']
                if not username or (hasattr(username, '__class__') and username.__class__.__name__ == 'float'):
                    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] ⚠️  Skipping row with null username: {dict(row)}")
                    skipped += 1
                    continue
                username = str(username).strip()
                if not username:
                    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] ⚠️  Skipping row with empty username")
                    skipped += 1
                    continue

                day_joined = self.current_date if username not in all_known else ""
                snapshot   = self.build_snapshot(row, leaderboard_ranks, day_joined=day_joined)
                snapshot['username'] = username

                if week_exists and username in current_week_usernames:
                    existing = conn.execute(
                        "SELECT day_joined FROM weekly_snapshots WHERE week = ? AND username = ?",
                        (self.current_week, username)
                    ).fetchone()
                    if existing and existing[0]:
                        snapshot['day_joined'] = existing[0]
                    snapshot['day_left'] = ""
                    updated += 1
                else:
                    inserted += 1

                conn.execute("""
                    INSERT OR REPLACE INTO weekly_snapshots
                    (date, week, username, level, weekly_ts, weekly_tpk, weekly_loots,
                     alltime_ts, alltime_tpk, alltime_loots, weekly_ts_rank, weekly_tpk_rank,
                     weekly_tl_rank, rank, day_joined, day_left)
                    VALUES
                    (:date, :week, :username, :level, :weekly_ts, :weekly_tpk, :weekly_loots,
                     :alltime_ts, :alltime_tpk, :alltime_loots, :weekly_ts_rank, :weekly_tpk_rank,
                     :weekly_tl_rank, :rank, :day_joined, :day_left)
                """, snapshot)

            # Members missing from scrape — mark day_left
            if week_exists:
                left_members = current_week_usernames - scraped_usernames
            else:
                left_members = self.get_prev_week_usernames(conn) - scraped_usernames

            for username in left_members:
                if week_exists:
                    conn.execute(
                        "UPDATE weekly_snapshots SET day_left = ? WHERE week = ? AND username = ?",
                        (self.current_date, self.current_week, username)
                    )
                else:
                    conn.execute(
                        "UPDATE weekly_snapshots SET day_left = ? WHERE username = ? AND week = (SELECT MAX(week) FROM weekly_snapshots WHERE username = ?)",
                        (self.current_date, username, username)
                    )

            if left_members:
                print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] 👋 {len(left_members)} member(s) marked Day Left: {', '.join(left_members)}")

            print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] ✅ Updated: {updated} | Inserted: {inserted} | Left: {len(left_members)} | Skipped: {skipped}")

            # Report leaderboard achievements
            on_leaderboard = [(u, r) for u, r in leaderboard_ranks.items() if u in scraped_usernames]
            if on_leaderboard:
                print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] 🏆 GLOBAL LEADERBOARD ACHIEVEMENTS:")
                for username, ranks in on_leaderboard:
                    achievements = []
                    if ranks.get('Weekly_TS_Rank'):
                        achievements.append(f"Weekly TS: {ranks['Weekly_TS_Rank']}")
                    if ranks.get('Weekly_TPK_Rank'):
                        achievements.append(f"Weekly TPK: {ranks['Weekly_TPK_Rank']}")
                    if achievements:
                        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}]    {username}: {', '.join(achievements)}")

            conn.commit()
            total_rows = conn.execute("SELECT COUNT(*) FROM weekly_snapshots").fetchone()[0]
            return total_rows

        finally:
            conn.close()

    # ─────────────────────────────────────────────
    # RUN
    # ─────────────────────────────────────────────
    def run(self):
        print("=" * 70)
        print(f"APEX CLAN TRACKER v3 - {self.current_date}")
        print("=" * 70)

        new_df, leaderboard_ranks = self.scrape_dfprofiler()
        total_rows = self.update_weekly_snapshots(new_df, leaderboard_ranks)

        print("\n" + "=" * 70)
        print("✅ SUCCESS")
        print("=" * 70)
        print(f"Members Scraped:              {len(new_df)}")
        print(f"Week:                         {self.current_week}")
        print(f"Total Snapshots in DB:        {total_rows}")
        print(f"\n📁 Database: {self.db_file}")
        print("=" * 70)


if __name__ == "__main__":
    tracker = ApexTrackerV3()
    tracker.run()
