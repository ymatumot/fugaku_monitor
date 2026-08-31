# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This directory contains two scripts:

- `used_resource.py`: tracks compute resource usage (node-hours) on the Fugaku
  supercomputer (Fujitsu FX1000/PJM environment). It shells out to `pjstatj`
  (Fujitsu's job accounting CLI) to pull per-user job statistics for a group ID
  (`gid`) and computes node-hours consumed per user, broken down by fiscal-year
  period (前期/後期/全期間), against the group's allocated quota.
- `get_dropbox_refresh_token.py`: a one-off interactive helper to (re-)obtain a
  Dropbox OAuth2 refresh token when `used_resource.py`'s Dropbox upload starts
  failing with an auth error (see "Dropbox upload credentials" below).

After computing node-hours, the script renders a grouped bar chart — one group
of bars per period, one bar per user within each group, with a red dashed line
marking that period's allocation — to `resource_usage_<YYYYMMDD>.png` next to
the script, and uploads that PNG to the Dropbox folder `/FugakuMonitor` via the
Dropbox API.

## Running the script

```bash
python3 used_resource.py
```

No arguments — user IDs, group IDs, and names are hardcoded at the top of the
file. Requires `pandas`, `matplotlib`, `numpy`, `dropbox` (`pip install
dropbox`) and working `pjstatj`/`accountj` on PATH (both present at
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
Full Dropbox access, `files.content.write` permission) and an OAuth2
refresh-token flow run once to obtain `DROPBOX_REFRESH_TOKEN`. Do not hardcode
these values in the script.

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
- `get_period_allocations(gid)` fetches the group's granted node-hour quota per
  period from `accountj -g <gid> -r 1 -c` (CSV output, values in seconds) rather
  than a hardcoded number. It reads the `SUBTHEMEPERIOD` rows (period `1` =
  zenki/前期, period `2` = kouki/後期), divides the `LIMIT` field by 3600 to get
  node-hours, and derives `zenkikan` as `zenki + kouki`. Note the allocation
  cap lives on the parent *subtheme* (e.g. `hp240019`'s parent is `hp260014`),
  not the group itself — `accountj`'s `GROUP` row typically shows `unlimited`.
  A period is only given a reference line on the graph when its allocation is
  `> 0`.
- `node_hours(gid, uid, start, end)` runs
  `pjstatj -s -u <uid> -g <gid> -t <term> -c > output.csv` for one `(gid, uid,
  period)` combination, reads the CSV with pandas, extracts `ELAPSE_TIM`
  (elapsed time, parsed as `HH:MM:SS` string slices) and `NANUM` (node count),
  and sums `elapsed_hours * nodes` to get node-hours. `ELAPSE_TIM` is cast to
  `str` before slicing so that queued/unrun jobs (empty `ELAPSE_TIM`, which
  pandas may infer as an all-NaN float column after `dropna()`) don't crash the
  `.str` accessor — this happens in practice for jobs with `ST == 'QUE'`.
- `output.csv` is a shared scratch file, overwritten and deleted on every
  `node_hours()` call — the script is not safe to run concurrently with itself.

## Editing notes

- To add/remove tracked users or groups, keep `uids`, `gids`, and `names` in sync
  (order-dependent zip), and add/update any per-group membership exception blocks
  (see above) if a group doesn't include every tracked `uid`.
- Allocation quotas are fetched live via `accountj`, not hardcoded — no manual
  update needed when a new fiscal year's allocation is granted.
- `labels` selects which `pjstatj -c` CSV columns are read; changing it requires
  matching the downstream column-index parsing of `ELAPSE_TIM` (fixed string
  slices `[0:4]`/`[5:7]`/`[8:10]` assume `HHHH:MM:SS`-style formatting).
