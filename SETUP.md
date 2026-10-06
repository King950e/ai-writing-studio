# AI Writing Studio: Setup from GitHub to the Live Website

When you finish, this is what you'll have:

| URL | Who can use it |
|---|---|
| `https://write.starwars.it.com/` | **Anyone.** Blog, email, captions, rewrite, repurpose |
| `https://write.starwars.it.com/jobs` | **Only you** (Cloudflare login). Resume and cover letter from your work history |

```
Visitor → Cloudflare (rate limit, + login for /jobs) → Tunnel on node2 → node3:5000 (web app) → Ollama on node3
```

The job tools stay private because they use your personal work history. If they were public, anyone could generate resumes with your name and email on them, and could make the AI write things in your name.

---

## Before you start

You need:

- [ ] GitHub account (`king950e`) and Git installed on your PC (`git --version`)
- [ ] Ansible control node that can already SSH to node3
- [ ] node3 running Ollama (`ollama list` works on node3)
- [ ] node2 running your Cloudflare Tunnel (the one serving todo.starwars.it.com)
- [ ] Your real `work_history.json` (the filled-in one, not the example)
- [ ] node3's IP, node2's IP, and node1's IP

---

## Step 1: Prepare the project on your PC

1. Unzip `ai-writing-studio.zip` somewhere **without `&` or spaces** in the path, for example `C:\Projects\ai-writing-studio`.
2. Make sure your real `work_history.json` is **not** inside this folder. Keep it somewhere else, like `C:\Projects\private\work_history.json`. The repo only gets `work_history.example.json`.
3. Optional local test (needs Ollama running on your PC):
   ```
   cd C:\Projects\ai-writing-studio
   pip install -r requirements.txt
   python app.py
   ```
   Open http://127.0.0.1:5000 and try Blog mode. Press Ctrl+C to stop. `/jobs` will say "private". That's expected, because there's no Cloudflare login on your PC.

## Step 2: Push it to GitHub

1. On github.com, click **New repository**:
   - Name: `ai-writing-studio`
   - **Public** (nothing secret goes in it, and the playbook can clone it without a password)
   - Do **not** add a README or .gitignore, because the project already has both.
2. On your PC:
   ```
   cd C:\Projects\ai-writing-studio
   git init
   git add .
   git status
   ```
3. **Check the `git status` list.** You should see app.py, cli/, deploy/, templates/, README.md, SETUP.md, requirements.txt, screenshot.png and work_history.example.json. If you see `work_history.json`, a `job.txt`, or any `*_output` file, **stop** and remove it from the folder first.
4. Commit and push:
   ```
   git commit -m "AI Writing Studio: web app, CLI tools, Ansible deploy"
   git branch -M main
   git remote add origin https://github.com/king950e/ai-writing-studio.git
   git push -u origin main
   ```
5. Refresh the GitHub page. The README and screenshot should show.

## Step 3: Get the playbook and your work history onto the control node

SSH into your Ansible control node, then:

1. Clone the repo next to your other playbooks:
   ```bash
   cd ~
   git clone https://github.com/king950e/ai-writing-studio.git
   cd ai-writing-studio/deploy
   ```
2. Copy your work history from your PC. Run this **on your PC**, in PowerShell, with your control node's IP:
   ```
   scp C:\Projects\private\work_history.json stunner@<control-node-IP>:~/ai-writing-studio/deploy/files/work_history.json
   ```
3. Back on the control node, encrypt it with Ansible Vault:
   ```bash
   ansible-vault encrypt files/work_history.json
   ```
   Choose a vault password you'll remember. `cat files/work_history.json` should now show `$ANSIBLE_VAULT;1.1;AES256...` instead of your info.
4. Make sure your inventory has node3 under that name, then test the connection:
   ```bash
   ansible -i <your-inventory> node3 -m ping
   ```

## Step 4: Fill in the playbook settings

Edit `deploy_writing_studio.yml` (`nano deploy_writing_studio.yml`) and set:

| Setting | Value |
|---|---|
| `repo_url` | `https://github.com/king950e/ai-writing-studio.git` |
| `node2_ip` | node2's IP |
| `cf_team_domain` | leave as `CHANGEME...` for now (Step 7) |
| `cf_access_aud` | leave as `CHANGEME` for now (Step 7) |

Leave `require_cf_access: "false"`. That's what makes the writing tools public.

## Step 5: Deploy to node3

1. Dry run first. It shows what would change without changing anything:
   ```bash
   ansible-playbook -i <your-inventory> deploy_writing_studio.yml --ask-vault-pass --check
   ```
   A few tasks may fail in check mode because earlier steps didn't really run, such as the pip install or the health check. That's normal for a first-time `--check`. What you're looking for is typos and connection errors.
2. Real run:
   ```bash
   ansible-playbook -i <your-inventory> deploy_writing_studio.yml --ask-vault-pass
   ```
   The first run can take a while if it has to pull qwen3.6 on node3.
3. **Read the end of the output.** If you see the UFW warning, the firewall on node3 is off. SSH to node3 and run:
   ```bash
   sudo ufw allow OpenSSH        # do this FIRST so you don't lock yourself out
   sudo ufw enable
   ```
4. Let node1 reach the app too, for monitoring in Step 9 (on node3):
   ```bash
   sudo ufw allow from <node1-IP> to any port 5000 proto tcp
   ```
5. Test from **node2** (the only other machine allowed in):
   ```bash
   curl http://<node3-IP>:5000/health        # {"status":"ok"}
   curl -s http://<node3-IP>:5000/ | head -5  # HTML for the page
   curl -s -o /dev/null -w "%{http_code}\n" http://<node3-IP>:5000/jobs   # 403 (private - correct)
   ```

If something fails, check it on node3:

```bash
sudo systemctl status writing-studio
sudo journalctl -u writing-studio -n 50
```

## Step 6: Put it on the internet (Cloudflare Tunnel)

**If your tunnel is managed in the Cloudflare dashboard:**

Zero Trust → **Networks → Tunnels** → your tunnel → **Public Hostname → Add a public hostname**:

| Field | Value |
|---|---|
| Subdomain | `write` |
| Domain | `starwars.it.com` |
| Path | *(empty)* |
| Type | `HTTP` |
| URL | `<node3-IP>:5000` |

Save. Cloudflare creates the DNS record for you.

**If your tunnel uses `config.yml` on node2:** add this above the `http_status:404` line:

```yaml
  - hostname: write.starwars.it.com
    service: http://<node3-IP>:5000
```

Then on node2:

```bash
cloudflared tunnel route dns <tunnel-name> write.starwars.it.com
sudo systemctl restart cloudflared
```

**Test:** open https://write.starwars.it.com on your phone with Wi-Fi off. Try Blog mode. The text should stream in.

## Step 7: Lock /jobs behind your login (Cloudflare Access)

1. Zero Trust → **Access → Applications → Add an application → Self-hosted**.
2. **Application name:** `Writing Studio - Job Tools`.
3. **Add two public hostnames** to the same application:
   - Subdomain `write`, Domain `starwars.it.com`, Path `jobs`
   - Subdomain `write`, Domain `starwars.it.com`, Path `api/job`
4. **Policy:** Name `Only me`, Action **Allow**, Include → **Emails** → `cantupre@gmail.com`.
5. **Login method:** One-time PIN (on by default).
6. Save. Then open the application again and copy two values:
   - **Application Audience (AUD) Tag**, a long string, usually under the application's Overview or Basic information
   - Your **team domain**, which looks like `something.cloudflareaccess.com`. It's under Settings → Custom pages or in the Zero Trust URL.
7. On the control node, put them in `deploy_writing_studio.yml`:
   ```yaml
   cf_team_domain: "something.cloudflareaccess.com"
   cf_access_aud: "the-long-aud-tag"
   ```
   Then re-run the playbook:
   ```bash
   ansible-playbook -i <your-inventory> deploy_writing_studio.yml --ask-vault-pass
   ```
8. **Test:**
   - Open https://write.starwars.it.com/jobs in a private window. You should get the Cloudflare login, then a code in your email, then the Job Application Tools page.
   - Paste the job posting, add the company name, and choose Full application.
   - In another private window, open https://write.starwars.it.com/. It should load **without** a login.

The app checks Cloudflare's login token itself, not just whether the header exists. Even a request that somehow skipped Cloudflare can't open `/jobs`.

## Step 8: Protect it from abuse (public site)

Anyone can now use the writing tools, so add these guards:

1. **Already in the app:** 10 requests per minute and 60 per day per visitor, a 4,000-character input limit, and a 64 KB request limit.
2. **Cloudflare rate-limit rule** (free plan allows one). Go to your domain → **Security → WAF → Rate limiting rules → Create rule**:
   - Match: Hostname equals `write.starwars.it.com` **AND** URI Path equals `/api/generate`
   - Characteristics: **IP**
   - Rate: **5 requests per 10 seconds**
   - Action: **Block** for 10 seconds
3. **Watch node3** for the first few days:
   ```bash
   free -h          # RAM
   ollama ps        # which models are loaded
   sudo tail -f /opt/ai-writing-studio/logs/studio.log   # every request: mode, IP, time taken
   ```
   Your self-healing pipeline also uses Ollama on node3. If the site gets busy and qwen2.5 and qwen3.6 fight over RAM, that's the sign to move the site to its own AI VM.
4. **Emergency switch:** if it gets abused, set `require_cf_access: "true"` and re-run the playbook. The whole site then needs a login. Or remove the public hostname in the tunnel.

## Step 9: Monitoring (node1)

Add to your Prometheus config on node1 (in the Blackbox job):

```yaml
- job_name: 'blackbox-writing-studio'
  metrics_path: /probe
  params:
    module: [http_2xx]
  static_configs:
    - targets:
        - http://<node3-IP>:5000/health
        - https://write.starwars.it.com/health
  relabel_configs:
    - source_labels: [__address__]
      target_label: __param_target
    - source_labels: [__param_target]
      target_label: instance
    - target_label: __address__
      replacement: <blackbox-exporter-host>:9115
```

Reload Prometheus. Your existing Alertmanager email rules cover it the same way they cover the todo app.

## Step 10: Updating it later

```
# On your PC: edit, then
git add .
git commit -m "describe the change"
git push

# On the control node:
cd ~/ai-writing-studio && git pull
cd deploy && ansible-playbook -i <your-inventory> deploy_writing_studio.yml --ask-vault-pass
```

Update your work history with `ansible-vault edit files/work_history.json`, then re-run the playbook.

---

## Troubleshooting

| Problem | Likely cause / fix |
|---|---|
| Playbook fails at "Clone or update the repo" | Repo is private or URL is wrong. Make it public or fix `repo_url` |
| Playbook fails at "Wait for the app to answer" | `sudo journalctl -u writing-studio -n 50` on node3 shows the Python error |
| Site shows Cloudflare **502 / 1033** | Tunnel can't reach node3:5000. Check `node2_ip` in UFW and the tunnel URL |
| Site shows **524** | Very rare with streaming. The model took over 100s to send its first word. Check `ollama ps` and RAM |
| `/jobs` says "private" even after login | `cf_team_domain` / `cf_access_aud` are wrong or still CHANGEME. Re-check them and re-run the playbook |
| Resume or cover letter comes back empty | Raise `num_ctx` to 16384 in the playbook and re-run |
| "Too many requests" | The rate limit is working. Wait a minute, or raise `rate_per_minute` |

## Settings reference

| Playbook variable | Default | What it does |
|---|---|---|
| `require_cf_access` | `"false"` | `"true"` makes the whole site require a login |
| `cf_team_domain` / `cf_access_aud` | — | From Cloudflare Access. Needed for `/jobs` |
| `rate_per_minute` / `rate_per_day` | `10` / `60` | Per-visitor limits |
| `max_input_chars` / `job_max_chars` | `4000` / `15000` | Input limits |
| `num_ctx` | `8192` | Model context size |
| `ollama_model` | `qwen3.6:latest` | Model used |
