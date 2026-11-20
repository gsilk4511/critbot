"""Single-process Unraid/Docker entry point for FTC CritBot.

Starts the Discord bot and officer dashboard, sharing ONE SQLite database.
The dashboard is localhost-only. Optionally exposes it securely through an
outbound Cloudflare Tunnel; requires configured Cloudflare domain and tunnel token.
"""
import os
import sys
import threading
import subprocess
import platform
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
load_dotenv(ROOT / '.env')


def dashboard_port():
    # Tunnel routes to loopback; no public TCP listener is required.
    return int(os.getenv('CRITBOT_DASHBOARD_PORT', '5000'))


def start_dashboard():
    from waitress import serve
    from critbot.dashboard import app, init_db
    init_db()
    port = dashboard_port()
    print(f'[Critbot] Dashboard listening inside container on 0.0.0.0:{port}; require HTTPS reverse proxy or tunnel.', flush=True)
    serve(app, host='0.0.0.0', port=port, threads=4)


def start_tunnel():
    token = os.getenv('CLOUDFLARE_TUNNEL_TOKEN', '').strip()
    if not token:
        print('[Critbot] No Cloudflare tunnel configured; Discord bot works, dashboard remains private.', flush=True)
        return
    uri = os.getenv('DISCORD_REDIRECT_URI', '').strip()
    if not (uri.startswith('https://') and uri.endswith('/auth/discord/callback')):
        print('[Critbot] Tunnel not started: set DISCORD_REDIRECT_URI to https://YOUR-DOMAIN/auth/discord/callback', flush=True)
        return
    if os.getenv('CRITBOT_ALLOW_HTTP_LOCAL') == '1':
        print('[Critbot] Tunnel not started: remove CRITBOT_ALLOW_HTTP_LOCAL=1', flush=True)
        return
    try:
        arch = platform.machine().lower()
        architecture = {'x86_64':'amd64', 'amd64':'amd64', 'aarch64':'arm64', 'arm64':'arm64'}.get(arch)
        if not architecture:
            raise RuntimeError(f'Unsupported Linux architecture: {arch}')
        executable = ROOT / 'cloudflared'
        if not executable.exists():
            url = f'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{architecture}'
            temp = ROOT / 'cloudflared.download'
            print('[Critbot] Downloading official Cloudflare connector for first run...', flush=True)
            urllib.request.urlretrieve(url, temp)
            temp.chmod(0o700)
            temp.replace(executable)
        # Token lives in an owner-only file instead of command-line args.
        token_file = ROOT / '.cloudflared-token'
        token_file.write_text(token + '\n')
        token_file.chmod(0o600)
        print('[Critbot] Launching HTTPS Cloudflare Tunnel...', flush=True)
        proc = subprocess.Popen([str(executable), 'tunnel', '--no-autoupdate', 'run', '--token-file', str(token_file)], cwd=str(ROOT))
        code = proc.wait()
        print(f'[Critbot] Cloudflare Tunnel exited (code {code}); bot remains online.', flush=True)
    except Exception as exc:
        print(f'[Critbot] Cloudflare Tunnel failed: {exc}. Bot remains online.', flush=True)


def main():
    # Load/validate the database BEFORE allowing any process to create tables.
    from critbot.paths import database_path
    db = database_path()
    if not db.is_file():
        raise SystemExit(f'Existing Critbot DB missing: {db}. Restore backup instead of initializing a blank database.')
    if not os.getenv('DISCORD_TOKEN'):
        raise SystemExit('Missing DISCORD_TOKEN; create .env from .env.example on the server.')
    if not os.getenv('CRITBOT_DASHBOARD_SECRET') or len(os.getenv('CRITBOT_DASHBOARD_SECRET','')) < 32:
        raise SystemExit('Missing/short CRITBOT_DASHBOARD_SECRET. Configure .env on server.')

    # Complete and back up release migrations BEFORE either dashboard or Discord starts.
    from critbot.dashboard import init_db
    init_db()
    print('[Critbot] v1.2 schema migrations applied. Legacy achievement records preserved (archived), not deleted.', flush=True)

    thread = threading.Thread(name='Critbot dashboard', target=start_dashboard, daemon=True)
    thread.start()
    if os.getenv('CLOUDFLARE_TUNNEL_TOKEN'):
        threading.Thread(name='Cloudflare Tunnel', target=start_tunnel, daemon=True).start()

    from critbot.bot import acquire_single_instance, init_db, bot, TOKEN
    acquire_single_instance()
    init_db()
    print('[Critbot] Starting full Discord bot (guild events, suggestions, achievements, activity and sync)',flush=True)
    bot.run(TOKEN)

if __name__ == '__main__':
    main()
