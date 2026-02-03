import asyncio
import json
import os
from typing import Dict, List, Optional

from .js_plugin_manager import JSPluginManager
from .lx_plugin_manager import LXPluginManager


class UnifiedPluginManager:
    """
    统一插件管理器
    负责协调MusicFree插件和洛雪插件的调用
    """

    def __init__(self, config_dir: str = "conf", plugins_config_path: str = "plugins-config.json", log=None):
        self.config_dir = config_dir
        self.plugins_config_path = plugins_config_path
        self.log = log  # 添加日志对象

        # 创建一个模拟的 xiaomusic 对象，具有 config.conf_path 属性
        class MockXiaomusic:
            def __init__(self, conf_path):
                class MockConfig:
                    def __init__(self, conf_path):
                        self.conf_path = conf_path
                self.config = MockConfig(conf_path)
        mock_xiaomusic = MockXiaomusic(config_dir)
        self.js_manager = JSPluginManager(mock_xiaomusic)
        self.lx_manager = LXPluginManager(config_dir, log=log)  # 传递日志对象
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        """加载插件配置"""
        config_path = os.path.join(self.config_dir, self.plugins_config_path)
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _is_lx_plugin(self, plugin_name: str) -> bool:
        """判断是否为洛雪插件"""
        # 通过插件配置或插件文件位置来判断
        # 如果插件在洛雪插件目录中，则认为是洛雪插件
        lx_plugin_path = os.path.join(self.config_dir, "lx_js_plugins", f"{plugin_name}.js")
        return os.path.exists(lx_plugin_path)

    def get_enabled_plugins(self) -> List[str]:
        """获取启用的插件列表"""
        enabled_plugins = self.config.get("enabled_plugins", [])
        return enabled_plugins

    async def load_plugins(self):
        """加载所有启用的插件"""
        enabled_plugins = self.get_enabled_plugins()
        self._log('info', f"Loading plugins, enabled: {enabled_plugins}")

        for plugin_name in enabled_plugins:
            is_lx = self._is_lx_plugin(plugin_name)
            self._log('info', f"Checking plugin {plugin_name}, is_lx={is_lx}")
            if is_lx:
                self._log('info', f"Loading LX plugin: {plugin_name}")
                result = await self.lx_manager.load_plugin(plugin_name)
                self._log('info', f"LX plugin {plugin_name} load result: {result}")
            else:
                self._log('info', f"Loading JS plugin: {plugin_name}")
                await self.js_manager.load_plugin(plugin_name)

    async def search(self, plugin_name: str, keyword: str, page: int = 1,
                     limit: int = 30, source: str = 'all', **kwargs) -> List[Dict]:
        """统一搜索接口"""
        if self._is_lx_plugin(plugin_name):
            return await self.lx_manager.search(plugin_name, keyword, page, limit, "kw", **kwargs)
        else:
            return self.js_manager.search(plugin_name, keyword, page, limit)

    async def search_all(self, keyword: str, page: int = 1, limit: int = 30,
                        source: str = 'all', **kwargs) -> Dict[str, List[Dict]]:
        """在所有启用的插件中搜索"""
        results = {}

        enabled_plugins = self.get_enabled_plugins()

        # 并行执行搜索请求
        tasks = []
        for plugin_name in enabled_plugins:
            if self._is_lx_plugin(plugin_name):
                task = self.lx_manager.search(plugin_name, keyword, page, limit, source, **kwargs)
            else:
                task = self.js_manager.search(plugin_name, keyword, page, limit)

            tasks.append((plugin_name, task))

        # 等待所有搜索任务完成
        for plugin_name, search_task in tasks:
            try:
                result = await search_task
                results[plugin_name] = result
            except Exception as e:
                print(f"Search failed for plugin {plugin_name}: {e}")
                results[plugin_name] = []

        return results

    async def get_media_source(self, plugin_name: str, music_item: Dict,
                              source: str = 'all', **kwargs) -> Optional[Dict]:
        """统一获取媒体源接口"""
        if self._is_lx_plugin(plugin_name):
            return await self.lx_manager.get_media_source(plugin_name, music_item, source, **kwargs)
        else:
            return await self.js_manager.get_media_source(plugin_name, music_item, source, **kwargs)

    async def get_lyric(self, plugin_name: str, music_item: Dict,
                       source: str = 'all', **kwargs) -> Optional[str]:
        """统一获取歌词接口"""
        if self._is_lx_plugin(plugin_name):
            return await self.lx_manager.get_lyric(plugin_name, music_item, source, **kwargs)
        else:
            return await self.js_manager.get_lyric(plugin_name, music_item, source, **kwargs)

    async def get_album(self, plugin_name: str, album_id: str, page: int = 1,
                       limit: int = 30, source: str = 'all', **kwargs) -> List[Dict]:
        """统一获取专辑接口"""
        if self._is_lx_plugin(plugin_name):
            return await self.lx_manager.get_album(plugin_name, album_id, page, limit, source, **kwargs)
        else:
            return await self.js_manager.get_album(plugin_name, album_id, page, limit, source, **kwargs)

    async def get_artist(self, plugin_name: str, artist_id: str, page: int = 1,
                        limit: int = 30, source: str = 'all', **kwargs) -> List[Dict]:
        """统一获取艺术家接口"""
        if self._is_lx_plugin(plugin_name):
            return await self.lx_manager.get_artist(plugin_name, artist_id, page, limit, source, **kwargs)
        else:
            return await self.js_manager.get_artist(plugin_name, artist_id, page, limit, source, **kwargs)

    async def get_recommend(self, plugin_name: str, music_item: Dict, page: int = 1,
                           limit: int = 30, source: str = 'all', **kwargs) -> List[Dict]:
        """统一获取推荐接口"""
        if self._is_lx_plugin(plugin_name):
            return await self.lx_manager.get_recommend(plugin_name, music_item, page, limit, source, **kwargs)
        else:
            return await self.js_manager.get_recommend(plugin_name, music_item, page, limit, source, **kwargs)

    async def close(self):
        """关闭所有插件管理器"""
        await asyncio.gather(
            self.js_manager.close(),
            self.lx_manager.close()
        )
