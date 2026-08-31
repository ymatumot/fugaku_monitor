import pandas as pd
import subprocess
import datetime
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import dropbox

today = datetime.date.today()
#term_start = '20250401'
term_start = '20251001'
#term_end = '20230930'
term_end = today.strftime('%Y%m%d')
term = term_start+':'+term_end

#uids = ['<uid9>','<uid1>','<uid2>','<uid11>','<uid10>','<uid3>','<uid4>','<uid7>','<uid8>','<uid5>']
#gids = ['<gid1>','<gid2>']
#names = ['<user1>','Matsumoto','<user2>','<user3>','<user10>','<user4>','<user5>','<user6>','<user7>','<user8>']
uids = ['<uid1>','<uid2>','<uid3>','<uid4>','<uid5>','<uid6>']
gids = ['hp240019']
names = ['Matsumoto','<user2>','<user4>','<user5>','<user8>','<user9>']
users = dict(zip(uids,names))

#labels = ['ELAPSE_TIM','NRNUM']
labels = ['ELAPSE_TIM','NANUM']

dropbox_folder = '/FugakuMonitor'
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


fig, axes = plt.subplots(1, len(gids), figsize=(6*len(gids), 5), squeeze=False)
axes = axes[0]

for gid, ax in zip(gids, axes):
  node_hour = list()
  used_names = list()
  for uid in uids:

     get_csv = 'pjstatj -s -u '+uid+' -g '+gid+' -t '+term+' -c > '+'output.csv'
     subprocess.call(get_csv,shell=True)

     df = pd.read_csv('output.csv')
     df = df[labels].dropna()

     etime_h = df[labels[0]].astype(str).str[0:4].astype(float)
     etime_m = df[labels[0]].astype(str).str[5:7].astype(float)
     etime_s = df[labels[0]].astype(str).str[8:10].astype(float)
     etime = etime_h+etime_m/60.0+etime_s/3600.0
     node = df[labels[1]]
     node_hour.append((etime*node).sum())
     used_names.append(users[uid])
     print(users[uid]+': ',(etime*node).sum(),' (node*hour)')

  subprocess.call('rm output.csv',shell=True)
  total = sum(node_hour)
  print('total used recources of '+gid+' as of '+today.strftime('%y/%m/%d')+': ',total,' (node*hour)')

  ax.bar(used_names, node_hour)
  ax.set_title(gid+'  total: {:.1f} node*hour'.format(total))
  ax.set_ylabel('node*hour')
  ax.tick_params(axis='x', rotation=45)

fig.suptitle('Fugaku resource usage as of '+today.strftime('%Y-%m-%d')+' (since '+term_start+')')
fig.tight_layout()
fig.savefig(image_path)
plt.close(fig)
print('saved graph: '+image_path)

upload_to_dropbox(image_path, dropbox_folder)
