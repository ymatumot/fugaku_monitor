import pandas as pd
import subprocess
import datetime
import os
import csv
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['font.family'] = ['DejaVu Sans', 'Droid Sans Japanese']
import matplotlib.pyplot as plt
plt.style.use('ggplot')
import dropbox

today = datetime.date.today()

#labels = ['ELAPSE_TIM','NRNUM']
labels = ['ELAPSE_TIM','NANUM']

dropbox_folder = ''  # app-folder access: uploads go to the app's own dedicated Dropbox folder
image_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'resource_usage_'+today.strftime('%Y%m%d')+'.png',
)


def get_dropbox_client():
    return dropbox.Dropbox(
        oauth2_refresh_token=os.environ['DROPBOX_REFRESH_TOKEN'],
        app_key=os.environ['DROPBOX_APP_KEY'],
        app_secret=os.environ['DROPBOX_APP_SECRET'],
    )


def load_accounts(dbx, folder):
    # accounts.csv rows: uid,name,gid -- one row per tracked user. Downloaded
    # fresh from Dropbox on every run (no local copy is kept) so accounts can
    # be added/removed without touching the script.
    remote_path = folder+'/accounts.csv'
    _, res = dbx.files_download(remote_path)

    uids, names, gids = [], [], []
    uid_gid = {}
    for row in csv.reader(res.content.decode('utf-8').splitlines()):
        if not row:
            continue
        uid, name, gid = row[0].strip(), row[1].strip(), row[2].strip()
        uids.append(uid)
        names.append(name)
        uid_gid[uid] = gid
        if gid not in gids:
            gids.append(gid)
    return uids, names, gids, uid_gid


dbx = get_dropbox_client()
uids, names, gids, uid_gid = load_accounts(dbx, dropbox_folder)
users = dict(zip(uids,names))

# fixed slice colors: each tracked user + その他 get the ggplot cycle colors,
# 未使用 is always gray, regardless of which slices are present in a given pie
_cycle = plt.rcParams['axes.prop_cycle'].by_key()['color']
color_map = {name: _cycle[i % len(_cycle)] for i, name in enumerate(names+['その他'])}
color_map['未使用'] = 'gray'

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

def upload_to_dropbox(dbx, local_path, folder):
    dest_path = folder+'/'+os.path.basename(local_path)
    with open(local_path, 'rb') as f:
        dbx.files_upload(f.read(), dest_path, mode=dropbox.files.WriteMode.overwrite)
    print('uploaded to Dropbox: '+dest_path)


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


def get_group_disk_usage(gid):
    # {volume: {'limit': GiB, 'usage': GiB}} -- only volumes with a group quota
    output = subprocess.check_output(['accountd','-g',gid,'-c'], text=True)
    result = {}
    for row in csv.reader(output.splitlines()):
        if row and row[0] == 'GROUP':
            result[row[2]] = {'limit': float(row[3]), 'usage': float(row[4])}
    return result


def get_user_disk_usage(gid):
    # {(volume, uid): GiB}
    output = subprocess.check_output(['accountd','-g',gid,'-m','-c'], text=True)
    result = {}
    for row in csv.reader(output.splitlines()):
        if row and row[0] == 'USER':
            result[(row[1],row[2])] = float(row[4])
    return result


TOP_N = 5


def top_n_or_other(pairs, other_value, n=TOP_N, other_label='その他'):
    # pairs: list of (label, value) for tracked users in this pie. Keeps the
    # top n by value under their own name and folds the rest (plus
    # other_value, the already-computed rest-of-group total) into a single
    # other_label total -- so as more users get tracked over time, a pie
    # never shows more than n+2 slices (top n + その他 + 未使用).
    pairs_sorted = sorted(pairs, key=lambda x: x[1], reverse=True)
    top = pairs_sorted[:n]
    rest = pairs_sorted[n:]
    other_total = other_value + sum(v for _, v in rest)
    return top, other_total


def pie_or_placeholder(ax, values, pie_labels, title):
    pairs = [(v,l) for v,l in zip(values, pie_labels) if v > 0]
    ax.set_title(title)
    if not pairs:
        ax.text(0.5, 0.5, '利用なし', ha='center', va='center', transform=ax.transAxes)
        ax.axis('off')
        return
    vs = [p[0] for p in pairs]
    ls = [p[1] for p in pairs]
    total = sum(vs)
    def autopct(pct):
        if pct < 1.0:
            return ''
        return '{:.1f}%\n({:,.0f})'.format(pct, pct/100.0*total)
    colors = [color_map[l] for l in ls]
    wedges, _, _ = ax.pie(vs, autopct=autopct, pctdistance=0.75, colors=colors,
                           startangle=90, counterclock=False)
    ax.legend(wedges, ls, loc='center left', bbox_to_anchor=(1.0, 0.5), fontsize='small')


for gid in gids:
  group_uids = [uid for uid in uids if uid_gid[uid] == gid]
  period_stats = get_period_stats(gid)
  ytd_usage = get_group_user_node_hours(gid)
  if today < kouki_start:
     zenki_usage = ytd_usage
  else:
     zenki_usage = group_node_hours_pjstatj(gid, zenki_start, zenki_end)

  node_hour_results = dict()
  for uid in group_uids:
     ytd = ytd_usage.get(uid, 0.0)
     zenki = zenki_usage.get(uid, 0.0)
     kouki = 0.0 if today < kouki_start else max(ytd-zenki, 0.0)
     node_hour_results[(uid,'zenki')] = zenki
     node_hour_results[(uid,'kouki')] = kouki
     node_hour_results[(uid,'zenkikan')] = ytd
     for key, label, start, end in periods:
        print(gid+' '+label+' '+users[uid]+': ',node_hour_results[(uid,key)],' (node*hour)')

  volumes_info = get_group_disk_usage(gid)
  user_disk = get_user_disk_usage(gid)
  volumes = list(volumes_info.keys())

  fig, axes = plt.subplots(2, max(len(periods),len(volumes)), figsize=(6*max(len(periods),len(volumes)), 10))

  for p, (key, label, start, end) in enumerate(periods):
     user_values = [(users[uid], node_hour_results[(uid,key)]) for uid in group_uids]
     tracked_total = sum(v for _, v in user_values)
     group_usage = period_stats[key]['usage']
     others = max(group_usage-tracked_total, 0.0)
     print(gid+' '+label+' total (tracked): ',tracked_total,' (node*hour), group total: ',group_usage,' (node*hour)')
     limit = period_stats[key]['limit']
     unused = max(limit-group_usage, 0.0)
     title = label+'\n使用 {:,.0f} / 割当 {:,.0f} node*hour'.format(group_usage, limit)
     top, other_total = top_n_or_other(user_values, others)
     values = [v for _, v in top]+[other_total, unused]
     pie_labels = [l for l, _ in top]+['その他','未使用']
     pie_or_placeholder(axes[0][p], values, pie_labels, title)

  for p in range(len(periods), axes.shape[1]):
     axes[0][p].axis('off')

  for v, volume in enumerate(volumes):
     user_values = [(users[uid], user_disk.get((volume,uid),0.0)) for uid in group_uids]
     tracked_total = sum(val for _, val in user_values)
     vol_usage = volumes_info[volume]['usage']
     others = max(vol_usage-tracked_total, 0.0)
     limit = volumes_info[volume]['limit']
     unused = max(limit-vol_usage, 0.0)
     title = volume+'\n使用 {:,.0f} / 割当 {:,.0f} GiB'.format(vol_usage, limit)
     top, other_total = top_n_or_other(user_values, others)
     values = [val for _, val in top]+[other_total, unused]
     pie_labels = [l for l, _ in top]+['その他','未使用']
     pie_or_placeholder(axes[1][v], values, pie_labels, title)

  for v in range(len(volumes), axes.shape[1]):
     axes[1][v].axis('off')

  fig.suptitle(gid+' resource usage as of '+today.strftime('%Y-%m-%d')+'\n(top: node-hours by period, bottom: disk usage by volume)')
  fig.tight_layout()
  fig.savefig(image_path)
  plt.close(fig)
  print('saved graph: '+image_path)

upload_to_dropbox(dbx, image_path, dropbox_folder)
os.remove(image_path)
