# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This directory contains two scripts:

- `used_resource.py`: tracks compute (node-hour) and disk usage for a Fugaku
  group (`gid`) via the `accountj`/`accountd`/`pjstatj` Fujitsu accounting
  CLIs, and renders pie charts of each tracked user's share against the
  group's allocated quota.
- `get_dropbox_refresh_token.py`: a one-off interactive helper to (re-)obtain a
  Dropbox OAuth2 refresh token when `used_resource.py`'s Dropbox upload starts
  failing with an auth error (see "Dropbox upload credentials" below).

The rendered image is a 2-row grid of pie charts: the top row has one pie per
fiscal-year period (前期/後期/全期間) showing node-hour usage split by tracked
user, a catch-all "その他" slice for the rest of the group, and a "未使用"
slice for the unused portion of the period's allocated quota (so the whole pie
represents the quota, not just what's been used so far), each titled with that
period's usage vs. its allocated quota; the bottom row has one pie per disk
volume the group has a quota on, same per-user + その他 + 未使用 breakdown,
titled with usage vs. quota in GiB. It's saved to `resource_usage_<YYYYMMDD>.png`
next to the script and uploaded to the Dropbox app's own dedicated folder via
the Dropbox API.

## Running the script

```bash
python3 used_resource.py
```

No arguments — user IDs, group IDs, and names are hardcoded at the top of the
file. Requires `pandas`, `matplotlib`, `dropbox` (`pip install dropbox`) and
working `pjstatj`/`accountj`/`accountd` on PATH (all present at
`/usr/local/bin/` on this system).

Intended to be run periodically via cron (scheduling itself is not handled by the
script — add a crontab entry that invokes `python3 used_resource.py`).

Japanese period labels (前期/後期/全期間) require a CJK-capable font; the script
sets `matplotlib.rcParams['font.family'] = ['DejaVu Sans', 'Droid Sans Japanese']`
(matplotlib's per-glyph font fallback picks the right font for CJK vs. Latin
glyphs) — `Droid Sans Japanese` ships at
`/usr/share/fonts/google-droid/DroidSansJapanese.ttf` on this system. Without it,
period labels render as missing-glyph boxes.

### Dropbox upload credentials

The script uploads via a long-lived Dropbox refresh token (short-lived access
tokens expire in hours and would break unattended cron runs). It reads three
environment variables at run time — set them wherever cron's environment is
configured (crontab `VAR=value` lines, or a sourced env file):

- `DROPBOX_APP_KEY`
- `DROPBOX_APP_SECRET`
- `DROPBOX_REFRESH_TOKEN`

These come from a Dropbox app created in the Dropbox App Console (scoped app,
**App folder** access, `files.content.write` permission) and an OAuth2
refresh-token flow run once to obtain `DROPBOX_REFRESH_TOKEN`. Do not hardcode
these values in the script.

Because the app uses App folder access (not Full Dropbox), all API paths are
relative to the app's own dedicated folder in the connected Dropbox account —
`dropbox_folder = ''` in `used_resource.py` means "the app folder's root", not
the Dropbox root. If the access type is ever changed back to Full Dropbox (or
to a different app folder name), the existing refresh token becomes invalid
for the new scope and must be reobtained (see the recovery procedure below) —
changing access type always requires re-authorizing.

On this system the three variables live in `~/.config/fugaku_monitor.env`
(`chmod 600`, `export VAR=value` lines) and cron sources that file before
running the script:

```cron
0 6 * * * . $HOME/.config/fugaku_monitor.env && /home/<uid1>/miniconda3/bin/python3 /vol0006/mdt3/home/<uid1>/scripts/used_resource.py >> /vol0006/mdt3/home/<uid1>/scripts/cron.log 2>&1
```

A refresh token normally never expires on its own — it stops working only if
the app's Dropbox connection is revoked (Dropbox account settings > Connected
apps), the app is deleted, or its App secret is regenerated in the App
Console. When that happens, the cron job's graph generation still succeeds
(the PNG is written next to the script) but the upload step raises a
`dropbox.exceptions.AuthError`, visible in `cron.log`. To recover, get a new
authorization code (App key/secret are unaffected and can be reused) —

```
https://www.dropbox.com/oauth2/authorize?client_id=<APP_KEY>&response_type=code&token_access_type=offline
```

— then run `get_dropbox_refresh_token.py` (prompts for App key, App secret,
and the authorization code via `getpass`, so none of them get echoed or
logged) and copy its printed `refresh_token` into
`~/.config/fugaku_monitor.env`.

## How it works

- `uids`/`gids`/`names` are parallel lists mapping Fugaku user IDs to group IDs
  and display names (`users = dict(zip(uids, names))`). Currently
  `gids = ['hp240019']` and all `uids` are queried against it — there are no
  per-group membership exceptions right now, but if a group only includes a
  subset of `uids`, add an `if gid == '<gid>': if uid not in (...): continue`
  block inside the `uid` loop (this pattern was used previously for
  `<gid1>`/`<gid2>`, since replaced by `hp240019`).
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
  — the script is not safe to run concurrently with itself.
- `get_group_disk_usage(gid)` runs `accountd -g <gid> -c` and reads its `GROUP`
  rows to get, per volume, the group's disk quota and total usage in GiB — only
  volumes with an actual group quota show up here. `get_user_disk_usage(gid)`
  runs `accountd -g <gid> -m -c` and reads its `USER` rows to get per-`(volume,
  uid)` usage in GiB, for every user in the group (not just tracked ones).
- `pie_or_placeholder(ax, values, pie_labels, title)` draws one pie chart:
  zero-value slices are dropped, wedge labels are shown via `ax.legend()`
  (rather than `ax.pie(labels=...)`) so that very small slices don't produce
  overlapping label text, and `autopct` suppresses the percentage/count text
  for slices under 1% for the same reason. If every value is 0 (e.g. kouki
  before it starts), it prints "利用なし" instead of an empty pie. Slices
  always start at 12 o'clock and go clockwise (`startangle=90,
  counterclock=False`) so every pie is oriented the same way. Colors come from
  the module-level `color_map` (built once from the `ggplot` style's color
  cycle for each tracked user's name and "その他", with "未使用" hardcoded to
  gray) so a given user/slice keeps the same color across every pie in the
  figure, regardless of which slices happen to be present.
- The script calls `plt.style.use('ggplot')` right after configuring the font,
  so `color_map` must be built after that call (it reads
  `plt.rcParams['axes.prop_cycle']`) — reordering these would silently revert
  to matplotlib's default color cycle.

## Editing notes

- To add/remove tracked users or groups, keep `uids`, `gids`, and `names` in sync
  (order-dependent zip), and add/update any per-group membership exception blocks
  (see above) if a group doesn't include every tracked `uid`.
- Allocation quotas are fetched live via `accountj`, not hardcoded — no manual
  update needed when a new fiscal year's allocation is granted.
- `labels` selects which `pjstatj -c` CSV columns are read; changing it requires
  matching the downstream column-index parsing of `ELAPSE_TIM` (fixed string
  slices `[0:4]`/`[5:7]`/`[8:10]` assume `HHHH:MM:SS`-style formatting).
