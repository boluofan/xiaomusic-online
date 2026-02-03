import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from .lx_adapter import LXAdapter


class LXPluginManager:
    """
    洛雪插件管理器
    负责管理洛雪插件的加载、运行和调用
    """

    def __init__(self, config_dir: str = "conf", log=None):
        self.config_dir = config_dir
        self.lx_plugins_dir = os.path.join(config_dir, "lx_js_plugins")
        self.plugins = {}
        self.plugin_processes = {}
        self.adapter = LXAdapter()
        self.log = log  # 添加日志对象

        # 确保插件目录存在
        os.makedirs(self.lx_plugins_dir, exist_ok=True)

    def _log(self, level, message):
        """记录日志的辅助方法"""
        if self.log:
            if level == 'debug':
                self.log.debug(message)
            elif level == 'info':
                self.log.info(message)
            elif level == 'warning':
                self.log.warning(message)
            elif level == 'error':
                self.log.error(message)
        else:
            # 如果没有日志对象，使用 print
            print(f"[LXPluginManager] {level.upper()}: {message}")

    def get_available_plugins(self) -> List[str]:
        """获取可用的洛雪插件列表"""
        plugins = []
        for file in os.listdir(self.lx_plugins_dir):
            if file.endswith('.js'):
                plugin_name = file[:-3]  # 移除.js后缀
                plugins.append(plugin_name)
        return plugins

    async def load_plugin(self, plugin_name: str) -> bool:
        """加载指定的洛雪插件"""
        plugin_path = os.path.join(self.lx_plugins_dir, f"{plugin_name}.js")
        if not os.path.exists(plugin_path):
            self._log('error', f"Plugin {plugin_name} not found at {plugin_path}")
            return False

        try:
            # 启动Node.js进程运行插件
            node_path = self._get_node_path()
            if not node_path:
                self._log('error', "Node.js not found, please install Node.js")
                return False

            # 使用绝对路径
            runner_abs_path = os.path.join(os.path.dirname(__file__), "lx_plugin_runner.js")
            plugin_abs_path = os.path.abspath(plugin_path)  # 转换插件路径为绝对路径

            self._log('debug', f"Running node with - Script: {runner_abs_path}, Plugin: {plugin_abs_path}")
            self._log('debug', f"Working directory: {os.path.dirname(__file__)}")

            process = await asyncio.create_subprocess_exec(
                node_path, runner_abs_path, plugin_abs_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
                cwd=os.path.dirname(__file__)  # 保持原来的工作目录
            )

            # 等待初始化完成
            try:
                # 读取多行，直到找到初始化成功的响应
                initialization_response_found = False
                timeout_time = time.time() + 25  # 增加超时时间

                while time.time() < timeout_time:
                    try:
                        line = await asyncio.wait_for(process.stdout.readline(), timeout=3.0)  # 增加超时时间
                        if line:
                            line_str = line.decode().strip()
                            if not line_str:
                                continue
                            try:
                                response = json.loads(line_str)
                                self._log('debug', f"Received response: {response}")

                                # 检查是否是初始化响应 (id为null, 包含result和error字段)
                                if (response.get('id') is None and
                                    'result' in response and
                                    'error' in response):
                                    # 如果有错误，立即返回失败
                                    if response.get('error'):
                                        self._log('error', f"Plugin initialization failed: {response.get('error')}")
                                        return False
                                    # 检查是否是初始化成功的响应
                                    elif isinstance(response.get('result'), dict) and response.get('result', {}).get('initialized'):
                                        # 找到了初始化成功的响应
                                        self._log('debug', "Found initialization success response")
                                        initialization_response_found = True
                                        break
                                    else:
                                        # 这不是最终的初始化响应，继续等待
                                        self._log('debug', f"This is not the final init response: {response}")
                                        continue
                                # 如果是插件初始化信息（event为'inited'），则忽略并继续读取
                                elif response.get('event') == 'inited':
                                    sources = list(response.get('data', {}).get('sources', {}).keys())
                                    self._log('debug', f"Received plugin sources info: {sources}")
                                    continue  # 继续等待最终的初始化响应
                                else:
                                    self._log('debug', f"Received other response during init: {response}")
                                    continue  # 继续等待
                            except json.JSONDecodeError:
                                # 非JSON行，可能是日志信息，继续读取
                                self._log('debug', f"Received non-JSON line during initialization: {line_str}")
                                continue
                    except asyncio.TimeoutError:
                        # 检查进程是否还活着
                        if process.returncode is not None:
                            self._log('error', f"Plugin process for {plugin_name} has exited with code {process.returncode}")
                            stdout, stderr = await process.communicate()
                            if stderr:
                                self._log('error', f"Process stderr: {stderr.decode()}")
                            if stdout:
                                self._log('debug', f"Process stdout: {stdout.decode()}")
                            return False
                        continue  # 继续等待

                if not initialization_response_found:
                    self._log('error', f"No initialization response received for plugin {plugin_name}")
                    # 尝试读取任何错误输出
                    try:
                        stderr_output, _ = await asyncio.wait_for(process.communicate(), timeout=2.0)
                        if stderr_output:
                            self._log('error', f"Node.js process stderr: {stderr_output.decode()}")
                    except:
                        pass  # 超时或其他问题，忽略
                    # 尝试终止进程
                    try:
                        process.terminate()
                        await process.wait()
                    except:
                        pass
                    return False

                self._log('info', f"Plugin {plugin_name} initialized successfully")
                self.plugin_processes[plugin_name] = process
                self.plugins[plugin_name] = {
                    'path': plugin_path,
                    'process': process
                }
                return True
            except asyncio.TimeoutError:
                self._log('error', f"Timeout initializing plugin {plugin_name}")
                # 尝试终止进程
                try:
                    process.terminate()
                    await process.wait()
                except:
                    pass
                return False

        except Exception as e:
            self._log('error', f"Error loading plugin {plugin_name}: {e}")
            import traceback
            traceback.print_exc()
            return False

        except Exception as e:
            self._log('error', f"Error loading plugin {plugin_name}: {e}")
            return False

    async def unload_plugin(self, plugin_name: str) -> bool:
        """卸载指定的洛雪插件"""
        if plugin_name in self.plugin_processes:
            process = self.plugin_processes[plugin_name]
            try:
                process.terminate()
                await process.wait()
                del self.plugin_processes[plugin_name]
                if plugin_name in self.plugins:
                    del self.plugins[plugin_name]
                self._log('info', f"Plugin {plugin_name} unloaded successfully")
                return True
            except Exception as e:
                self._log('error', f"Error unloading plugin {plugin_name}: {e}")
                return False
        return False

    async def _send_command(self, plugin_name: str, method: str, params: dict) -> dict:
        """向插件进程发送命令并获取响应"""
        self._log('debug', f"[_send_command] plugin_name={plugin_name}, method={method}")
        self._log('debug', f"[_send_command] Available plugins in self.plugins: {list(self.plugins.keys())}")
        self._log('debug', f"[_send_command] Available plugin_processes: {list(self.plugin_processes.keys())}")

        if plugin_name not in self.plugin_processes:
            self._log('error', f"[_send_command] Plugin {plugin_name} not in plugin_processes")
            self._log('error', f"[_send_command] Available: {list(self.plugin_processes.keys())}")
            raise Exception(f"Plugin {plugin_name} not loaded")

        process = self.plugin_processes[plugin_name]

        # 创建请求
        request = {
            'id': id(self),  # 使用对象ID作为请求ID
            'method': method,
            'params': params
        }

        self._log('debug', f"Sending command to plugin {plugin_name}: method={method}, params={json.dumps(params, ensure_ascii=False)}")

        # 发送请求
        process.stdin.write((json.dumps(request) + '\n').encode())
        await process.stdin.drain()

        # 读取响应 - 溯音插件可能需要更长的超时时间
        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=60.0)
            response = json.loads(line.decode())
            self._log('debug', f"Received response from plugin {plugin_name}: {line.decode()}")
            return response
        except asyncio.TimeoutError:
            self._log('error', f"Timeout waiting for response from plugin {plugin_name}")
            raise Exception(f"Timeout waiting for response from plugin {plugin_name}")
        except json.JSONDecodeError:
            # 如果无法解析JSON，可能是因为收到了非JSON数据
            # 尝试读取多行直到获取有效响应
            self._log('warning', f"Could not decode JSON response from plugin {plugin_name}, retrying...")
            # 继续读取直到超时或获取有效响应
            for i in range(10):  # 最多重试10次
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=10.0)
                    response = json.loads(line.decode())
                    self._log('debug', f"Successfully decoded JSON on attempt {i+1}")
                    return response
                except (asyncio.TimeoutError, json.JSONDecodeError):
                    self._log('debug', f"Retry {i+1} failed to decode JSON")
                    continue
            self._log('error', f"Failed to get valid response from plugin {plugin_name} after 10 retries")
            raise Exception(f"Failed to get valid response from plugin {plugin_name}")

    def _get_node_path(self) -> Optional[str]:
        """获取Node.js路径"""
        # 尝试在系统PATH中查找node
        import shutil
        node_path = shutil.which("node")
        if node_path:
            return node_path

        # 如果没找到，尝试常见安装路径
        common_paths = [
            "C:\\Program Files\\nodejs\\node.exe",
            "C:\\Program Files (x86)\\nodejs\\node.exe",
            os.path.expanduser("~/AppData/Roaming/npm/node.exe")
        ]

        for path in common_paths:
            if os.path.exists(path):
                return path

        return None

    async def search(self, plugin_name: str, keyword: str, page: int = 1,
                     limit: int = 30, source: str = 'all', **kwargs) -> List[Dict]:
        """搜索音乐"""
        self._log('info', f"[搜索] 插件={plugin_name}, 关键词={keyword}, 页码={page}, 限制={limit}, 音源={source}")
        if plugin_name not in self.plugins:
            self._log('debug', f"Plugin {plugin_name} not loaded, loading...")
            await self.load_plugin(plugin_name)

        try:
            response = await self._send_command(plugin_name, 'search', {
                'keyword': keyword,
                'page': page,
                'limit': limit,
                'source': source,
                'options': kwargs
            })

            if response.get('error'):
                self._log('error', f"[搜索失败] 插件={plugin_name}, 错误={response['error']}")
                return []

            # 使用适配器转换结果格式
            result = response.get('result', [])
            self._log('info', f"[搜索成功] 插件={plugin_name}, 结果数量={len(result)}")
            return self.adapter.adapt_search_result(result)

        except Exception as e:
            self._log('error', f"[搜索异常] 插件={plugin_name}, 异常={e}")
            return []

    async def get_media_source(self, plugin_name: str, music_item: Dict,
                              source: str = 'all', **kwargs) -> Optional[Dict]:
        """获取媒体源"""
        song_name = music_item.get('name', 'Unknown')
        self._log('info', f"[获取播放链接] 插件={plugin_name}, 歌曲={song_name}, 音源={source}")
        if plugin_name not in self.plugins:
            self._log('debug', f"Plugin {plugin_name} not loaded, loading...")
            await self.load_plugin(plugin_name)

        try:
            response = await self._send_command(plugin_name, 'getMediaSource', {
                'musicItem': music_item,
                'source': source,
                'options': kwargs
            })

            if response.get('error'):
                self._log('error', f"[获取播放链接失败] 插件={plugin_name}, 歌曲={song_name}, 错误={response['error']}")
                return None

            result = response.get('result')
            self._log('info', f"[获取播放链接成功] 插件={plugin_name}, 歌曲={song_name}")
            return self.adapter.adapt_media_source(result)

        except Exception as e:
            self._log('error', f"[获取播放链接异常] 插件={plugin_name}, 歌曲={song_name}, 异常={e}")
            return None

    async def get_lyric(self, plugin_name: str, music_item: Dict,
                       source: str = 'all', **kwargs) -> Optional[str]:
        """获取歌词"""
        self._log('info', f"[获取歌词] 插件={plugin_name}, 音源={source}")
        if plugin_name not in self.plugins:
            self._log('debug', f"Plugin {plugin_name} not loaded, loading...")
            await self.load_plugin(plugin_name)

        try:
            response = await self._send_command(plugin_name, 'getLyric', {
                'musicItem': music_item,
                'source': source,
                'options': kwargs
            })

            if response.get('error'):
                self._log('error', f"[获取歌词失败] 插件={plugin_name}, 歌曲={music_item}, 错误={response['error']}")
                return None

            result = response.get('result')
            self._log('info', f"[获取歌词成功] 插件={plugin_name}, 歌曲={music_item}")
            return self.adapter.adapt_lyric(result)

        except Exception as e:
            self._log('error', f"[获取歌词异常] 插件={plugin_name}, 歌曲={music_item}, 异常={e}")
            return None

    async def get_album(self, plugin_name: str, album_id: str, page: int = 1,
                       limit: int = 30, source: str = 'all', **kwargs) -> List[Dict]:
        """获取专辑"""
        self._log('info', f"[获取专辑] 插件={plugin_name}, 专辑ID={album_id}, 页码={page}, 音源={source}")
        if plugin_name not in self.plugins:
            self._log('debug', f"Plugin {plugin_name} not loaded, loading...")
            await self.load_plugin(plugin_name)

        try:
            response = await self._send_command(plugin_name, 'getAlbum', {
                'albumId': album_id,
                'page': page,
                'limit': limit,
                'source': source,
                'options': kwargs
            })

            if response.get('error'):
                self._log('error', f"[获取专辑失败] 插件={plugin_name}, 专辑ID={album_id}, 错误={response['error']}")
                return []

            result = response.get('result', [])
            self._log('info', f"[获取专辑成功] 插件={plugin_name}, 专辑ID={album_id}, 结果数量={len(result)}")
            return self.adapter.adapt_album_result(result)

        except Exception as e:
            self._log('error', f"[获取专辑异常] 插件={plugin_name}, 专辑ID={album_id}, 异常={e}")
            return []

    async def get_artist(self, plugin_name: str, artist_id: str, page: int = 1,
                        limit: int = 30, source: str = 'all', **kwargs) -> List[Dict]:
        """获取艺术家"""
        self._log('info', f"[获取艺术家] 插件={plugin_name}, 艺术家ID={artist_id}, 音源={source}")
        if plugin_name not in self.plugins:
            self._log('debug', f"Plugin {plugin_name} not loaded, loading...")
            await self.load_plugin(plugin_name)

        try:
            response = await self._send_command(plugin_name, 'getArtist', {
                'artistId': artist_id,
                'page': page,
                'limit': limit,
                'source': source,
                'options': kwargs
            })

            if response.get('error'):
                self._log('error', f"[获取艺术家失败] 插件={plugin_name}, 艺术家ID={artist_id}, 错误={response['error']}")
                return []

            result = response.get('result', [])
            self._log('info', f"[获取艺术家成功] 插件={plugin_name}, 艺术家ID={artist_id}, 结果数量={len(result)}")
            return self.adapter.adapt_artist_result(result)

        except Exception as e:
            self._log('error', f"[获取艺术家异常] 插件={plugin_name}, 艺术家ID={artist_id}, 异常={e}")
            return []

    async def get_recommend(self, plugin_name: str, music_item: Dict, page: int = 1,
                           limit: int = 30, source: str = 'all', **kwargs) -> List[Dict]:
        """获取推荐"""
        self._log('info', f"[获取推荐] 插件={plugin_name}, 音源={source}")
        if plugin_name not in self.plugins:
            self._log('debug', f"Plugin {plugin_name} not loaded, loading...")
            await self.load_plugin(plugin_name)

    async def close(self):
        """关闭所有插件进程"""
        for plugin_name in list(self.plugin_processes.keys()):
            await self.unload_plugin(plugin_name)
