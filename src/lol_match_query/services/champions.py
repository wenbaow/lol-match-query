"""英雄数据提供者。

从 Data Dragon CDN 获取英雄头像与中文名，支持本地磁盘缓存与后台预加载。
"""
import os
import io
import threading

import requests
import customtkinter as ctk
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
                self.version = resp.json()[0]
                self._log(f'Data Dragon 版本: {self.version}')

                url = f'{self.CDN_BASE}/{self.version}/data/zh_CN/champion.json'
                resp = requests.get(url, timeout=10)
                for en_name, info in resp.json()['data'].items():
                    self.champion_map[info['key']] = {
                        'en_name': en_name,
                        'cn_name': info['name'],
                    }

                with self._lock:
                    self._initialized = True
                self._log(f'已加载 {len(self.champion_map)} 个英雄数据')
                if done_callback:
                    done_callback()
            except Exception as e:
                self._log(f'Data Dragon 初始化失败: {e}')

        threading.Thread(target=_init, daemon=True).start()

    def get_champion_name(self, champion_id):
        """获取英雄中文名"""
        info = self.champion_map.get(str(champion_id))
        return info['cn_name'] if info else None

    def preload_icons_async(self, champion_ids, done_callback=None):
        """后台批量下载英雄头像文件到本地缓存"""
        if not self.initialized:
            return

        def _download():
            downloaded = False
            for cid in champion_ids:
                if cid in self._preloading:
                    continue
                info = self.champion_map.get(str(cid))
                if not info:
                    continue
                cache_path = os.path.join(self.cache_dir, f'{info["en_name"]}_64.png')
                if os.path.exists(cache_path):
                    continue
                self._preloading.add(cid)
                try:
                    url = f'{self.CDN_BASE}/{self.version}/img/champion/{info["en_name"]}.png'
                    resp = requests.get(url, timeout=10)
                    Image.open(io.BytesIO(resp.content)).save(cache_path)
                    downloaded = True
                except Exception as e:
                    self._log(f'下载英雄头像失败({info["en_name"]}): {e}')
                finally:
                    self._preloading.discard(cid)
            if downloaded and done_callback:
                done_callback()

        threading.Thread(target=_download, daemon=True).start()

    def get_champion_icon(self, champion_id, size=30):
        """从本地缓存读取头像并创建 CTkImage（须在主线程调用）"""
        key = (champion_id, size)
        if key in self.icon_cache:
            return self.icon_cache[key]

        info = self.champion_map.get(str(champion_id))
        if not info:
            return None

        cache_path = os.path.join(self.cache_dir, f'{info["en_name"]}_64.png')
        if not os.path.exists(cache_path):
            return None

        try:
            img = Image.open(cache_path)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
            self.icon_cache[key] = ctk_img
            return ctk_img
        except Exception:
            return None
