VERSION = (1, 0, 0, 'alpha', 0)


def get_version(*args, **kwargs):
    from pythia.utils import get_version
    return get_version(*args, **kwargs)
