from datetime import datetime, timezone

import pytest

from fieldforge_gps.nmea import Framer, SentenceError, parse_sentence


def sentence(body: str) -> bytes:
    checksum = 0
    for x in body.encode("ascii"):
        checksum ^= x
    return f"${body}*{checksum:02X}\r\n".encode("ascii")


def rmc(**changes):
    fields = [
        "GNRMC",
        "120000.00",
        "A",
        "1000.0000",
        "N",
        "02000.0000",
        "E",
        "1.2",
        "45.0",
        "021026",
        "",
        "",
        "A",
    ]
    indexes = dict(
        header=0, time=1, status=2, lat=3, ns=4, lon=5, ew=6, speed=7, course=8, date=9, mode=12
    )
    for key, value in changes.items():
        fields[indexes[key]] = value
    return sentence(",".join(fields))


def gga(**changes):
    fields = [
        "GNGGA",
        "120000.00",
        "1000.0000",
        "N",
        "02000.0000",
        "E",
        "1",
        "08",
        "0.9",
        "1.0",
        "M",
        "0.0",
        "M",
        "",
        "",
    ]
    indexes = dict(header=0, time=1, lat=2, ns=3, lon=4, ew=5, quality=6, satellites=7, hdop=8)
    for key, value in changes.items():
        fields[indexes[key]] = value
    return sentence(",".join(fields))


def test_vendor_rmc_example():
    p = parse_sentence(b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n")
    assert p.latitude == pytest.approx(48.1173)
    assert p.longitude == pytest.approx(11.5166666667)
    assert p.timestamp == datetime(1994, 3, 23, 12, 35, 19, tzinfo=timezone.utc)


def test_known_gga():
    p = parse_sentence(b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n")
    assert p.valid and p.satellites == 8 and p.hdop == 0.9
    assert p.timestamp is None


@pytest.mark.parametrize("talker", ["GP", "GN", "GL", "GA", "GB", "BD", "GQ", "GI"])
def test_talkers(talker):
    assert parse_sentence(rmc(header=talker + "RMC")).talker == talker


@pytest.mark.parametrize(
    "key,value",
    [
        ("lat", "9060.0"),
        ("lat", "9100.0"),
        ("lat", "9000.001"),
        ("lon", "18000.001"),
        ("lat", "1060.0"),
        ("lon", "02060.0"),
        ("ns", "E"),
        ("ew", "N"),
        ("lat", "+1000.0"),
        ("lat", "NaN"),
        ("lon", "inf"),
        ("lat", "100.0"),
        ("lon", "2000.0"),
        ("speed", "-1"),
        ("speed", "nan"),
        ("speed", "2001"),
        ("course", "361"),
        ("date", "310226"),
        ("date", "290225"),
        ("date", ""),
        ("date", "011320"),
        ("time", "240000"),
        ("time", "120060"),
        ("time", "126000"),
        ("time", ""),
        ("time", "120000.1234567"),
        ("status", "X"),
        ("lat", "1000.1234567890123"),
    ],
)
def test_bad_rmc_fields(key, value):
    with pytest.raises(SentenceError):
        parse_sentence(rmc(**{key: value}))


@pytest.mark.parametrize("mode", ["E", "M", "N", "S", "X"])
def test_non_gnss_modes_not_valid(mode):
    p = parse_sentence(rmc(mode=mode))
    assert not p.valid and p.latitude is None


@pytest.mark.parametrize("mode", ["", "A", "D", "R", "F", "P"])
def test_supported_modes(mode):
    assert parse_sentence(rmc(mode=mode)).valid


def test_void_with_empty_position():
    assert not parse_sentence(rmc(status="V", lat="", ns="", lon="", ew="", time="", date="")).valid


def test_southern_western_and_extremes():
    p = parse_sentence(rmc(lat="9000.0", ns="S", lon="18000.0", ew="W"))
    assert (p.latitude, p.longitude) == (-90, -180)


def test_fraction_leap_date_and_century():
    assert parse_sentence(rmc(time="123456.123456", date="290224")).timestamp.microsecond == 123456
    assert parse_sentence(rmc(date="010180")).timestamp.year == 1980
    assert parse_sentence(rmc(date="010179")).timestamp.year == 2079
    assert parse_sentence(rmc(course="360")).course_true == 0


@pytest.mark.parametrize("quality", ["0", "3", "6", "7", "8"])
def test_invalid_quality(quality):
    assert not parse_sentence(gga(quality=quality)).valid


@pytest.mark.parametrize("quality", ["1", "2", "4", "5"])
def test_valid_quality(quality):
    assert parse_sentence(gga(quality=quality)).valid


@pytest.mark.parametrize(
    "key,value",
    [
        ("satellites", "0"),
        ("satellites", "200"),
        ("satellites", "1.5"),
        ("hdop", "-0.1"),
        ("hdop", "NaN"),
        ("quality", "9"),
        ("hdop", "1000"),
    ],
)
def test_invalid_gga_fields(key, value):
    with pytest.raises(SentenceError):
        parse_sentence(gga(**{key: value}))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"$GPRMC,foo",
        b"$GPRMC,foo*00",
        b"$GPRMC\x00*00",
        b" garbage",
        b"$GPRMC*GG",
        b"$GPRMC**00",
        b"$GPRMC*00 trailing",
        b"x" * 513,
        "text",
    ],
)
def test_bad_framing(raw):
    with pytest.raises(SentenceError):
        parse_sentence(raw)


def test_controls_with_correct_checksum_still_rejected():
    with pytest.raises(SentenceError):
        parse_sentence(sentence("GNRMC,\x1b"))


def test_unknown_types_ignored_but_checksum_checked():
    assert parse_sentence(sentence("GPGSV,1,1,0")) is None
    assert parse_sentence(rmc(header="XXRMC")) is None


def test_bytewise_framer():
    f = Framer()
    output = []
    wire = rmc() + gga()
    for value in wire:
        output.extend(f.feed(bytes([value])))
    assert output == [rmc(), gga()]
    assert not f.finish()


def test_overlong_suffix_cannot_become_position():
    f = Framer()
    assert f.feed(b"x" * 513 + rmc()) == [None]
    assert f.feed(rmc()) == [rmc()]
    assert len(f._buffer) == 0


def test_truncated_final_record_rejected():
    f = Framer()
    assert f.feed(rmc()[:-2]) == []
    assert f.finish() == [None]
    assert f.finish() == []


def test_chunk_bound():
    with pytest.raises(ValueError):
        Framer().feed(b"x" * 4097)
