"""E2E server wrapper: real app/API with the CPU take-restoration fixture engine.

Only the native serving identity and the engine object are replaced. Book,
history, bytes, locks, routes and Editor controls are the real application.
"""
import os
import sys

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "app")
sys.path.insert(0, APP)

from project import ProjectManager
from synthesis_recovery_serving import NativeRecoveryServingIdentity
from tests.test_take_restoration import TakeRestorationTests

_engine = TakeRestorationTests().engine()
ProjectManager.get_engine = lambda self, *args, **kwargs: _engine

import synthesis_recovery_serving as serving
serving.capture_native_custom_serving_identity = (
    lambda *args, **kwargs: NativeRecoveryServingIdentity('b' * 64, 'c' * 64, 'd' * 64))

import app as app_module
import uvicorn

if __name__ == '__main__':
    uvicorn.run(app_module.app,
                host=os.environ.get('ALEXANDRIA_HOST', '127.0.0.1'),
                port=int(os.environ['ALEXANDRIA_PORT']), log_level='warning')
