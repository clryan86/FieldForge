import hashlib
import io
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.usa_maps import acquire as a


class Reply(io.BytesIO):
    def __init__(self, raw, url, headers=None):
        super().__init__(raw)
        self.url = url
        self.headers = {'Content-Length': str(len(raw))} if headers is None else headers
    def geturl(self):
        return self.url


def transport(data=b'fictional protocol bytes', wrong=False):
    md5 = ('0'*32 if wrong else hashlib.md5(data).hexdigest()) + '  vermont-latest.osm.pbf\n'
    values = {'vermont-latest.osm.pbf': data, 'vermont-latest.osm.pbf.md5': md5.encode(),
              'vermont.poly': b'fictional extent\nEND\n'}
    return lambda url: Reply(values[url.split('/')[-1]], url)


def test_real_api_path_is_fixed():
    assert a.BASE == 'https://download.geofabrik.de/north-america/us/'
    assert len(a.REGIONS) == 53  # 50 states plus DC, Puerto Rico and USVI


@pytest.mark.parametrize('name', ['../x', 'USA', '', 'https://evil.test', 'guam', 'not-a-state'])
def test_invalid_region_no_output(tmp_path, name):
    with pytest.raises(ValueError):a.acquire_region(tmp_path, name, transport=transport())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('url', ['http://download.geofabrik.de/north-america/us/vermont.poly',
 'https://evil.test/north-america/us/vermont.poly', a.BASE+'../secrets',
 a.BASE+'vermont.poly?token=x', a.BASE+'vermont.poly#x',
 'https://user@download.geofabrik.de/north-america/us/vermont.poly'])
def test_url_rejected(url):
    with pytest.raises(ValueError):a._safe_url(url)


def test_complete_verified_reuse_does_not_request_again(tmp_path):
    row, reused = a.acquire_region(tmp_path,'vermont',transport=transport())
    assert not reused and row['status']=='source-verified'
    before={p.name:p.read_bytes() for p in (tmp_path/'vermont').iterdir()}
    def offline(_):raise AssertionError('Network forbidden')
    got, reused=a.acquire_region(tmp_path,'vermont',transport=offline)
    assert reused and got==row
    assert before=={p.name:p.read_bytes() for p in (tmp_path/'vermont').iterdir()}


def test_publisher_digest_failure_no_published_data(tmp_path):
    with pytest.raises(ValueError,match='MD5'):a.acquire_region(tmp_path,'vermont',transport=transport(wrong=True))
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize('cap',[0,-1,True,a.MAX_CAP+1])
def test_invalid_cap(tmp_path,cap):
    with pytest.raises(ValueError):a.acquire_region(tmp_path,'vermont',cap=cap)


@pytest.mark.parametrize('headers',[{'Content-Length':'1000000'}, {'Content-Length':'wrong'},
                                  {'Content-Length':'2'}, {'Content-Length':'0'}])
def test_bad_size_failure(tmp_path,headers):
    def tx(url):return Reply(b'abc',url,headers)
    with pytest.raises(ValueError):a.acquire_region(tmp_path,'vermont',cap=10,transport=tx)
    assert list(tmp_path.iterdir())==[]


def test_unannounced_oversize(tmp_path):
    def tx(url):return Reply(b'x'*5000,url,{})
    with pytest.raises(ValueError):a.acquire_region(tmp_path,'vermont',transport=tx)
    assert list(tmp_path.iterdir())==[]


def test_corruption_reuse_refused(tmp_path):
    a.acquire_region(tmp_path,'vermont',transport=transport())
    p=tmp_path/'vermont/vermont-latest.osm.pbf';p.write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'):a.acquire_region(tmp_path,'vermont',transport=transport())
    assert p.read_bytes()==b'changed'


def test_unexpected_file_refused(tmp_path):
    a.acquire_region(tmp_path,'vermont',transport=transport())
    (tmp_path/'vermont/x').write_bytes(b'x')
    with pytest.raises(ValueError,match='members'):a.verify_acquisition(tmp_path/'vermont')


def test_wrong_region_receipt(tmp_path):
    a.acquire_region(tmp_path,'vermont',transport=transport())
    with pytest.raises(ValueError,match='Wrong region'):a.verify_acquisition(tmp_path/'vermont',expected_region='maine')


def test_symbolic_output_refused(tmp_path):
    real=tmp_path/'real';real.mkdir();link=tmp_path/'alias';link.symlink_to(real,target_is_directory=True)
    with pytest.raises(ValueError):a.acquire_region(link,'vermont',transport=transport())


def test_concurrent_lock_preserved(tmp_path):
    lock=tmp_path/'.vermont.acquisition-lock';lock.mkdir()
    with pytest.raises(FileExistsError):a.acquire_region(tmp_path,'vermont',transport=transport())
    assert lock.exists()


def test_failed_transfer_cleanup(tmp_path):
    def tx(url):raise OSError('offline')
    with pytest.raises(OSError):a.acquire_region(tmp_path,'vermont',transport=tx)
    assert list(tmp_path.iterdir())==[]


def test_cross_source_redirect_refused(tmp_path):
    def tx(url):return Reply(b'xxx',a.BASE+'maine.poly')
    with pytest.raises(ValueError,match='changed'):a.acquire_region(tmp_path,'vermont',transport=tx)


def test_duplicate_receipt_fields(tmp_path):
    a.acquire_region(tmp_path,'vermont',transport=transport())
    p=tmp_path/'vermont/source-receipt.json';p.write_text('{"format":1,"format":2}')
    with pytest.raises(ValueError,match='Duplicate'):a.verify_acquisition(tmp_path/'vermont')


def test_cli_acquisition_error_is_nonzero(tmp_path):
    assert a.main(['--output',str(tmp_path),'--region','vermont','--max-mib','0'])==2
