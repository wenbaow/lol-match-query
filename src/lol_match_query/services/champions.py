"""英雄数据提供者。

从 Data Dragon CDN 获取英雄头像与中文名，支持本地磁盘缓存与后台预加载。
"""
import io
import os
import tempfile
import threading

import customtkinter as ctk
import requests
from PIL import Image


class ChampionDataProvider:
    """从 Data Dragon CDN 获取英雄头像与名称，支持本地缓存与后台预加载"""
    CDN_BASE = 'https://ddragon.leagueoflegends.com/cdn'
    VERSIONS_URL = 'https://ddragon.leagueoflegends.com/api/versions.json'

    def __init__(self, log_callback=None):
        self.version = None
        self.champion_map = {}   # champion_id(str) → {'en_name', 'cn_name'}
        self.icon_cache = {}     # (champion_id, size) → CTkImage
        self.log_callback = log_callback
        self._initialized = False
        self._lock = threading.Lock()
        self._preloading = set()   # 正在下载的英雄id，避免重复下载
        self.cache_dir = os.path.join(os.path.expanduser('~'), '.lol_helper', 'icons')
        os.makedirs(self.cache_dir, exist_ok=True)

    def _log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    @property
    def initialized(self):
        with self._lock:
            return self._initialized

    def initialize_async(self, done_callback=None):
        """后台获取版本号 + 英雄映射表"""
        def _init():
            try:
                resp = requests.get(self.VERSIONS_URL, timeout=10)
                resp.raise_for_status()
                version = resp.json()[0]
                self._log(f'Data Dragon 版本: {version}')

                url = f'{self.CDN_BASE}/{version}/data/zh_CN/champion.json'
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                champion_map = {}
                for en_name, info in resp.json().get('data', {}).items():
                    champion_map[info['key']] = {
                        'en_name': en_name,
                        'cn_name': info['name'],
                    }

                with self._lock:
                    self.version = version
                    self.champion_map = champion_map
                    self._initialized = True
                self._log(f'已加载 {len(champion_map)} 个英雄数据')
                if done_callback:
                    done_callback()
            except Exception as e:
                self._log(f'Data Dragon 初始化失败: {e}')

        threading.Thread(target=_init, daemon=True).start()

    def get_champion_name(self, champion_id):
        """获取英雄中文名"""
        with self._lock:
            info = self.champion_map.get(str(champion_id))
        return info['cn_name'] if info else None

    def _cache_path(self, en_name):
        return os.path.join(self.cache_dir, f'{en_name}_64.png')

    def _remove_cache_file(self, cache_path):
        """删除损坏的缓存文件，让下次预加载重新下载"""
        try:
            os.remove(cache_path)
            self._log(f'已删除损坏的头像缓存: {cache_path}')
        except OSError:
            pass

    def _download_icon(self, session, info):
        """下载单个头像并以原子方式写入缓存"""
        cache_path = self._cache_path(info['en_name'])
        url = f'{self.CDN_BASE}/{self.version}/img/champion/{info["en_name"]}.png'
        resp = session.get(url, timeout=10)
        resp.raise_for_status()

        with Image.open(io.BytesIO(resp.content)) as img:
            img.load()
            pil_img = img.copy()

        # 先写临时文件再 os.replace，避免中断产生半截 PNG
        fd, tmp_path = tempfile.mkstemp(
            prefix='champion_', suffix='.png', dir=self.cache_dir)
        os.close(fd)
        try:
            pil_img.save(tmp_path, format='PNG')
            os.replace(tmp_path, cache_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def preload_icons_async(self, champion_ids, done_callback=None):
        """后台批量下载英雄头像文件到本地缓存"""
        if not self.initialized:
            return

        def _download():
            downloaded = False
            session = requests.Session()
            try:
                for cid in champion_ids:
                    with self._lock:
                        info = self.champion_map.get(str(cid))
                        if not info or cid in self._preloading:
                            continue
                        self._preloading.add(cid)
                    try:
                        cache_path = self._cache_path(info['en_name'])
                        if not os.path.exists(cache_path):
                            self._download_icon(session, info)
                            downloaded = True
                    except Exception as e:
                        self._log(f'下载英雄头像失败({info["en_name"]}): {e}')
                    finally:
                        with self._lock:
                            self._preloading.discard(cid)
            finally:
                session.close()

            if downloaded and done_callback:
                try:
                    done_callback()
                except Exception as e:
                    self._log(f'头像下载完成回调异常: {e}')

        threading.Thread(target=_download, daemon=True).start()

    def get_champion_icon(self, champion_id, size=30):
        """从本地缓存读取头像并创建 CTkImage（须在主线程调用）"""
        key = (champion_id, size)
        if key in self.icon_cache:
            return self.icon_cache[key]

        with self._lock:
            info = self.champion_map.get(str(champion_id))
        if not info:
            return None

        cache_path = self._cache_path(info['en_name'])
        if not os.path.exists(cache_path):
            return None

        # 先校验图片本身；损坏则删除缓存，等下次预加载重新下载
        try:
            with Image.open(cache_path) as img:
                img.load()
                pil_img = img.copy()
        except Exception as e:
            self._log(f'头像缓存无效，将重新下载({info["en_name"]}): {e}')
            self._remove_cache_file(cache_path)
            return None

        try:
            ctk_img = ctk.CTkImage(
                light_image=pil_img, dark_image=pil_img, size=(size, size))
        except Exception as e:
            self._log(f'创建头像图像失败({info["en_name"]}): {e}')
            return None

        self.icon_cache[key] = ctk_img
        return ctk_img
