"""
APEX CLAN - Run All
Chains all three scripts in sequence. Stops if any script fails.
After HTML is generated, pushes to GitHub Pages automatically.
"""

import subprocess
import sys
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SCRIPTS = [
    "apex_clan_db_python_v3.py",
    "apex_calc_v3.py",
    "apex_html_gen_v3.py",
]

# ===== CONFIGURATION =====
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_TOKEN    = os.getenv("GITHUB_TOKEN")
GITHUB_REPO     = os.getenv("GITHUB_REPO")

print("=" * 70)
print("🏆 APEX CLAN - RUN ALL")
print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

# ===== RUN SCRIPTS =====
for i, script in enumerate(SCRIPTS, 1):
    print(f"\n[{i}/3] Running {script}...")
    print("-" * 70)

    result = subprocess.run([sys.executable, script])

    if result.returncode != 0:
        print(f"\n❌ {script} failed with exit code {result.returncode}. Stopping.")
        input("\nPress Enter to exit...")
        sys.exit(1)

    print(f"\n✅ {script} completed successfully.")

# ===== GIT PUSH =====
print(f"\n[4/4] Pushing to GitHub...")
print("-" * 70)

remote_url = f"https://{GITHUB_USERNAME}:{GITHUB_TOKEN}@github.com/{GITHUB_USERNAME}/{GITHUB_REPO}.git"
week_label = datetime.now().strftime('%Y-W%W')

git_commands = [
    ["git", "add", "index.html"],
    ["git", "add", "chart.min.js"],
    ["git", "commit", "-m", f"Weekly update - {week_label}"],
    ["git", "remote", "set-url", "origin", remote_url],
    ["git", "push", "origin", "main"],
]

for cmd in git_commands:
    result = subprocess.run(cmd)
    if result.returncode != 0 and cmd[1] != "commit":  # commit can fail if no changes
        print(f"\n❌ Git command failed: {' '.join(cmd[:2])}. Stopping.")
        input("\nPress Enter to exit...")
        sys.exit(1)

print(f"\n{'=' * 70}")
print("✅ ALL DONE — Tracker → Calc → HTML → GitHub complete!")
print(f"🌐 Live at: https://{GITHUB_USERNAME}.github.io/{GITHUB_REPO}/")
print(f"{'=' * 70}")
input("\nPress Enter to exit...")
