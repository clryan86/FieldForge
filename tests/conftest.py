"""Keep parameter labels bounded even when testing megabyte-sized input data."""

import hashlib


def pytest_make_parametrize_id(config, val, argname):
    if isinstance(val, (str, bytes)) and len(val) > 100:
        data = val.encode("utf-8", errors="surrogatepass") if isinstance(val, str) else val
        return f"{argname}-{len(val)}-{hashlib.sha256(data).hexdigest()[:12]}"
    return None
