from core.audio import sniff_audio_format


def test_sniff_common_formats():
    assert sniff_audio_format(b"\x02#!SILK_V3....") == "silk"
    assert sniff_audio_format(b"RIFF\x00\x00\x00\x00WAVEfmt ") == "wav"
    assert sniff_audio_format(b"ID3\x04\x00\x00") == "mp3"
    assert sniff_audio_format(b"\xff\xfb\x90\x00") == "mp3"
    assert sniff_audio_format(b"OggS....") == "ogg"


def test_unknown_format():
    assert sniff_audio_format(b"not-audio") == "bin"

