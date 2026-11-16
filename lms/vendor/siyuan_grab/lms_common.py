"""Desktop configuration shim; never loads the standalone CLI's login cache."""
BASE = 'https://lms.xjtu.edu.cn'
HOST = 'lms.xjtu.edu.cn'


def state_path(course):
    raise RuntimeError('Use the desktop account session, not CLI login files')
