# Deploy setup (one time)

After this setup, every push to `main` that passes CI starts the **Deploy**
workflow. It waits until you approve it in GitHub, then connects to the server
over SSH and runs `deploy.sh` there. `deploy.sh` checks out the commit, installs
the requirements, restarts Gunicorn and checks that the app answers with the new
version. If anything fails it rolls back to the previous commit. A smoke test
against https://df-insights.de runs at the end, and again every night.

How the credentials stay private, even though the repo is public:

- The SSH key exists only as an encrypted secret of the GitHub `production`
  environment. It is never in the repo, GitHub masks it in logs, and workflows
  triggered by pull requests from forks never get it.
- Only `main` may use the environment, and every deploy needs your approval.
- On the server the key belongs to a dedicated `deploy` user and is limited to
  one command (`deploy.sh`). It cannot open a shell, forward ports or copy files,
  and `deploy.sh` accepts nothing but a commit SHA that is already on `main`.
- `.env` stays on the server and never goes through GitHub.

## Who does what on the server

| User             | Owns / may do                                                                   |
|------------------|---------------------------------------------------------------------------------|
| `deploy`         | owns `/srv/df-insights` (checkout, `.venv`); may restart `webapp` and nothing else with `sudo`; holds the GitHub Actions key |
| `flask-gunicorn` | runs the `webapp` service; can **read** the code and `.env`, write nothing      |
| `ubuntu`         | your admin login with full `sudo`; no deploy key                                |

If the deploy key or `deploy.sh` were ever abused, the attacker would be
`deploy`: no `sudo` beyond restarting the app, no access to your `ubuntu` files.

The app lives in `/srv/df-insights` (repository root with `.env`) and
`/srv/df-insights/work` (`app.py`), and runs as the systemd service `webapp`.

## Moving an existing `ubuntu` setup to the `deploy` user

If the app currently runs from `/home/ubuntu/work` and the deploy key sits in
`ubuntu`'s `authorized_keys`, do steps 1 to 7 below in order. The old folder
stays untouched until step 7, so you can switch back at any point by removing
the systemd override from step 4 (`sudo systemctl revert webapp`).

Find out first whether import jobs run from cron, because they will need the new
path too:

```shell
crontab -l; sudo crontab -l; sudo crontab -u flask-gunicorn -l   # look for /home/ubuntu/work
```

## 1. Create the `deploy` user

```shell
sudo adduser --system --group --home /home/deploy --shell /bin/bash deploy
```

`--system` gives it no password, so nobody can log in with one. The shell must
be a real shell (not `nologin`) because SSH runs the forced command through it.

## 2. Create the checkout in `/srv/df-insights`

```shell
sudo install -d -o deploy -g deploy -m 755 /srv/df-insights
sudo -u deploy git clone https://github.com/MG-ng/DF-Insights.de.git /srv/df-insights
sudo -u deploy python3 -m venv /srv/df-insights/.venv
sudo -u deploy /srv/df-insights/.venv/bin/pip install -r /srv/df-insights/work/requirements.txt gunicorn
```

Copy `.env` so that `deploy` owns it and the web server can only read it:

```shell
sudo install -o deploy -g flask-gunicorn -m 640 /home/ubuntu/work/.env /srv/df-insights/.env
sudo grep APP_VERSION /srv/df-insights/.env    # must print nothing
```

If `APP_VERSION` is set there, delete that line; the footer version comes from
`.app-version`, which `deploy.sh` writes.

If the import jobs use the API cache, copy it as well (optional, it only saves
downloads):

```shell
sudo cp -a /home/ubuntu/work/work/.cache /srv/df-insights/work/ && sudo chown -R deploy:deploy /srv/df-insights/work/.cache
```

## 3. Allow `deploy` to restart the app, and nothing else

```shell
echo 'deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart webapp' | sudo tee /etc/sudoers.d/df-insights-deploy
sudo chmod 440 /etc/sudoers.d/df-insights-deploy
sudo visudo -c                                       # must say "parsed OK"
sudo -u deploy sudo -n systemctl restart webapp && echo "sudo ok"
```

## 4. Point the `webapp` service at the new folder

```shell
sudo systemctl edit webapp
```

Add these lines in the editor (the empty `ExecStart=` clears the old command
first, systemd needs that):

```ini
[Service]
WorkingDirectory=/srv/df-insights/work
ExecStart=
ExecStart=/srv/df-insights/.venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 app:app
```

Keep `User=flask-gunicorn` as it is. Then:

```shell
sudo systemctl restart webapp
curl -s http://127.0.0.1:5000/about | grep -o 'Version [^<]*'
```

The page must answer. The version shows the commit once the first deploy has
written `.app-version` (until then it may say `unknown`).

## 5. Install the deploy script and move the key

```shell
sudo -u deploy install -d -m 700 /home/deploy/bin /home/deploy/.ssh
sudo install -o deploy -g deploy -m 755 /srv/df-insights/.github/deploy/deploy.sh /home/deploy/bin/df-insights-deploy
```

Move the GitHub Actions key line out of `/home/ubuntu/.ssh/authorized_keys` (the
one ending in `github-actions-deploy`) into the new user's file, with the new
script path:

```shell
sudo -u deploy nano /home/deploy/.ssh/authorized_keys
```

```text
command="/home/deploy/bin/df-insights-deploy",restrict ssh-ed25519 AAAA...same-public-key... github-actions-deploy
```

```shell
sudo chmod 600 /home/deploy/.ssh/authorized_keys
nano ~/.ssh/authorized_keys      # as ubuntu: delete the github-actions-deploy line
```

The key itself and `DEPLOY_SSH_KEY` / `DEPLOY_KNOWN_HOSTS` in GitHub stay the same.
If you no longer have the public key, recreate the line from the private key's
`.pub` file, or make a new key pair as in "New deploy key" below.

## 6. In GitHub: switch the user, then deploy

Settings → Environments → production → Variables: set `DEPLOY_USER` to `deploy`.
Then **Actions → Deploy → Run workflow** and approve it. The log should end with
`deployed <commit>` and a green smoke test.

## 7. Clean up

Once the deploy worked:

- Point any cron import jobs at `/srv/df-insights` and run them as `deploy`, e.g.
  `sudo -u deploy /srv/df-insights/.venv/bin/python -u /srv/df-insights/work/databaseSetupAll.py ...`
- Remove the old copy: `rm -rf /home/ubuntu/work` (keep a backup first if you like).
- Remove the old sudo rule for `ubuntu` from `/etc/sudoers.d/df-insights-deploy`
  if you had added one; the file should only contain the `deploy` line.

## Automatic data updates

`work/updateDatabase.py` fetches only what is new since its last run (SMARD
power data, Open-Meteo weather and previous-run forecasts) and refreshes the
materialized views with `REFRESH ... CONCURRENTLY`, so the website keeps
answering during the refresh. Then it writes the Colab datasets
`work/static/data.h5` and `work/static/data-<model>.h5`, served at
https://df-insights.de/static/data.h5. They are untracked, so deploys keep them. It needs a database that `databaseSetupAll.py`
has set up once. A systemd timer runs it four times a day (00:15, 06:15, 12:15
and 18:15 UTC) as `deploy`, from the checkout, so a deploy also updates the job.

Install it once (as `ubuntu`):

```shell
sudo -u deploy install -d -m 755 /srv/df-insights/work/.cache
sudo install -m 644 /srv/df-insights/.github/deploy/df-insights-update.service /srv/df-insights/.github/deploy/df-insights-update.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start df-insights-update.service     # first run by hand; catches up everything since the last import
journalctl -u df-insights-update.service -n 50      # should end with "Update completed"
sudo systemctl enable --now df-insights-update.timer
systemctl list-timers df-insights-update.timer      # shows the next run
```

The first run after a long pause catches up the whole gap and can take a while;
later runs take a few minutes, mostly for the view refresh. If the app still runs
from `/home/ubuntu/work`, point the unit at it with
`sudo systemctl edit df-insights-update.service`:

```ini
[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/work
ExecStart=
ExecStart=/home/ubuntu/work/.venv/bin/python -u /home/ubuntu/work/work/updateDatabase.py
ReadWritePaths=
ReadWritePaths=-/home/ubuntu/work/work/.cache /home/ubuntu/work/work/static
ProtectHome=false
```

Day to day:

- **Logs:** `journalctl -u df-insights-update.service --since today`
- **Update now:** `sudo systemctl start df-insights-update.service`
- **Only rebuild data.h5:** `sudo -u deploy /srv/df-insights/.venv/bin/python -u /srv/df-insights/work/exportColabData.py`
- **Refetch a period** (e.g. after SMARD corrected older data):
  `sudo -u deploy /srv/df-insights/.venv/bin/python -u /srv/df-insights/work/updateDatabase.py --since 2026-06-01`
- **Pause it** during a full rebuild with `databaseSetupAll.py`:
  `sudo systemctl stop df-insights-update.timer`, and `start` it again afterwards.
  Two updates never run at the same time; a second one exits right away.
- If the units change in the repo, copy them again as above and run
  `sudo systemctl daemon-reload`.

## New deploy key (only for a fresh setup or after a leak)

```shell
ssh-keygen -t ed25519 -N "" -C "github-actions-deploy" -f df-insights-deploy
cat df-insights-deploy.pub        # goes into /home/deploy/.ssh/authorized_keys (step 5)
```

Test it from your computer. It should refuse with `expected a full commit SHA`,
which proves the key can't do anything else:

```shell
ssh -i df-insights-deploy deploy@<server> whoami
```

Put the private key into the `DEPLOY_SSH_KEY` secret, then delete the file from
your computer. If the key ever leaks, delete its line from
`/home/deploy/.ssh/authorized_keys` and create a new one.

## GitHub `production` environment

Repository **Settings → Environments → production**:

- **Required reviewers:** yourself (`MG-ng`).
- **Deployment branches and tags:** "Selected branches and tags", branch `main`.
- **Environment secrets:**

| Secret               | Value                                                    |
|----------------------|----------------------------------------------------------|
| `DEPLOY_SSH_KEY`     | the whole content of the private key file `df-insights-deploy` |
| `DEPLOY_KNOWN_HOSTS` | the server's host key line, see below                    |

- **Environment variables** (not secret, so GitHub does not mask them in logs):

| Variable      | Value                                         |
|---------------|-----------------------------------------------|
| `DEPLOY_HOST` | the server's host name, e.g. `df-insights.de` |
| `DEPLOY_USER` | `deploy`                                      |

`DEPLOY_KNOWN_HOSTS` is the line printed by `ssh-keyscan -t ed25519 <server>`. It
starts with the name(s) SSH may use for the server and must contain the
`DEPLOY_HOST` value. To allow both the domain and the IP, list both, separated by
a comma: `df-insights.de,203.0.113.7 ssh-ed25519 AAAA...`

Check that the fingerprint matches the server. These two commands must print the
same `SHA256:...`:

```shell
ssh-keyscan -t ed25519 <server> | ssh-keygen -lf -      # on your computer
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub        # on the server
```

## Settings `deploy.sh` assumes

The defaults at the top of `deploy.sh` match the steps above: checkout
`/srv/df-insights`, virtualenv `/srv/df-insights/.venv`, service `webapp`, health
check `http://127.0.0.1:5000/about`. If something differs, override it in
`/home/deploy/.config/df-insights-deploy.env` (owned by `deploy`, mode 600), e.g.:

```shell
HEALTH_URL="http://127.0.0.1:8000/about"
```

## Day to day

- **Deploy:** merge a PR into `main`. When CI is green, the Deploy run waits for
  your approval.
- **Roll back by hand:** `sudo -u deploy /home/deploy/bin/df-insights-deploy <full-sha>`
  with an older commit from `main`.
- **Look at the code on the server:** `sudo -u deploy git -C /srv/df-insights log -3`.
  Don't edit files there; the next deploy overwrites tracked files.
- **When `deploy.sh` changes in the repo**, update the installed copy:

  ```shell
  sudo -u deploy git -C /srv/df-insights fetch origin main
  sudo -u deploy git -C /srv/df-insights show origin/main:.github/deploy/deploy.sh > /tmp/df-insights-deploy
  sudo install -o deploy -g deploy -m 755 /tmp/df-insights-deploy /home/deploy/bin/df-insights-deploy
  ```

- **Nightly check:** the *Production check* workflow fails when the site is down
  or does not run the latest commit on `main`, for example when a deploy is still
  waiting for approval.
