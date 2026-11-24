"""配置持久化测试。"""
import json

from lol_match_query.config import DEFAULT_CONFIG, load_config, save_config


def test_load_defaults_when_missing(tmp_path):
    config = load_config(tmp_path / 'missing.json')
    assert config['overlay_enabled'] is True
    assert config['overlay_auto_query'] is True
    assert config['overlay_alpha'] == 0.95
    assert config['overlay_offset'] == [12, 56]
    assert config['overlay_collapsed'] is False
    assert config['overlay_icon_pos'] is None
    # 返回副本，修改不会污染模块级默认值
    config['overlay_offset'].append(1)
    assert DEFAULT_CONFIG['overlay_offset'] == [12, 56]


def test_roundtrip(tmp_path):
    path = tmp_path / 'nested' / 'config.json'
    config = load_config(path)
    config['overlay_enabled'] = False
    config['overlay_alpha'] = 0.8
    config['overlay_offset'] = [-10, 120]
    assert save_config(config, path) is True

    loaded = load_config(path)
    assert loaded['overlay_enabled'] is False
    assert loaded['overlay_alpha'] == 0.8
    assert loaded['overlay_offset'] == [-10, 120]


def test_corrupt_file(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text('{not json', encoding='utf-8')
    assert load_config(path) == DEFAULT_CONFIG


def test_non_dict_json(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text('[1, 2, 3]', encoding='utf-8')
    assert load_config(path) == DEFAULT_CONFIG


def test_invalid_field_types(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({
        'overlay_enabled': 'yes',
        'overlay_auto_query': 1,
        'overlay_alpha': 'bad',
        'overlay_offset': 'bad',
    }), encoding='utf-8')
    config = load_config(path)
    assert config['overlay_enabled'] is True
    assert config['overlay_auto_query'] is True
    assert config['overlay_alpha'] == 0.95
    assert config['overlay_offset'] == [12, 56]


def test_alpha_and_offset_clamped(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({
        'overlay_alpha': 5,
        'overlay_offset': [-99999, 99999],
    }), encoding='utf-8')
    config = load_config(path)
    assert config['overlay_alpha'] == 1.0
    assert config['overlay_offset'] == [-4000, 4000]

    config['overlay_alpha'] = 0.1
    save_config(config, path)
    assert load_config(path)['overlay_alpha'] == 0.55


def test_overlay_collapse_fields(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({
        'overlay_collapsed': True,
        'overlay_icon_pos': [1900, 500],
    }), encoding='utf-8')
    config = load_config(path)
    assert config['overlay_collapsed'] is True
    assert config['overlay_icon_pos'] == [1900, 500]

    path.write_text(json.dumps({
        'overlay_collapsed': 'yes',
        'overlay_icon_pos': 'bad',
    }), encoding='utf-8')
    config = load_config(path)
    assert config['overlay_collapsed'] is False
    assert config['overlay_icon_pos'] is None


def test_overlay_icon_pos_roundtrip(tmp_path):
    path = tmp_path / 'config.json'
    config = load_config(path)
    config['overlay_collapsed'] = True
    config['overlay_icon_pos'] = [-1800, 300]
    assert save_config(config, path) is True

    loaded = load_config(path)
    assert loaded['overlay_collapsed'] is True
    assert loaded['overlay_icon_pos'] == [-1800, 300]


def test_hotkey_fields(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({
        'hotkey_enabled': False,
        'hotkey': ' ctrl+shift+f ',
    }), encoding='utf-8')
    config = load_config(path)
    assert config['hotkey_enabled'] is False
    assert config['hotkey'] == 'ctrl+shift+f'

    path.write_text(json.dumps({
        'hotkey_enabled': 'no',
        'hotkey': 123,
    }), encoding='utf-8')
    config = load_config(path)
    assert config['hotkey_enabled'] is True
    assert config['hotkey'] == 'ctrl+alt+q'
