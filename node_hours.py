import pandas as pd
import subprocess
import datetime
import os
import csv

import resource_common as common
import matplotlib.pyplot as plt

today = datetime.date.today()

#labels = ['ELAPSE_TIM','NRNUM']
labels = ['ELAPSE_TIM','NANUM']

dropbox_folder = ''  # app-folder access: uploads go to the app's own dedicated Dropbox folder
image_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'node_hours_'+today.strftime('%Y%m%d')+'.png',
)

GID = 'hp240019'  # the only Fugaku group tracked so far; accounts.csv's
                  # "group" column is a subgroup label, not this id --
                  # per-gid tracking from accounts.csv is a future addition

dbx = common.get_dropbox_client()
uids, names, groups, uid_group = common.load_accounts(dbx, dropbox_folder)
users = dict(zip(uids,names))
color_map = common.build_color_map(uids, users)
group_color_map = common.build_group_color_map(groups)

# fiscal-year periods: zenki (前期) = Apr-Sep, kouki (後期) = Oct-Mar
fiscal_year = today.year if today.month >= 4 else today.year - 1
zenki_start = datetime.date(fiscal_year, 4, 1)
zenki_end = datetime.date(fiscal_year, 9, 30)
kouki_start = datetime.date(fiscal_year, 10, 1)
kouki_end = datetime.date(fiscal_year + 1, 3, 31)

periods = [
    ('zenki', '前期', zenki_start, zenki_end),
    ('kouki', '後期', kouki_start, kouki_end),
    ('zenkikan', '全期間', zenki_start, kouki_end),
]


def group_node_hours_pjstatj(gid, start, end):
    # exact query over an explicit date range, one call for the whole group --
    # only used to pin down the (by then finalized) zenki totals once kouki
    # has started, since the fast accountj path below only reports a
    # fiscal-year-to-date total. Returns {uid: node-hours}.
    if start > today:
        return {}
    term = start.strftime('%Y%m%d')+':'+min(end, today).strftime('%Y%m%d')
    get_csv = 'pjstatj -s -g '+gid+' -t '+term+' -c > '+'output.csv'
    subprocess.call(get_csv,shell=True)

    df = pd.read_csv('output.csv')
    df = df[['USER']+labels].dropna()
    subprocess.call('rm output.csv',shell=True)

    etime_h = df[labels[0]].astype(str).str[0:4].astype(float)
    etime_m = df[labels[0]].astype(str).str[5:7].astype(float)
    etime_s = df[labels[0]].astype(str).str[8:10].astype(float)
    etime = etime_h+etime_m/60.0+etime_s/3600.0
    df['node_hour'] = etime*df[labels[1]]
    return df.groupby('USER')['node_hour'].sum().to_dict()


def get_group_user_node_hours(gid):
    # fast: fiscal-year-to-date node-hours per user, from accountj -E (values in seconds)
    output = subprocess.check_output(['accountj','-g',gid,'-E','-r','1','-c'], text=True)
    usage = {}
    for row in csv.reader(output.splitlines()):
        if row and row[0] == 'USER':
            usage[row[1]] = float(row[3])/3600.0
    return usage


def get_period_stats(gid):
    # {period_key: {'limit': node-hours, 'usage': node-hours}} from accountj (values in seconds)
    output = subprocess.check_output(['accountj','-g',gid,'-r','1','-c'], text=True)
    stats = {}
    for row in csv.reader(output.splitlines()):
        if row and row[0] == 'SUBTHEMEPERIOD':
            limit_sec = float(row[3])
            usage_sec = float(row[4]) if row[4] != '---' else 0.0
            key = 'zenki' if row[2] == '1' else 'kouki'
            stats[key] = {'limit': limit_sec/3600.0, 'usage': usage_sec/3600.0}
    stats.setdefault('zenki', {'limit': 0.0, 'usage': 0.0})
    stats.setdefault('kouki', {'limit': 0.0, 'usage': 0.0})
    stats['zenkikan'] = {
        'limit': stats['zenki']['limit']+stats['kouki']['limit'],
        'usage': stats['zenki']['usage']+stats['kouki']['usage'],
    }
    return stats


period_stats = get_period_stats(GID)
ytd_usage = get_group_user_node_hours(GID)
if today < kouki_start:
   zenki_usage = ytd_usage
else:
   zenki_usage = group_node_hours_pjstatj(GID, zenki_start, zenki_end)

node_hour_results = dict()
for uid in uids:
   ytd = ytd_usage.get(uid, 0.0)
   zenki = zenki_usage.get(uid, 0.0)
   kouki = 0.0 if today < kouki_start else max(ytd-zenki, 0.0)
   node_hour_results[(uid,'zenki')] = zenki
   node_hour_results[(uid,'kouki')] = kouki
   node_hour_results[(uid,'zenkikan')] = ytd
   for key, label, start, end in periods:
      print(GID+' '+label+' '+users[uid]+': ',node_hour_results[(uid,key)],' (node*hour)')

fig, axes = plt.subplots(2, len(periods), figsize=(6*len(periods), 10))

for p, (key, label, start, end) in enumerate(periods):
   user_values = [(users[uid], node_hour_results[(uid,key)]) for uid in uids]
   tracked_total = sum(v for _, v in user_values)
   group_usage = period_stats[key]['usage']
   others = max(group_usage-tracked_total, 0.0)
   print(GID+' '+label+' total (tracked): ',tracked_total,' (node*hour), group total: ',group_usage,' (node*hour)')
   limit = period_stats[key]['limit']
   unused = max(limit-group_usage, 0.0)
   title = label+'\n使用 {:,.0f} / 割当 {:,.0f} node*hour'.format(group_usage, limit)
   top, other_total = common.top_n_or_other(user_values, others)
   values = [v for _, v in top]+[other_total, unused]
   pie_labels = [l for l, _ in top]+['その他','未使用']
   common.pie_or_placeholder(axes[0, p], values, pie_labels, title, color_map)

   subgroup_totals = {}
   for uid in uids:
      subgroup_totals.setdefault(uid_group[uid], 0.0)
      subgroup_totals[uid_group[uid]] += node_hour_results[(uid,key)]
   subgroup_values = list(subgroup_totals.items())
   subgroup_title = label+' (グループ別)\n使用 {:,.0f} / 割当 {:,.0f} node*hour'.format(group_usage, limit)
   sub_top, sub_other_total = common.top_n_or_other(subgroup_values, others)
   sub_values = [v for _, v in sub_top]+[sub_other_total, unused]
   sub_pie_labels = [l for l, _ in sub_top]+['その他','未使用']
   common.pie_or_placeholder(axes[1, p], sub_values, sub_pie_labels, subgroup_title, group_color_map)

fig.suptitle(GID+' node-hour usage as of '+today.strftime('%Y-%m-%d')+' (by fiscal-year period; top row per-user, bottom row per-group)')
fig.tight_layout()
fig.savefig(image_path)
plt.close(fig)
print('saved graph: '+image_path)

common.upload_to_dropbox(dbx, image_path, dropbox_folder)
os.remove(image_path)
