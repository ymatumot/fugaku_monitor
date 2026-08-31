import getpass
import requests

app_key = getpass.getpass('App key: ')
app_secret = getpass.getpass('App secret: ')
code = getpass.getpass('Authorization code: ')

resp = requests.post(
    'https://api.dropbox.com/oauth2/token',
    data={
        'code': code,
        'grant_type': 'authorization_code',
        'client_id': app_key,
        'client_secret': app_secret,
    },
)

data = resp.json()
if 'refresh_token' in data:
    print()
    print('refresh_token:', data['refresh_token'])
else:
    print()
    print('Error response:', data)
