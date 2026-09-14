# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This directory contains four scripts:

- `resource_common.py`: shared code imported by both monitoring scripts below
  — Dropbox client/upload, `accounts.csv` loading, pie-chart color assignment
  and drawing. Not run directly.
- `node_hours.py`: tracks compute (node-hour) usage for a Fugaku group
  (`gid`) via the `accountj`/`pjstatj` Fujitsu accounting CLIs, and renders a
  pie per fiscal-year period. Run **daily** — node-hour data is cheap to
  query.
- `disk_usage.py`: tracks disk usage per volume for a Fugaku group via the
  `accountd` accounting CLI, and renders a pie per volume. Run **weekly** —
  `accountd` is slow, so it's queried far less often than node-hours.
- `get_dropbox_refresh_token.py`: a one-off interactive helper to (re-)obtain a
  Dropbox OAuth2 refresh token when either script's Dropbox upload starts
  failing with an auth error (see "Dropbox upload credentials" below).

`node_hours.py` and `disk_usage.py` were originally one script
(`used_resource.py`, producing one combined image) but were split so each
workload could run on its own schedule — bundling them meant every daily cron
run paid the slow `accountd` cost even on days a disk-usage refresh wasn't
wanted.

Each script renders a row of pie charts and uploads it as its own image:
`node_hours.py` produces one pie per fiscal-year period (前期/後期/全期間)
showing node-hour usage split by the top 5 tracked users by usage (by name),
a catch-all "その他" slice folding in both the rest of the group and any
tracked users past the top 5, and a "未使用" slice for the unused portion of
the period's allocated quota (so the whole pie represents the quota, not just
what's been used so far), each titled with that period's usage vs. its
allocated quota. `disk_usage.py` produces one pie per disk volume the group
has a quota on, same top-5-by-name + その他 + 未使用 breakdown, titled with
usage vs. quota in GiB. Capping at the top 5 keeps each chart readable as more
users get added to `accounts.csv` over time.

Each image is saved as `node_hours_<YYYYMMDD>.png` / `disk_usage_<YYYYMMDD>.png`
next to the scripts, uploaded to the Dropbox app's own dedicated folder via
the Dropbox API, and then the local copy is deleted — the PNGs only persist
in Dropbox, not on disk.

## Running the scripts

```bash
python3 node_hours.py
python3 disk_usage.py
```

No arguments — tracked user IDs, names, and group IDs come from `accounts.csv`
in the Dropbox app folder, downloaded fresh on every run by each script (see
"Accounts file" below). Requires `pandas` (`node_hours.py` only), `matplotlib`,
`dropbox` (`pip install dropbox`) and working `pjstatj`/`accountj`
(`node_hours.py`) / `accountd` (`disk_usage.py`) on PATH (all present at
`/usr/local/bin/` on this system).

Intended to be run periodically via cron on two different schedules
(scheduling itself is not handled by the scripts — see the crontab below):
`node_hours.py` daily, `disk_usage.py` weekly.

Japanese labels (前期/後期/全期間/その他/未使用) require a CJK-capable font;
`resource_common.py` sets
`matplotlib.rcParams['font.family'] = ['DejaVu Sans', 'Droid Sans Japanese']`
(matplotlib's per-glyph font fallback picks the right font for CJK vs. Latin
glyphs) — `Droid Sans Japanese` ships at
`/usr/share/fonts/google-droid/DroidSansJapanese.ttf` on this system. Without it,
these labels render as missing-glyph boxes. Because `resource_common` also
calls `matplotlib.use('Agg')` and `plt.style.use('ggplot')` at import time,
both scripts `import resource_common` *before* `import matplotlib.pyplot as
plt`, so the backend/font/style are already configured when pyplot is used.

### Accounts file

`uids`/`names`/`gids` are not hardcoded — `resource_common.load_accounts()`
downloads `accounts.csv` from the root of the Dropbox app folder at the start
of every run (`dbx.files_download('/accounts.csv')`) and parses it as plain,
headerless CSV rows of `uid,name,gid` (one row per tracked user; the same
`gid` can appear on multiple rows). This means adding, removing, or moving a
tracked user between groups only requires editing that file in Dropbox — no
script change or redeploy needed, in either script. `uid_gid` (the per-row
`uid -> gid` mapping) is used in each script's main loop to filter each
group's user list (`group_uids = [uid for uid in uids if uid_gid[uid] ==
gid]`), so a group only shows the users actually assigned to it in the file.

No local copy is kept — every run re-downloads `accounts.csv`, and
`load_accounts()` lets `dbx.files_download` raise straight out of it (no
try/except) if Dropbox is unreachable or the file is missing, so cron runs
loudly fail rather than silently working from a stale account list.

Downloading requires the Dropbox app to have the `files.content.read`
permission in addition to `files.content.write` (Dropbox App Console >
Permissions tab); adding a scope to an existing app requires re-authorizing
(see the recovery procedure below) since the previously issued refresh token
doesn't cover the new scope — attempting to use it raises
`stone.backends.python_rsrc.stone_validators.ValidationError: unexpected use
of the catch-all tag 'other'` (misleading; the real cause, visible only in the
raw HTTP response, is a missing scope, not a decoding bug).

### Dropbox upload credentials

Both scripts upload via a long-lived Dropbox refresh token (short-lived access
tokens expire in hours and would break unattended cron runs). Each reads three
environment variables at run time (via `resource_common.get_dropbox_client()`)
— set them wherever cron's environment is configured (crontab `VAR=value`
lines, or a sourced env file):

- `DROPBOX_APP_KEY`
- `DROPBOX_APP_SECRET`
- `DROPBOX_REFRESH_TOKEN`

These come from a Dropbox app created in the Dropbox App Console (scoped app,
**App folder** access, `files.content.write` permission) and an OAuth2
refresh-token flow run once to obtain `DROPBOX_REFRESH_TOKEN`. Do not hardcode
these values in either script.

Because the app uses App folder access (not Full Dropbox), all API paths are
relative to the app's own dedicated folder in the connected Dropbox account —
`dropbox_folder = ''` in both scripts means "the app folder's root", not the
Dropbox root. If the access type is ever changed back to Full Dropbox (or to a
different app folder name), the existing refresh token becomes invalid for the
new scope and must be reobtained (see the recovery procedure below) — changing
access type always requires re-authorizing.

On this system the three variables live in `~/.config/fugaku_monitor.env`
(`chmod 600`, `export VAR=value` lines) and cron sources that file before
running each script:

```cron
0 6 * * * . $HOME/.config/fugaku_monitor.env && $HOME/miniconda3/bin/python3 $HOME/scripts/node_hours.py >> $HOME/scripts/node_hours_cron.log 2>&1
30 6 * * 1 . $HOME/.config/fugaku_monitor.env && $HOME/miniconda3/bin/python3 $HOME/scripts/disk_usage.py >> $HOME/scripts/disk_usage_cron.log 2>&1
```

(`disk_usage.py` runs Mondays at 6:30 — offset from `node_hours.py`'s 6:00 run
so the two don't overlap; the day/time is arbitrary and easy to change. `cron`
sets `$HOME` from the crontab owner's passwd entry, and `$HOME/scripts` here
resolves to the same directory as this repo's absolute path — `$HOME` is
`/home/<uid>`, a symlink/bind mount to `/vol0006/mdt3/home/<uid>` on this
system — so this line has no hardcoded username and works unchanged for
whichever account's crontab it's installed in.)

A refresh token normally never expires on its own — it stops working only if
the app's Dropbox connection is revoked (Dropbox account settings > Connected
apps), the app is deleted, or its App secret is regenerated in the App
Console. When that happens, a cron run's graph generation still succeeds (the
PNG is written next to the script) but the upload step raises a
`dropbox.exceptions.AuthError`, visible in that script's cron log. To recover,
get a new authorization code (App key/secret are unaffected and can be
reused) —

```
https://www.dropbox.com/oauth2/authorize?client_id=<APP_KEY>&response_type=code&token_access_type=offline
```

— then run `get_dropbox_refresh_token.py` (prompts for App key, App secret,
and the authorization code via `getpass`, so none of them get echoed or
logged) and copy its printed `refresh_token` into
`~/.config/fugaku_monitor.env`. One token is shared by both scripts, so this
only needs doing once even though two scripts use it.

## How it works

### `resource_common.py`

- `get_dropbox_client()` builds the `dropbox.Dropbox` client from the three
  env vars above.
- `load_accounts(dbx, folder)` returns `uids, names, gids, uid_gid` (see
  "Accounts file" above); `gids` is the deduplicated, first-seen-order list of
  every `gid` present in `accounts.csv` (currently just `hp240019`). Each
  script does `users = dict(zip(uids, names))` itself to map uid to display
  name.
- `upload_to_dropbox(dbx, local_path, folder)` uploads with
  `mode=dropbox.files.WriteMode.overwrite`.
- `build_color_map(uids, users)` returns the module-level-style color map each
  script uses: each tracked user's color is `_color_for_uid(uid)`, a
  deterministic hash of their `uid` (`md5(uid) % len(_USER_COLORS)`) into the
  `ggplot` style's color cycle *minus its last color* — hashing on `uid`
  rather than list position means a user's color stays fixed across runs even
  as `accounts.csv` gains, loses, or reorders rows. "その他" is hardcoded to
  that reserved last cycle color (so it can never collide with a user's hash
  color) and "未使用" is hardcoded to gray. A given user/slice keeps the same
  color across every pie a script draws, regardless of which slices happen to
  be present. `resource_common` calls `plt.style.use('ggplot')` at import time
  before `_cycle`/`_USER_COLORS`/`_OTHER_COLOR` are computed, so importing it
  in a different order (or re-styling afterward) would silently change the
  palette these read from.
- `top_n_or_other(pairs, other_value, n=TOP_N)` takes the tracked users'
  `(name, value)` pairs for one pie, keeps the top `n` (`TOP_N = 5`) by value
  under their own name, and folds the rest into a single total added to
  `other_value` (the already-computed rest-of-group amount) — so a pie never
  shows more than `TOP_N + 2` slices (top N users + その他 + 未使用) no
  matter how many users `accounts.csv` ends up tracking.
- `pie_or_placeholder(ax, values, pie_labels, title, color_map)` draws one pie
  chart: zero-value slices are dropped, wedge labels are shown via
  `ax.legend()` (rather than `ax.pie(labels=...)`) so that very small slices
  don't produce overlapping label text, and `autopct` suppresses the
  percentage/count text for slices under 1% for the same reason. If every
  value is 0 (e.g. 後期 before it starts), it prints "利用なし" instead of an
  empty pie. Slices always start at 12 o'clock and go clockwise
  (`startangle=90, counterclock=False`) so every pie is oriented the same way.

### `node_hours.py`

- Periods are fiscal-year halves: `zenki`/前期 = Apr 1–Sep 30, `kouki`/後期 =
  Oct 1–Mar 31, `zenkikan`/全期間 = the two combined. The fiscal year is derived
  from today's date (`fiscal_year = today.year if today.month >= 4 else
  today.year - 1`), so the window shifts automatically as the script keeps
  running across fiscal years — it does not need manual updates twice a year.
  A period whose start date is in the future is skipped (reported as 0
  node-hours) rather than queried.
- `get_period_stats(gid)` fetches the group's granted node-hour quota *and*
  usage per period from `accountj -g <gid> -r 1 -c` (CSV output, values in
  seconds) rather than hardcoding the quota. It reads the `SUBTHEMEPERIOD` rows
  (period `1` = zenki/前期, period `2` = kouki/後期), divides `LIMIT`/`USAGE` by
  3600 to get node-hours, and derives `zenkikan` as the sum of both. Note the
  allocation cap lives on the parent *subtheme* (e.g. `hp240019`'s parent is
  `hp260014`), not the group itself — `accountj`'s plain `GROUP` row typically
  shows `unlimited`. A period is only given a reference line on the graph when
  its allocation is `> 0`.
- `get_group_user_node_hours(gid)` runs `accountj -g <gid> -E -r 1 -c` *once*
  and reads its `USER` rows to get every group member's node-hour usage — this
  is a fiscal-year-to-date cumulative total (it has no period breakdown), but
  is dramatically faster than querying `pjstatj` (this single `accountj -E`
  call replaced what used to be one slow `pjstatj` call per tracked user, per
  period). While today is still within zenki (`today < kouki_start`), this
  cumulative total *is* zenki's total (kouki hasn't started yet), so it's used
  directly and `pjstatj` is never called. Once kouki has started, zenki is
  finalized and no longer obtainable from this fiscal-year-to-date number, so
  `group_node_hours_pjstatj(gid, zenki_start, zenki_end)` is used instead to
  pin it down — and kouki's total is derived per user by subtracting that from
  the fast cumulative total.
- `group_node_hours_pjstatj(gid, start, end)` runs
  `pjstatj -s -g <gid> -t <term> -c > output.csv` — *without* `-u`, so it's one
  call for the whole group rather than one per user — reads the CSV with
  pandas, extracts `ELAPSE_TIM` (elapsed time, parsed as `HH:MM:SS` string
  slices) and `NANUM` (node count), and groups by `USER` to sum
  `elapsed_hours * nodes` into node-hours per user. `ELAPSE_TIM` is cast to
  `str` before slicing so that queued/unrun jobs (empty `ELAPSE_TIM`, which
  pandas may infer as an all-NaN float column after `dropna()`) don't crash the
  `.str` accessor — this happens in practice for jobs with `ST == 'QUE'`.
  `output.csv` is a shared scratch file, overwritten and deleted on every call
  — `node_hours.py` is not safe to run concurrently with itself.

### `disk_usage.py`

- `get_group_disk_usage(gid)` runs `accountd -g <gid> -c` and reads its `GROUP`
  rows to get, per volume, the group's disk quota and total usage in GiB — only
  volumes with an actual group quota show up here. `get_user_disk_usage(gid)`
  runs `accountd -g <gid> -m -c` and reads its `USER` rows to get per-`(volume,
  uid)` usage in GiB, for every user in the group (not just tracked ones).
- If a group has no volumes with a quota, the figure is a single axes showing
  "対象ボリュームなし" instead of an empty row of pies.

## Editing notes

- To add/remove tracked users or groups, edit `accounts.csv` in the Dropbox
  app folder directly — no script change needed. Each row is `uid,name,gid`.
- Allocation quotas are fetched live via `accountj`, not hardcoded — no manual
  update needed when a new fiscal year's allocation is granted.
- `labels` (in `node_hours.py`) selects which `pjstatj -c` CSV columns are
  read; changing it requires matching the downstream column-index parsing of
  `ELAPSE_TIM` (fixed string slices `[0:4]`/`[5:7]`/`[8:10]` assume
  `HHHH:MM:SS`-style formatting).
- Both scripts fix their image filename before the per-`gid` loop runs, so if
  `accounts.csv` ever spans more than one `gid`, each group's figure
  overwrites the previous one at that same path and only the last group's
  image ends up uploaded — this predates the split and was never exercised in
  practice (`accounts.csv` has only ever listed one `gid`, `hp240019`).
