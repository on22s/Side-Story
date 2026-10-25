"""E2E server wrapper: real app/API with the CPU take-restoration fixture engine.

Only the native serving identity and engine object are replaced, and only after
the data directory is verified as the private E2E fixture. Book, history,
bytes, locks, routes and Editor controls are the real application.
"""
import json
import os
from pathlib import Path
import sys

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "app")
sys.path.insert(0, APP)


def _require_fixture(data_dir):
    marker = Path(data_dir) / '.e2e-take-history.json'
    try:
        value = json.loads(marker.read_text())
    except (OSError, ValueError) as error:
        raise SystemExit(f'refusing non-E2E data directory: {error}') from error
    if value != {'fixture': 'take_history', 'version': 1}:
        raise SystemExit('refusing non-E2E data directory: fixture marker mismatch')


def main():
    _require_fixture(os.environ['ALEXANDRIA_DATA_DIR'])
    from project import ProjectManager
    from synthesis_recovery_serving import NativeRecoveryServingIdentity
    from tests.test_take_restoration import TakeRestorationTests

    engine = TakeRestorationTests().engine()
    ProjectManager.get_engine = lambda self, *args, **kwargs: engine
    identity = NativeRecoveryServingIdentity('b' * 64, 'c' * 64, 'd' * 64)
    import synthesis_recovery_serving as serving
    serving.capture_native_custom_serving_identity = lambda *args, **kwargs: identity
    # synthesis_recovery.py binds this name at import time; keep every caller
    # on the same fixture identity.
    import synthesis_recovery as recovery
    recovery.capture_native_custom_serving_identity = lambda *args, **kwargs: identity

    import app as app_module
    import uvicorn
    uvicorn.run(app_module.app, host='127.0.0.1',
                port=int(os.environ['ALEXANDRIA_PORT']), log_level='warning')


if __name__ == '__main__':
    main()
