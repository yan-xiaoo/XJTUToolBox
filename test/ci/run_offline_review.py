"""Run desktop/calendar regression domains with isolated state and no network.

Usage: python -m test.ci.run_offline_review --domains schedule qt-ui
Git rehearsal tests use local bare repositories; no remote URLs are contacted.
"""
import argparse
import logging
import os
from pathlib import Path
import socket
import tempfile
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domains', nargs='+', default=['schedule', 'qt-ui'])
    args = parser.parse_args()
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['PYTHON_KEYRING_BACKEND'] = 'keyring.backends.null.Keyring'
    os.environ['GIT_TERMINAL_PROMPT'] = '0'
    with tempfile.TemporaryDirectory(prefix='toolbox-offline-') as directory:
        import platformdirs
        for kind in ('data', 'config', 'cache', 'log', 'state'):
            path = Path(directory) / kind
            path.mkdir()
            setattr(platformdirs, 'user_' + kind + '_dir', lambda *a, _path=path, **k: str(_path))
            setattr(platformdirs, 'user_' + kind + '_path', lambda *a, _path=path, **k: _path)

        def blocked(*args, **kwargs):
            raise RuntimeError('Offline regression runner blocks network access')

        socket.create_connection = blocked
        socket.socket.connect = blocked
        from app.qt_bootstrap import configure_qt_plugins
        configure_qt_plugins()
        from test.ci.run_test_shard import build_suite
        suite = unittest.TestSuite(build_suite(domain) for domain in args.domains)

        def ids(tests):
            for test in tests:
                if isinstance(test, unittest.TestSuite):
                    yield from ids(test)
                else:
                    yield test.id()

        names = list(ids(suite))
        if len(names) != len(set(names)):
            raise RuntimeError('Duplicate test IDs in selected domains')
        print(f'Running {len(names)} unique tests', flush=True)
        try:
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            return 0 if result.wasSuccessful() else 1
        finally:
            logging.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
