#!/usr/bin/env python3
"""Real-browser smoke test for retained-take Editor controls.

Runs the actual FastAPI app against a private CPU-only synthetic book. The
server wrapper supplies only the fixture engine/serving identity needed for
verified restoration; books, take-history bytes, locks, routes and Editor
controls are the real application.

Usage: python tools/e2e/smoke_take_history.py [--app-python PATH] [--keep]
Exit 0 when every check passes, 1 when a check fails, 2 when it could not run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[2]
APP = REPO / 'app'
TOOLS = REPO / 'tools/e2e'
sys.path.insert(0, str(APP))
from subprocess_ownership import start_owned_subprocess, stop_owned_subprocess


def get_app_python():
    candidate = APP / 'env/bin/python'
    return str(candidate) if candidate.is_file() else sys.executable


def get_free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def wait_ready(url, server, log_path, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f'server exited with {server.returncode}; see {log_path}')
        try:
            urllib.request.urlopen(url, timeout=2).close()
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    raise RuntimeError(f'server not ready after {timeout}s; see {log_path}')


def stop_server(server):
    try:
        stop_owned_subprocess(server, timeout=3, force_after_grace=True)
    finally:
        control = getattr(server, '_alexandria_control', None)
        if control is not None:
            control.close()


def get_json(base, path):
    with urllib.request.urlopen(base + path, timeout=20) as response:
        return json.load(response)


def post_json(base, path, body):
    request = urllib.request.Request(base + path, method='POST',
        data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def get_bytes(base, path):
    with urllib.request.urlopen(base + path, timeout=20) as response:
        return response.read()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def wait_api(predicate, timeout=20, interval=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise TimeoutError('condition was not met before timeout')


def open_take_panel(page):
    page.evaluate("document.querySelectorAll('details').forEach(d=>d.open=true)")
    page.get_by_role('button', name="This line's snapshots").click()
    page.evaluate('loadEditorTakeSnapshots(false)')
    page.wait_for_function("() => takeHistoryBusy === false", timeout=15000)
    page.wait_for_function(
        "() => document.getElementById('editor-take-status').textContent.includes('saved snapshot')",
        timeout=10000)


def snapshot_card(page, version):
    page.wait_for_function(
        "version => [...document.querySelectorAll('#editor-take-list audio')].some(audio => audio.src.includes(version))",
        arg=version, timeout=15000)
    cards = page.locator('#editor-take-list > div')
    for index in range(cards.count()):
        card = cards.nth(index)
        if card.locator(f'audio[src*="{version}"]').count():
            return card
    raise AssertionError(f'snapshot card {version} is not visible')


def select_line(page, index):
    page.evaluate(f'selectEditorReviewLineById({index})')
    page.wait_for_timeout(250)


def run_browser(base, data_dir, metadata, failures, checks):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page_errors = []
            page.on('pageerror', lambda error: page_errors.append(str(error)))
            page.goto(f'{base}/#editor')
            page.locator('#chunks-table-body tr.chunk-row').nth(1).wait_for(timeout=20000)
            select_line(page, 0)
            open_take_panel(page)
            token = page.evaluate('chunkSnapshotBookToken')
            if not isinstance(token, str) or len(token) != 64:
                raise AssertionError('Editor has no book token')
            origin = next(row for row in get_json(base,
                f'/api/take_snapshots?expected_book_token={token}&uid=line')['records']
                if row['version'] == metadata['snapshot_version'])
            if origin['sha256'] != metadata['snapshot_sha256']:
                raise AssertionError('seeded snapshot hash changed')

            # Audition the archived bytes through the Editor's audio source.
            card = snapshot_card(page, origin['version'])
            src = card.locator('audio').get_attribute('src')
            archived = get_bytes(base, src)
            if sha(archived) != origin['sha256']:
                raise AssertionError('audition served bytes that differ from the snapshot hash')
            checks.append('audition hash')

            # A pending save must stay bound to row 0 while the user switches
            # rows before the request is released. This is also the save flow.
            held = {}
            def hold(route):
                held['route'] = route
            page.route('**/*take_snapshot*', hold)
            before0 = get_json(base, f'/api/take_snapshots?expected_book_token={token}&uid=line')['total']
            before1 = get_json(base, f'/api/take_snapshots?expected_book_token={token}&uid=other')['total']
            row1_before = next(row for row in get_json(base, '/api/chunks') if row['id'] == 1)
            row1_hash = sha((Path(data_dir) / row1_before['audio_path']).read_bytes())
            page.locator('#editor-take-save').click()
            for _ in range(200):
                if 'route' in held:
                    break
                page.wait_for_timeout(50)
            if 'route' not in held:
                raise AssertionError('pending save request was not intercepted')
            select_line(page, 1)
            held['route'].continue_()
            wait_api(lambda: get_json(base,
                f'/api/take_snapshots?expected_book_token={token}&uid=line')['total'] > before0)
            page.unroute('**/*take_snapshot*')
            if get_json(base, f'/api/take_snapshots?expected_book_token={token}&uid=other')['total'] != before1:
                raise AssertionError('pending save was redirected to the newly selected row')
            row1 = next(row for row in get_json(base, '/api/chunks') if row['id'] == 1)
            if sha((Path(data_dir) / row1['audio_path']).read_bytes()) != row1_hash:
                raise AssertionError('row switch changed the other row audio')
            checks.append('pending row ownership')

            select_line(page, 0)
            open_take_panel(page)
            saved = get_json(base, f'/api/take_snapshots?expected_book_token={token}&uid=line')['records'][0]
            if saved['sha256'] != metadata['current_sha256']:
                raise AssertionError('saved snapshot did not capture the selected take')
            checks.append('save')

            # Delete the newest snapshot and undo it. Both actions use the
            # actual list buttons and must leave the archived bytes intact.
            page.locator('#editor-take-list > div').first.get_by_role(
                'button', name='Delete with undo').click()
            wait_api(lambda: get_json(base,
                f'/api/take_snapshots?expected_book_token={token}&uid=line')['records'][0]['state'] == 'deleted')
            open_take_panel(page)
            page.locator('#editor-take-list > div').first.get_by_role(
                'button', name='Undo deletion').click()
            wait_api(lambda: get_json(base,
                f'/api/take_snapshots?expected_book_token={token}&uid=line')['records'][0]['state'] == 'ready')
            open_take_panel(page)
            if sha(get_bytes(base, snapshot_card(page, saved['version']).locator('audio').get_attribute('src'))) != saved['sha256']:
                raise AssertionError('delete/undo changed the archived audio')
            checks.append('delete/undo')

            # Verified restoration must select the origin bytes for row 0.
            card = snapshot_card(page, origin['version'])
            card.get_by_role('button', name='Check & restore').click()
            def restored():
                row = next(row for row in get_json(base, '/api/chunks') if row['id'] == 0)
                status = get_json(base, '/api/status/audio')
                if status.get('error'):
                    raise AssertionError(f"restore failed: {status['error']}")
                if row.get('audio_revision') == origin.get('audio_revision'):
                    return row
                if status.get('running') is False and status.get('status') in ('failed', 'cancelled'):
                    raise AssertionError(f"restore did not select the saved revision: {status}")
                return None
            row0 = wait_api(restored, timeout=40)
            selected = (Path(data_dir) / row0['audio_path']).read_bytes()
            if sha(selected) != origin['sha256']:
                raise AssertionError('restored file does not match the snapshot hash')
            checks.append('restore hash')
            page.wait_for_function('() => takeHistoryBusy === false', timeout=20000)
            select_line(page, 0)
            open_take_panel(page)

            # A pending save must not follow a book switch. Save the current
            # book first, hold a new save, switch books, then release it.
            post_json(base, '/api/scripts/save', {'name': 'Other', 'expected_book_token': token})
            manifest_path = Path(data_dir) / 'take_history/manifest.json'
            before_archive = len(json.loads(manifest_path.read_text())['records'])
            held = {}
            def hold_book(route):
                held['route'] = route
            page.route('**/*take_snapshot*', hold_book)
            select_line(page, 0)
            page.locator('#editor-take-save').click()
            for _ in range(200):
                if 'route' in held:
                    break
                page.wait_for_timeout(50)
            if 'route' not in held:
                raise AssertionError('book-switch save request was not intercepted')
            page.evaluate("void loadScript('Other')")
            page.locator('#confirmModalOk').wait_for(state='visible', timeout=10000)
            page.locator('#confirmModalOk').click()
            wait_api(lambda: page.evaluate('currentBookFilename') == 'Other.json', timeout=20)
            held['route'].continue_()
            page.wait_for_timeout(750)
            page.unroute('**/*take_snapshot*')
            after_archive = len(json.loads(manifest_path.read_text())['records'])
            if after_archive != before_archive:
                raise AssertionError('pending save wrote into the old book after switching')
            token_b = page.evaluate('chunkSnapshotBookToken')
            if get_json(base, f'/api/take_snapshots?expected_book_token={token_b}')['total'] != 0:
                raise AssertionError('pending save appeared in the newly loaded book')
            checks.append('pending book ownership')

            if page_errors:
                failures.append(f'page errors: {page_errors[:3]}')
        finally:
            browser.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--app-python', help='interpreter for seed/server (default: app/env)')
    parser.add_argument('--keep', action='store_true')
    args = parser.parse_args(argv)
    try:
        import playwright  # noqa: F401
    except ImportError:
        print('playwright is not installed in this interpreter; see requirements-test.txt', file=sys.stderr)
        return 2
    data_dir = tempfile.mkdtemp(prefix='aa2-take-smoke-')
    os.chmod(data_dir, 0o700)
    server = None
    log_path = os.path.join(data_dir, 'server.log')
    failures, checks = [], []
    status = 0
    app_python = args.app_python or get_app_python()
    env = dict(os.environ, ALEXANDRIA_DATA_DIR=data_dir, ALEXANDRIA_HOST='127.0.0.1',
               ALEXANDRIA_PORT=str(get_free_port()), PYTHONDONTWRITEBYTECODE='1')
    base = f"http://127.0.0.1:{env['ALEXANDRIA_PORT']}"
    try:
        seed = subprocess.run([app_python, str(TOOLS / 'seed_take_history.py')],
                              env=env, capture_output=True, text=True, timeout=120)
        if seed.returncode:
            raise RuntimeError(f'seed failed ({seed.returncode}): {seed.stderr[-2048:]}')
        metadata = json.loads(seed.stdout)
        with open(log_path, 'w') as log:
            server = start_owned_subprocess([app_python, str(TOOLS / 'take_history_server.py')],
                env=env, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=os.name == 'posix', termination_grace=3)
        wait_ready(base + '/', server, log_path)
        run_browser(base, data_dir, metadata, failures, checks)
        print('checks:', ', '.join(checks))
    except Exception as error:
        failures.append(f'{type(error).__name__}: {error}')
    finally:
        if server is not None:
            try:
                stop_server(server)
            except Exception as error:
                failures.append(f'cleanup: {type(error).__name__}: {error}')
        if failures:
            status = 1
            for failure in failures:
                print(f'FAIL: {failure}', file=sys.stderr)
        if status or args.keep:
            print(f'kept {data_dir}')
        else:
            import shutil
            shutil.rmtree(data_dir, ignore_errors=True)
    return status


if __name__ == '__main__':
    sys.exit(main())
