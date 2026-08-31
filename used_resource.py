import pandas as pd
import subprocess
import datetime
import os
import csv
import numpy as np
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['font.family'] = ['DejaVu Sans', 'Droid Sans Japanese']
import matplotlib.pyplot as plt
import dropbox

today = datetime.date.today()

uids = ['<uid1>','<uid2>']
gids = ['hp240019']
names = ['Matsumoto','<user2>']
users = dict(zip(uids,names))

#labels = ['ELAPSE_TIM','NRNUM']
labels = ['ELAPSE_TIM','NANUM']

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

dropbox_folder = ''  # app-folder access: uploads go to the app's own dedicated Dropbox folder
image_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'resource_usage_'+today.strftime('%Y%m%d')+'.png',
)


def upload_to_dropbox(local_path, folder):
    app_key = os.environ['DROPBOX_APP_KEY']
    app_secret = os.environ['DROPBOX_APP_SECRET']
    refresh_token = os.environ['DROPBOX_REFRESH_TOKEN']
    dbx = dropbox.Dropbox(
        oauth2_refresh_token=refresh_token,
        app_key=app_key,
        app_secret=app_secret,
    )
    dest_path = folder+'/'+os.path.basename(local_path)
    with open(local_path, 'rb') as f:
        dbx.files_upload(f.read(), dest_path, mode=dropbox.files.WriteMode.overwrite)
    print('uploaded to Dropbox: '+dest_path)


def node_hours(gid, uid, start, end):
    if start > today:
        return 0.0
    term = start.strftime('%Y%m%d')+':'+min(end, today).strftime('%Y%m%d')
    get_csv = 'pjstatj -s -u '+uid+' -g '+gid+' -t '+term+' -c > '+'output.csv'
    subprocess.call(get_csv,shell=True)

    df = pd.read_csv('output.csv')
    df = df[labels].dropna()
    subprocess.call('rm output.csv',shell=True)

    etime_h = df[labels[0]].astype(str).str[0:4].astype(float)
    etime_m = df[labels[0]].astype(str).str[5:7].astype(float)
    etime_s = df[labels[0]].astype(str).str[8:10].astype(float)
    etime = etime_h+etime_m/60.0+etime_s/3600.0
    node = df[labels[1]]
    return (etime*node).sum()


def get_period_allocations(gid):
    output = subprocess.check_output(['accountj','-g',gid,'-r','1','-c'], text=True)
    allocations = {}
    for row in csv.reader(output.splitlines()):
        if row and row[0] == 'SUBTHEMEPERIOD':
            limit_sec = float(row[3])
            if row[2] == '1':
                allocations['zenki'] = limit_sec/3600.0
            elif row[2] == '2':
                allocations['kouki'] = limit_sec/3600.0
    allocations.setdefault('zenki', 0.0)
    allocations.setdefault('kouki', 0.0)
    allocations['zenkikan'] = allocations['zenki']+allocations['kouki']
    return allocations


fig, axes = plt.subplots(len(gids), 1, figsize=(8, 5*len(gids)), squeeze=False)
axes = axes[:,0]

x = np.arange(len(periods))
width = 0.8/len(uids)

for gid, ax in zip(gids, axes):
  allocations = get_period_allocations(gid)
  results = dict()
  for uid in uids:
     for key, label, start, end in periods:
        nh = node_hours(gid, uid, start, end)
        results[(uid,key)] = nh
        print(gid+' '+label+' '+users[uid]+': ',nh,' (node*hour)')

  for i, uid in enumerate(uids):
     values = [results[(uid,key)] for key,label,start,end in periods]
     offset = (i-(len(uids)-1)/2)*width
     ax.bar(x+offset, values, width, label=users[uid])

  for p, (key, label, start, end) in enumerate(periods):
     total = sum(results[(uid,key)] for uid in uids)
     print(gid+' '+label+' total: ',total,' (node*hour)')
     allocation = allocations[key]
     if allocation > 0:
        ax.hlines(allocation, x[p]-0.4, x[p]+0.4, colors='red', linestyles='--')

  ax.set_xticks(x)
  ax.set_xticklabels([label for key,label,start,end in periods])
  ax.set_ylabel('node*hour')
  ax.set_title(gid)
  ax.legend()

fig.suptitle('Fugaku resource usage as of '+today.strftime('%Y-%m-%d')+' (red dashed line: allocation)')
fig.tight_layout()
fig.savefig(image_path)
plt.close(fig)
print('saved graph: '+image_path)

upload_to_dropbox(image_path, dropbox_folder)
