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
- On the server the key is limited to one command (`deploy.sh`). It cannot open
  a shell, forward ports or copy files, and `deploy.sh` accepts nothing but a
  commit SHA that is already on `main`.
- `.env` stays on the server and never goes through GitHub.

The server runs the app as `ubuntu` from `/home/ubuntu/work` (the repository
root, with `.env`) and `/home/ubuntu/work/work` (`app.py`), as the systemd
service `webapp`.

## 1. On the server: check the git checkout

`deploy.sh` fetches the approved commit into `~/work` with git, so `~/work` must
be a clone of this repository:

```shell
cd ~/work
git remote -v          # origin must point to github.com/MG-ng/DF-Insights.de
git status --short     # should list no modified tracked files (" M" lines)
```

The deploy runs `git checkout --force`, which overwrites local changes to
tracked files. `.env`, the virtualenv and `work/.cache` are untracked and ignored,
so they stay untouched. Commit or remove any other local edits first.

## 2. On the server: check the settings `deploy.sh` assumes

```shell
systemctl cat webapp
```

Look at `ExecStart` and `WorkingDirectory`:

- **Virtualenv.** `deploy.sh` assumes `/home/ubuntu/work/.venv`. If Gunicorn
  starts from a different path, e.g. `/home/ubuntu/venv/bin/gunicorn`, set it in
  the config file below.
- **Port.** The health check calls `http://127.0.0.1:5000/about`. If Gunicorn
  binds to a different port (`--bind`), set `HEALTH_URL`.

Only if something differs, create `~/.config/df-insights-deploy.env`, for example:

```shell
mkdir -p ~/.config
cat > ~/.config/df-insights-deploy.env <<'EOF'
VENV="/home/ubuntu/venv"
HEALTH_URL="http://127.0.0.1:8000/about"
EOF
```

Then check two more things:

```shell
sudo -n systemctl restart webapp && echo "sudo ok"   # must work without a password prompt
grep APP_VERSION ~/work/.env                          # must print nothing
```

- If the restart asks for a password, allow just this one command with
  `sudo visudo -f /etc/sudoers.d/df-insights-deploy` and this line:
  `ubuntu ALL=(root) NOPASSWD: /usr/bin/systemctl restart webapp`
- If `.env` sets `APP_VERSION`, remove the line. The footer must show the commit
  that git reports, or the deploy check fails.

## 3. On the server: install the deploy script

Install the script outside the checkout, so a deploy never changes it while it runs:

```shell
mkdir -p ~/bin
install -m 755 ~/work/.github/deploy/deploy.sh ~/bin/df-insights-deploy
```

When `deploy.sh` changes in the repo later, update the installed copy straight
from `main`. This works even though deploys leave `~/work` on a detached commit,
where `git pull` refuses to run:

```shell
git -C ~/work fetch origin main
git -C ~/work show origin/main:.github/deploy/deploy.sh > /tmp/df-insights-deploy
install -m 755 /tmp/df-insights-deploy ~/bin/df-insights-deploy
```

## 4. On your own computer: create the deploy key

```shell
ssh-keygen -t ed25519 -N "" -C "github-actions-deploy" -f df-insights-deploy
cat df-insights-deploy.pub
```

On the server, add **one line** to `~/.ssh/authorized_keys`: the forced command,
then the public key. Leave your existing keys as they are.

```text
command="/home/ubuntu/bin/df-insights-deploy",restrict ssh-ed25519 AAAA...your-public-key... github-actions-deploy
```

Test it from your computer. It should refuse with
`expected a full commit SHA`, which proves the key can't do anything else:

```shell
ssh -i df-insights-deploy ubuntu@<server> whoami
```

Get the server's host key line for GitHub. Use the same host name or IP you log in
with:

```shell
ssh-keyscan -t ed25519 <server>
```

Check that the fingerprint matches the server. These two commands must print
the same `SHA256:...`:

```shell
ssh-keyscan -t ed25519 <server> | ssh-keygen -lf -      # on your computer
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub        # on the server
```

## 5. In GitHub: create the `production` environment

Repository **Settings → Environments → New environment**, name `production`:

- **Required reviewers:** add yourself (`MG-ng`).
- **Deployment branches and tags:** "Selected branches and tags", add `main`.
- **Environment secrets:**

| Secret               | Value                                                    |
|----------------------|----------------------------------------------------------|
| `DEPLOY_SSH_KEY`     | the whole content of the private key file `df-insights-deploy` |
| `DEPLOY_KNOWN_HOSTS` | the line printed by `ssh-keyscan -t ed25519 <server>`, using the same name as `DEPLOY_HOST` |

- **Environment variables** (not secret, so GitHub does not mask them in logs):

| Variable      | Value                                  |
|---------------|----------------------------------------|
| `DEPLOY_HOST` | the server's host name, e.g. `df-insights.de` |
| `DEPLOY_USER` | `ubuntu`                               |

The `DEPLOY_KNOWN_HOSTS` line starts with the name(s) SSH may use for the server.
It must contain the `DEPLOY_HOST` value. To allow both the domain and the IP,
list both, separated by a comma: `df-insights.de,203.0.113.7 ssh-ed25519 AAAA...`

Then delete the private key file from your computer. GitHub has the only copy
it needs. If the key ever leaks, remove its line from `authorized_keys` and
repeat step 4.

## 6. First deploy

**Actions → Deploy → Run workflow** (branch `main`), then approve it under
"Review deployments". The job log shows each step from the server and the smoke
test result.

## Day to day

- **Deploy:** merge a PR into `main`. When CI is green, the Deploy run waits for
  your approval.
- **Roll back by hand:** run `~/bin/df-insights-deploy <full-sha>` on the server
  with an older commit from `main`.
- **Nightly check:** the *Production check* workflow fails when the site is
  down or does not run the latest commit on `main`, for example when a deploy is
  still waiting for approval. Missing security headers show up as warnings until
  nginx sets them.
