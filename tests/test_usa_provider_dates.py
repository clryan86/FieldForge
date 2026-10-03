import hashlib

import pytest

from test_usa_acquire import Reply
from tools.usa_maps import acquire as a


@pytest.mark.parametrize('suffix', ['261002.osm.pbf', '261002.osm.pbf.md5'])
def test_valid_dated_source_redirect(suffix):
    assert a._safe_url(a.BASE + 'vermont-' + suffix)
    assert a._file_identity(a.BASE + 'vermont-' + suffix)[0] == 'vermont'


@pytest.mark.parametrize('suffix', ['261399.osm.pbf', '261002.zip', '../maine.poly'])
def test_invalid_dated_source_redirect(suffix):
    with pytest.raises(ValueError):
        a._safe_url(a.BASE + 'vermont-' + suffix)


def test_dated_provider_md5_and_source(tmp_path):
    data = b'fictional-source'

    def tx(url):
        final = url.replace('-latest.', '-261002.')
        if url.endswith('.md5'):
            raw = (hashlib.md5(data).hexdigest() + '  vermont-261002.osm.pbf').encode()
        elif url.endswith('.pbf'):
            raw = data
        else:
            raw = b'fictional boundary'
        return Reply(raw, final)

    row, _ = a.acquire_region(tmp_path, 'vermont', transport=tx)
    assert row['files']['vermont-latest.osm.pbf']['final_url'].endswith('vermont-261002.osm.pbf')
    assert a.verify_acquisition(tmp_path / 'vermont') == row
