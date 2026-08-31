# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This directory contains a single script, `used_resource.py`, for tracking compute
resource usage (node-hours) on the Fugaku supercomputer (Fujitsu FX1000/PJM
environment). It shells out to `pjstatj` (Fujitsu's job accounting CLI) to pull
per-user job statistics for one or more group IDs (`gid`) and computes total
node-hours consumed per user and per group over a date range.

## Running the script

```bash
python3 used_resource.py
```

No arguments — the date range, user IDs, group IDs, and user IDs are hardcoded at
the top of the file. Requires `pandas` and a working `pjstatj` on PATH (present at
`/usr/local/bin/pjstatj` on this system).

## How it works

- `term_start`/`term_end` define the accounting period (`YYYYMMDD:YYYYMMDD`);
  `term_end` defaults to today.
- `uids`/`gids`/`names` are parallel lists mapping Fugaku user IDs to group IDs and
  display names (`users = dict(zip(uids, names))`).
- For each `gid`, the script has hardcoded per-group membership exceptions (e.g.
  `<gid1>` excludes `<uid4>`; `<gid2>` only includes `<uid1>`/`<uid4>`) — these
  `if`/`continue` blocks must be updated by hand when group membership changes.
- For each remaining `(gid, uid)` pair it runs
  `pjstatj -s -u <uid> -g <gid> -t <term> -c > output.csv`, reads the CSV with
  pandas, extracts `ELAPSE_TIM` (elapsed time, parsed as `HH:MM:SS` string slices)
  and `NANUM` (node count), and sums `elapsed_hours * nodes` to get node-hours per
  user, then sums across users for a group total.
- `output.csv` is a shared scratch file, overwritten each iteration and deleted
  after each `gid` loop — the script is not safe to run concurrently with itself.

## Editing notes

- To add/remove tracked users or groups, keep `uids`, `gids`, and `names` in sync
  (order-dependent zip), and check whether the per-group exception `if` blocks
  around line 26-31 need updating.
- `labels` selects which `pjstatj -c` CSV columns are read; changing it requires
  matching the downstream column-index parsing of `ELAPSE_TIM` (fixed string
  slices `[0:4]`/`[5:7]`/`[8:10]` assume `HHHH:MM:SS`-style formatting).
