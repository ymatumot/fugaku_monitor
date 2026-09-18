# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This directory contains four scripts:

- `resource_common.py`: shared code imported by both monitoring scripts below
  — Dropbox client/upload, `accounts.xlsx` loading, pie-chart color assignment
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

Each script renders a two-row grid of pie charts and uploads it as its own
image: the top row breaks usage down by tracked user (top 5 by usage, by
name), the bottom row breaks the same usage down by subgroup instead (the
`group` column in `accounts.xlsx` — currently just the placeholder `PIC` for
everyone, since no real subgrouping exists yet). Both rows share the same
column layout and a "未使用" slice for the unused portion of the allocated
quota (so the whole pie represents the quota, not just what's been used so
far). Both also fold "the rest of the group/subgroup, plus any tracked
users/subgroups past the top 5" into one catch-all slice, but the two scripts
label it differently: `node_hours.py` calls it "その他" (its `accountj`-based
numbers are current, so this slice genuinely means "other identities");
`disk_usage.py` calls it "未反映" instead, because its per-user breakdown
(`accountd -g <gid> -m -c`) lags its group totals (`accountd -g <gid> -c`) by
weeks (see `disk_usage.py`'s notes below) — that gap is not reliably "other
users," so its label says "not yet reflected" rather than implying specific
other identities. `node_hours.py` produces one column per fiscal-year period
(前期/後期/全期間), each titled with that period's usage vs. its allocated
quota; `disk_usage.py` produces one column per disk volume the group has a
quota on, titled with usage vs. quota in GiB. Capping at the top 5 keeps each
chart readable as more users/subgroups get added to `accounts.xlsx` over time.

Each image is saved as `node_hours_<YYYYMMDD>.png` / `disk_usage_<YYYYMMDD>.png`
next to the scripts, uploaded to the Dropbox app's own dedicated folder via
the Dropbox API, and then the local copy is deleted — the PNGs only persist
in Dropbox, not on disk.

## Running the scripts

```bash
python3 node_hours.py
python3 disk_usage.py
```

No arguments — tracked user IDs, names, and group IDs come from `accounts.xlsx`
in the Dropbox app folder, downloaded fresh on every run by each script (see
"Accounts file" below). Requires `pandas` (`node_hours.py` only), `matplotlib`,
`dropbox` (`pip install dropbox`), `openpyxl` (`pip install openpyxl`, for
reading `accounts.xlsx`) and working `pjstatj`/`accountj` (`node_hours.py`) /
`accountd` (`disk_usage.py`) on PATH (all present at `/usr/local/bin/` on
this system).

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

`uids`/`names`/`groups` are not hardcoded — `resource_common.load_accounts()`
downloads `accounts.xlsx` from `dropbox_folder+'/accounts.xlsx'` (see
"Dropbox upload credentials" below for what `dropbox_folder` resolves to —
the app folder root by default, or `DROPBOX_FOLDER`'s value) at the start of
every run and parses it via `openpyxl` (`read_only=True, data_only=True`,
first worksheet only), keyed on a header row `uid,name,group` followed by one
row per tracked user (the same `group` value can appear on multiple rows). This
means adding, removing, or moving a tracked user between subgroups only
requires editing that file in Dropbox — no script change or redeploy needed,
in either script. `uid_group` (the per-row `uid -> group` mapping) is used in
each script's main loop to total each subgroup's usage for the bottom-row
pies.

Note `group` here is a subgroup *label* for the per-group breakdown pies, not
the Fugaku `accountj`/`accountd` group id — that id is currently hardcoded as
`GID = 'hp240019'` at the top of each script, since only one Fugaku group has
ever been tracked. Reading it from `accounts.xlsx` instead (to support
tracking multiple real Fugaku groups) is a planned future change, not
implemented yet.

No local copy is kept — every run re-downloads `accounts.xlsx`, and
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
tokens expire in hours and would break unattended cron runs). Each reads
environment variables at run time (via `resource_common.get_dropbox_client()`
for the first three; each script reads `DROPBOX_FOLDER` itself) — set them
wherever cron's environment is configured (crontab `VAR=value` lines, or a
sourced env file):

- `DROPBOX_APP_KEY`
- `DROPBOX_APP_SECRET`
- `DROPBOX_REFRESH_TOKEN`
- `DROPBOX_FOLDER` (optional — see below)

The first three come from a Dropbox app created in the Dropbox App Console
and an OAuth2 refresh-token flow run once to obtain `DROPBOX_REFRESH_TOKEN`.
Do not hardcode these values in either script — this is also why
`DROPBOX_FOLDER` is an env var rather than a literal path in the code: the
scripts are meant to be published (e.g. on GitHub), and a real folder name is
config, not something that belongs in public source.

`dropbox_folder = os.environ.get('DROPBOX_FOLDER', '')` in both scripts
defaults to `''` when unset. What `''` means depends on the app's access
type, chosen in the Dropbox App Console when the app was created:

- **App folder** access (this app's original setup): all API paths are
  relative to the app's own dedicated folder in the connected account, so
  `''` means "that app folder's root" — there is no real folder name to leak,
  since the app can't reach anywhere else in the account regardless of what
  `DROPBOX_FOLDER` is set to.
- **Full Dropbox** access (needed to read/write a folder another user shared
  with you and gave you edit access to, since that's outside any App folder):
  paths are relative to the Dropbox account root, so `DROPBOX_FOLDER` must be
  set to the shared folder's actual path (e.g. `/SharedFolderName`, as it
  appears mounted in your own Dropbox) for uploads/downloads to land there
  instead of the account root.

Changing access type (or, for App folder access, the app's name/folder)
always invalidates the existing refresh token — the previously issued token
doesn't cover the new scope — and requires re-authorizing (see the recovery
procedure below) to get a new one.

On this system the three variables live in `~/.config/fugaku_monitor.env`
(`chmod 600`, `export VAR=value` lines) and cron sources that file before
running each script:

```cron
0 6 * * * . $HOME/.config/fugaku_monitor.env && /path/to/python3 $HOME/scripts/node_hours.py >> $HOME/scripts/node_hours_cron.log 2>&1
30 6 * * 1 . $HOME/.config/fugaku_monitor.env && /path/to/python3 $HOME/scripts/disk_usage.py >> $HOME/scripts/disk_usage_cron.log 2>&1
```

(`/path/to/python3` must be the absolute path to whichever `python3` has this
project's dependencies installed — find it with `which python3`; cron runs
with a minimal `PATH`, so a bare `python3` often resolves to the wrong
interpreter or none at all. `disk_usage.py` runs Mondays at 6:30 — offset
from `node_hours.py`'s 6:00 run so the two don't overlap; the day/time is
arbitrary and easy to change. `cron` sets `$HOME` from the crontab owner's
passwd entry, and `$HOME/scripts` here resolves to the same directory as
this repo's absolute path — `$HOME` is `/home/<uid>`, a symlink/bind mount to
`/vol0006/mdt3/home/<uid>` on this system — so this line has no hardcoded
username and works unchanged for
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
- `load_accounts(dbx, folder)` returns `uids, names, groups, uid_group` (see
  "Accounts file" above); `groups` is the deduplicated, first-seen-order list
  of every `group` value present in `accounts.xlsx` (currently just `PIC`).
  Each script does `users = dict(zip(uids, names))` itself to map uid to
  display name.
- `upload_to_dropbox(dbx, local_path, folder)` uploads with
  `mode=dropbox.files.WriteMode.overwrite`.
- `build_color_map(uids, users)` (top-row, per-user pies) and
  `build_group_color_map(groups)` (bottom-row, per-group pies) deliberately
  draw from two different color scales so a user's color and a group's color
  are never visually confusable, even when both happen to land on a similar
  hue: user colors come from the `ggplot` style's multi-hue cycle *minus its
  last color* (`_USER_COLORS`); group colors come from `_GROUP_COLORS` — a
  fixed 5-step monochrome blue ramp (light to dark) pulled from the dataviz
  skill's validated palette reference, spread out (not consecutive steps) for
  maximum mutual contrast. Both call the shared `_assign_distinct_colors(keys,
  pool)`: each key's preferred slot is a hash of the key (stable across runs,
  independent of accounts.xlsx's row order — keys are processed in `sorted()`
  order so the outcome depends only on the *set* of keys present), but if that
  slot is already taken by another key in the same call, it linear-probes
  forward to the next free one — so two different tracked users (or two
  different groups) are never handed the same color, as long as there are at
  most `len(pool)` of them (a 5-6 item pool is comfortably ahead of today's 5
  tracked users and 1 group, but a slot can get reused once that pool is
  exhausted). Both functions take an `other_label` parameter (default
  `'その他'`; `disk_usage.py` passes `'未反映'` instead — see the Overview)
  for the catch-all slice's dict key, mapped to the reserved last `ggplot`
  cycle color for users or a violet accent (`_GROUP_OTHER_COLOR`) for groups
  — so it can never collide with that row's assigned colors; "未使用" is
  hardcoded to the same gray in both rows (a shared, non-identity "nothing
  here" meaning, not a specific user/group's color). A given user/group/slice
  keeps the same color across every pie a script
  draws, regardless of which slices happen to be present. `resource_common`
  calls `plt.style.use('ggplot')` at import time before
  `_cycle`/`_USER_COLORS`/`_OTHER_COLOR` are computed, so importing it in a
  different order (or re-styling afterward) would silently change the
  per-user palette these read from (`_GROUP_COLORS` is independent of the
  `ggplot` style).
- `top_n_or_other(pairs, other_value, n=TOP_N)` takes the tracked users'
  `(name, value)` pairs for one pie, keeps the top `n` (`TOP_N = 5`) by value
  under their own name, and folds the rest into a single total added to
  `other_value` (the already-computed rest-of-group amount) — so a pie never
  shows more than `TOP_N + 2` slices (top N users + その他 + 未使用) no
  matter how many users `accounts.xlsx` ends up tracking.
- `pie_or_placeholder(ax, values, pie_labels, title, color_map)` draws one pie
  chart: zero-value slices are dropped, wedge labels are shown via
  `ax.legend()` (rather than `ax.pie(labels=...)`) so that very small slices
  don't produce overlapping label text, and `autopct` suppresses the
  percentage/count text for slices under 1% for the same reason. If every
  value is 0 (e.g. 後期 before it starts), it prints "利用なし" instead of an
  empty pie. Slices always start at 12 o'clock and go clockwise
  (`startangle=90, counterclock=False`) so every pie is oriented the same way.

### `node_hours.py`

- `GID` (currently `'hp240019'`) is the hardcoded real Fugaku group id passed
  to `accountj`/`pjstatj`; every tracked uid in `accounts.xlsx` is queried
  under it regardless of that user's `group` (subgroup) value. The top-row
  pies break the result down per user (as before); the bottom-row pies total
  the same per-user numbers by `uid_group[uid]` instead, for the per-subgroup
  breakdown.
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

- `GID` (currently `'hp240019'`) is the hardcoded real Fugaku group id, same
  role as in `node_hours.py` — every tracked uid is queried under it
  regardless of that user's `group` (subgroup) value, and the bottom-row
  pies total per-user disk usage by `uid_group[uid]`.
- `get_group_disk_usage(gid)` runs `accountd -g <gid> -c` and reads its `GROUP`
  rows to get, per volume, the group's disk quota and total usage in GiB — only
  volumes with an actual group quota show up here. `get_user_disk_usage(gid)`
  runs `accountd -g <gid> -m -c` and reads its `USER` rows to get per-`(volume,
  uid)` usage in GiB, for every user in the group (not just tracked ones).
- These two `accountd` queries are **not** the same freshness: `-c`'s
  `COLLECT_DATE` is current on every run, but `-m -c`'s `COLLECT_DATE` is a
  much staler, infrequently-refreshed snapshot (observed several weeks behind
  in practice, and unchanged across repeated calls in the same session) — so
  the per-user breakdown can lag the group total by weeks. This means a
  volume's "その他" slice is *not* necessarily usage by untracked group
  members — it can equally be recent usage by a tracked user that the stale
  per-user snapshot hasn't caught up to yet (e.g. a user who started using a
  volume, or grew their usage on one, after that snapshot was taken). There
  is no way to tell the two apart from `accountd`'s output alone.
- If a group has no volumes with a quota, the figure is a single axes showing
  "対象ボリュームなし" instead of a two-row grid of pies.

## Editing notes

- To add/remove tracked users or subgroups, edit `accounts.xlsx` in the
  Dropbox app folder directly — no script change needed. It has a header row
  (`uid,name,group`) followed by one `uid,name,group` row per tracked user;
  `group` is a subgroup label (currently `PIC` for everyone), not the real
  Fugaku group id.
- To track a different (or additional) real Fugaku group, change/add the
  hardcoded `GID` constant near the top of `node_hours.py`/`disk_usage.py` —
  this is not read from `accounts.xlsx`. Supporting multiple real Fugaku
  groups from `accounts.xlsx` itself is a planned future change, not
  implemented yet.
- Allocation quotas are fetched live via `accountj`, not hardcoded — no manual
  update needed when a new fiscal year's allocation is granted.
- `labels` (in `node_hours.py`) selects which `pjstatj -c` CSV columns are
  read; changing it requires matching the downstream column-index parsing of
  `ELAPSE_TIM` (fixed string slices `[0:4]`/`[5:7]`/`[8:10]` assume
  `HHHH:MM:SS`-style formatting).
