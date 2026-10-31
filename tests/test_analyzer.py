"""Tests for analyzer.py — no network or ffmpeg calls are made."""

import argparse
import os
import types

import pytest

import analyzer


def make_config(tmp_path, **overrides):
    defaults = dict(
        api_key='test-key',
        webhook_url='https://example.test/analyze',
        analyze_multiple_url='https://example.test/analyze-multiple',
        output_dir=str(tmp_path),
        fractions=[0.5],
        dedup_threshold=8,
        cleanup_thumbnails=False,
        force=False,
        extensions=('.mp4', '.mov'),
        provider=None,
    )
    defaults.update(overrides)
    return analyzer.Config(**defaults)


def fake_response(status_code=200, payload=None, text='', headers=None):
    return types.SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        text=text,
        json=lambda: payload if payload is not None else {},
    )


def make_frame(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b'fake-jpeg')
    return str(path)


# --- argument parsing -------------------------------------------------------

def test_parse_fractions_sorts_and_dedupes():
    assert analyzer.parse_fractions('0.9, 0.5,0.9') == [0.5, 0.9]


@pytest.mark.parametrize('value', ['', ' ', '0', '1', '-0.1', '1.5', 'abc'])
def test_parse_fractions_rejects_invalid(value):
    with pytest.raises(argparse.ArgumentTypeError):
        analyzer.parse_fractions(value)


def test_parse_fractions_rejects_more_than_five():
    with pytest.raises(argparse.ArgumentTypeError):
        analyzer.parse_fractions('0.1,0.2,0.3,0.4,0.5,0.6')


def test_parse_extensions_normalizes():
    assert analyzer.parse_extensions(' .MP4, mov ,') == ('.mp4', '.mov')


def test_parse_extensions_rejects_empty():
    with pytest.raises(argparse.ArgumentTypeError):
        analyzer.parse_extensions(' , ')


def test_defaults_preserve_single_frame_behavior():
    args = analyzer.parse_args([])
    assert args.frames == [0.5]
    assert args.dedup_threshold == 8
    assert args.provider is None


# --- URL / config -----------------------------------------------------------

def test_derive_analyze_multiple_url():
    assert analyzer.derive_analyze_multiple_url(
        'https://example.test/analyze'
    ) == 'https://example.test/analyze-multiple'
    assert analyzer.derive_analyze_multiple_url(
        'https://example.test/analyze/'
    ) == 'https://example.test/analyze-multiple'
    assert analyzer.derive_analyze_multiple_url(
        'https://example.test'
    ) == 'https://example.test/analyze-multiple'


def test_build_config_derives_urls(tmp_path, monkeypatch):
    monkeypatch.setattr(
        analyzer, 'load_env', lambda: ('key', 'https://example.test/analyze')
    )
    args = analyzer.parse_args(['--output-dir', str(tmp_path)])
    config = analyzer.build_config(args)
    assert config.api_key == 'key'
    assert config.webhook_url == 'https://example.test/analyze'
    assert config.analyze_multiple_url == 'https://example.test/analyze-multiple'
    assert config.output_dir == str(tmp_path)


# --- perceptual hashing / dedup --------------------------------------------

def test_dhash_identical_and_inverted():
    pixels = bytes(range(72))
    digest = analyzer.dhash_from_pixels(pixels)
    assert analyzer.hamming_distance(digest, analyzer.dhash_from_pixels(pixels)) == 0

    inverted = bytes(255 - value for value in pixels)
    other = analyzer.dhash_from_pixels(inverted)
    assert analyzer.hamming_distance(digest, other) == 64


def test_dhash_rejects_short_input():
    with pytest.raises(ValueError):
        analyzer.dhash_from_pixels(b'too short')


def test_dedupe_frames_drops_near_duplicates(tmp_path, monkeypatch):
    paths = [make_frame(tmp_path, name) for name in ('a.jpg', 'b.jpg', 'c.jpg')]
    hashes = {paths[0]: 0x0, paths[1]: 0x1, paths[2]: 0xFFFF}
    monkeypatch.setattr(analyzer, 'compute_dhash', lambda path: hashes[path])

    kept = analyzer.dedupe_frames(paths, threshold=8)

    assert kept == [paths[0], paths[2]]
    assert not os.path.exists(paths[1])


def test_dedupe_disabled_keeps_everything(tmp_path, monkeypatch):
    paths = [make_frame(tmp_path, name) for name in ('a.jpg', 'b.jpg')]
    monkeypatch.setattr(
        analyzer, 'compute_dhash', lambda path: pytest.fail('should not hash')
    )
    assert analyzer.dedupe_frames(paths, threshold=0) == paths


def test_dedupe_keeps_frame_when_hashing_fails(tmp_path, monkeypatch):
    paths = [make_frame(tmp_path, name) for name in ('a.jpg', 'b.jpg')]

    def broken_hash(path):
        raise ValueError('cannot hash')

    monkeypatch.setattr(analyzer, 'compute_dhash', broken_hash)
    assert analyzer.dedupe_frames(paths, threshold=8) == paths


# --- request construction ---------------------------------------------------

def test_post_multiple_uses_images_field(tmp_path, monkeypatch):
    paths = [make_frame(tmp_path, name) for name in ('f1.jpg', 'f2.jpg')]
    captured = {}

    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        captured.update(
            url=url, headers=headers, files=files, data=data, timeout=timeout
        )
        return fake_response(200, {'title': 't', 'description': 'd', 'keywords': 'k'})

    monkeypatch.setattr(analyzer.requests, 'post', fake_post)
    config = make_config(tmp_path, provider='openrouter')

    result = analyzer.analyze_frames(paths, 'clip.mp4', config)

    assert result == {'title': 't', 'description': 'd', 'keywords': 'k'}
    assert captured['url'] == 'https://example.test/analyze-multiple'
    assert [entry[0] for entry in captured['files']] == ['images', 'images']
    assert captured['data'] == {
        'filename': 'clip.mp4',
        'generateTwoPartKeywords': 'true',
        'useFilename': 'true',
        'provider': 'openrouter',
    }
    assert captured['headers']['X-API-Key'] == 'test-key'
    assert captured['timeout'] == analyzer.REQUEST_TIMEOUT


def test_analyze_frames_falls_back_on_404(tmp_path, monkeypatch):
    frame = make_frame(tmp_path, 'f.jpg')
    calls = []

    def fake_multiple(*args, **kwargs):
        calls.append('multiple')
        return fake_response(404, text='not found')

    def fake_legacy(*args, **kwargs):
        calls.append('legacy')
        return fake_response(200, {'title': 't', 'description': 'd', 'keywords': 'k'})

    monkeypatch.setattr(analyzer, 'post_multiple', fake_multiple)
    monkeypatch.setattr(analyzer, 'post_legacy', fake_legacy)

    result = analyzer.analyze_frames([frame], 'clip.mp4', make_config(tmp_path))

    assert calls == ['multiple', 'legacy']
    assert result['title'] == 't'


@pytest.mark.parametrize('status', [400, 401, 413, 415])
def test_analyze_frames_does_not_fall_back_on_client_errors(
    tmp_path, monkeypatch, status
):
    frame = make_frame(tmp_path, 'f.jpg')
    calls = []

    def fake_multiple(*args, **kwargs):
        calls.append('multiple')
        return fake_response(status, text='error')

    def fake_legacy(*args, **kwargs):
        calls.append('legacy')
        return fake_response(200, {'title': 't', 'description': 'd', 'keywords': 'k'})

    monkeypatch.setattr(analyzer, 'post_multiple', fake_multiple)
    monkeypatch.setattr(analyzer, 'post_legacy', fake_legacy)

    result = analyzer.analyze_frames([frame], 'clip.mp4', make_config(tmp_path))

    assert calls == ['multiple']
    assert result is None


def test_analyze_frames_retries_500_then_succeeds(tmp_path, monkeypatch):
    frame = make_frame(tmp_path, 'f.jpg')
    responses = [
        fake_response(500, text='boom'),
        fake_response(503, text='unavailable'),
        fake_response(200, {'title': 't', 'description': 'd', 'keywords': 'k'}),
    ]
    calls = []

    def fake_multiple(*args, **kwargs):
        calls.append('call')
        return responses.pop(0)

    monkeypatch.setattr(analyzer, 'post_multiple', fake_multiple)
    monkeypatch.setattr(analyzer.time, 'sleep', lambda seconds: None)

    result = analyzer.analyze_frames([frame], 'clip.mp4', make_config(tmp_path))

    assert len(calls) == 3
    assert result['title'] == 't'


def test_analyze_frames_gives_up_after_max_retries(tmp_path, monkeypatch):
    frame = make_frame(tmp_path, 'f.jpg')
    calls = []

    def fake_multiple(*args, **kwargs):
        calls.append('call')
        return fake_response(500, text='boom')

    monkeypatch.setattr(analyzer, 'post_multiple', fake_multiple)
    monkeypatch.setattr(analyzer.time, 'sleep', lambda seconds: None)

    result = analyzer.analyze_frames([frame], 'clip.mp4', make_config(tmp_path))

    assert len(calls) == analyzer.MAX_RETRIES
    assert result is None


def test_retry_after_header_is_honored(tmp_path, monkeypatch):
    frame = make_frame(tmp_path, 'f.jpg')
    responses = [
        fake_response(429, headers={'Retry-After': '7'}),
        fake_response(200, {'title': 't', 'description': 'd', 'keywords': 'k'}),
    ]
    sleeps = []

    def fake_multiple(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(analyzer, 'post_multiple', fake_multiple)
    monkeypatch.setattr(analyzer.time, 'sleep', sleeps.append)

    analyzer.analyze_frames([frame], 'clip.mp4', make_config(tmp_path))

    assert sleeps == [7]


# --- response parsing -------------------------------------------------------

def test_parse_metadata_rejects_non_object():
    response = fake_response(200, payload=['not', 'an', 'object'])
    assert analyzer.parse_metadata(response) is None


def test_parse_metadata_rejects_invalid_json():
    response = types.SimpleNamespace(
        status_code=200,
        headers={},
        text='<html>error</html>',
        json=lambda: (_ for _ in ()).throw(ValueError('bad json')),
    )
    assert analyzer.parse_metadata(response) is None


def test_parse_metadata_warns_but_returns_missing_keys():
    response = fake_response(200, payload={'title': 'only title'})
    assert analyzer.parse_metadata(response) == {'title': 'only title'}


# --- frame extraction -------------------------------------------------------

def test_extract_frames_continues_after_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        analyzer.ffmpeg, 'probe', lambda path: {'format': {'duration': '10'}}
    )
    outcomes = [True, False, True]
    seen = []

    def fake_extract(video_path, image_path, duration, fraction):
        seen.append(fraction)
        if outcomes[len(seen) - 1]:
            with open(image_path, 'wb') as handle:
                handle.write(b'frame')
        return outcomes[len(seen) - 1]

    monkeypatch.setattr(analyzer, 'extract_frame', fake_extract)

    frames = analyzer.extract_frames(
        'video.mp4', str(tmp_path), 'video', [0.5, 0.7, 0.9]
    )

    assert seen == [0.5, 0.7, 0.9]
    assert frames == [
        str(tmp_path / 'video_001.jpg'),
        str(tmp_path / 'video_003.jpg'),
    ]


def test_extract_frames_returns_empty_when_probe_fails(tmp_path, monkeypatch):
    def broken_probe(path):
        raise analyzer.ffmpeg.Error('ffprobe', b'', b'no duration')

    monkeypatch.setattr(analyzer.ffmpeg, 'probe', broken_probe)
    assert analyzer.extract_frames('video.mp4', str(tmp_path), 'video', [0.5]) == []


# --- CSV / processing -------------------------------------------------------

def test_write_csv(tmp_path):
    csv_path = tmp_path / 'video.csv'
    analyzer.write_csv(
        str(csv_path),
        'video.mp4',
        {'title': 'T', 'description': 'D', 'keywords': 'a, b'},
    )

    lines = csv_path.read_text(encoding='utf-8').splitlines()
    assert lines[0] == 'Filename,Title,Description,Keywords'
    assert lines[1] == 'video.mp4,T,D,"a, b"'


def test_process_videos_skips_existing_csv(tmp_path, monkeypatch):
    (tmp_path / 'video.mp4').write_bytes(b'video')
    (tmp_path / 'video.csv').write_text('existing', encoding='utf-8')
    calls = []

    monkeypatch.setattr(
        analyzer, 'extract_frames', lambda *args, **kwargs: calls.append('extract') or []
    )

    analyzer.process_videos(str(tmp_path), make_config(tmp_path))

    assert calls == []


def test_process_videos_cleans_up_all_frames(tmp_path, monkeypatch):
    (tmp_path / 'video.mp4').write_bytes(b'video')
    frames = [make_frame(tmp_path, 'video_001.jpg'), make_frame(tmp_path, 'video_002.jpg')]

    monkeypatch.setattr(analyzer, 'extract_frames', lambda *args, **kwargs: list(frames))
    monkeypatch.setattr(
        analyzer, 'dedupe_frames', lambda paths, threshold: list(paths)
    )
    monkeypatch.setattr(
        analyzer,
        'analyze_frames',
        lambda *args, **kwargs: {'title': 'T', 'description': 'D', 'keywords': 'K'},
    )

    config = make_config(tmp_path, cleanup_thumbnails=True)
    analyzer.process_videos(str(tmp_path), config)

    assert not any(os.path.exists(path) for path in frames)
    assert (tmp_path / 'video.csv').exists()


def test_process_videos_skips_when_no_frames_extracted(tmp_path, monkeypatch):
    (tmp_path / 'video.mp4').write_bytes(b'video')
    calls = []

    monkeypatch.setattr(analyzer, 'extract_frames', lambda *args, **kwargs: [])
    monkeypatch.setattr(
        analyzer, 'analyze_frames', lambda *args, **kwargs: calls.append('analyze')
    )

    analyzer.process_videos(str(tmp_path), make_config(tmp_path))

    assert calls == []
    assert not (tmp_path / 'video.csv').exists()


def test_process_videos_requires_directory(tmp_path):
    video_file = tmp_path / 'not-a-dir.mp4'
    video_file.write_bytes(b'video')
    # Should not raise and should not create output.
    analyzer.process_videos(str(video_file), make_config(tmp_path))
