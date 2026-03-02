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

    # 超时配置（秒）
    INIT_TIMEOUT = 10  # 插件初始化超时
    COMMAND_TIMEOUT = 60  # 默认命令超时
    FAST_COMMAND_TIMEOUT = 30  # 快速命令超时（如搜索）
    HEALTH_CHECK_TIMEOUT = 5  # 健康检查超时

    # 重试配置
    MAX_RETRIES = 3  # 最大重试次数
    RETRY_DELAY = 1  # 重试延迟（秒）

    def __init__(self, config_dir: str = "conf", log=None):
        self.config_dir = config_dir
        self.lx_plugins_dir = os.path.join(config_dir, "lx_js_plugins")
        self.plugins = {}
        self.plugin_processes = {}
        self.adapter = LXAdapter()
        self.log = log  # 添加日志对象

        # 确保插件目录存在
        os.makedirs(self.lx_plugins_dir, exist_ok=True)

    def parse_plugin_metadata(self, plugin_path: str) -> Dict[str, str]:
        """
        从插件文件中解析元信息
        支持格式：
        /*!
         * @name 插件名称
         * @description 插件描述
         * @version 版本号
         * @author 作者
         * @homepage 主页URL
         */
        """
        try:
            with open(plugin_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 查找注释块
            import re
            comment_pattern = r'/\*\*(.*?)\*/'
            comment_match = re.search(comment_pattern, content, re.DOTALL)

            if not comment_match:
                return {}

            comment_block = comment_match.group(1)

            # 解析元信息字段
            metadata = {}
            field_pattern = r'\s*\*\s*@(\w+)\s+(.+?)(?:\n|$)'

            for match in re.finditer(field_pattern, comment_block):
                field_name = match.group(1)
                field_value = match.group(2).strip()

                # 字段长度限制
                if field_name == 'name' and len(field_value) > 30:
                    field_value = field_value[:30]
                elif field_name == 'description' and len(field_value) > 100:
                    field_value = field_value[:100]
                elif field_name == 'version' and len(field_value) > 20:
                    field_value = field_value[:20]
                elif field_name == 'author' and len(field_value) > 50:
                    field_value = field_value[:50]
                elif field_name == 'homepage' and len(field_value) > 200:
                    field_value = field_value[:200]

                metadata[field_name] = field_value

            return metadata

        except Exception as e:
            self._log('error', f"Failed to parse plugin metadata from {plugin_path}: {e}")
            return {}

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

    def get_plugin_info(self, plugin_name: str) -> Dict:
        """
        获取插件的详细信息
        返回格式：
        {
            "name": "插件名称",
            "description": "插件描述",
            "version": "版本号",
            "author": "作者",
            "homepage": "主页URL",
            "path": "插件路径",
            "enabled": true/false
        }
        """
        plugin_path = os.path.join(self.lx_plugins_dir, f"{plugin_name}.js")

        if not os.path.exists(plugin_path):
            return {}

        # 解析元信息
        metadata = self.parse_plugin_metadata(plugin_path)

        # 检查插件是否已加载
        is_loaded = plugin_name in self.plugin_processes

        plugin_info = {
            "name": metadata.get("name", plugin_name),
            "description": metadata.get("description", ""),
            "version": metadata.get("version", "1.0.0"),
            "author": metadata.get("author", ""),
            "homepage": metadata.get("homepage", ""),
            "path": plugin_path,
            "enabled": is_loaded
        }

        return plugin_info

    def get_all_plugins_info(self) -> List[Dict]:
        """获取所有插件的详细信息列表"""
        plugins_info = []
        for plugin_name in self.get_available_plugins():
            plugin_info = self.get_plugin_info(plugin_name)
            if plugin_info:
                plugins_info.append(plugin_info)
        return plugins_info

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

    async def _send_command(self, plugin_name: str, method: str, params: dict, max_retries: int = None) -> dict:
        """
        向插件进程发送命令并获取响应
        支持重试机制和灵活的超时配置
        """
        if max_retries is None:
            max_retries = self.MAX_RETRIES

        self._log('debug', f"[_send_command] plugin_name={plugin_name}, method={method}")
        self._log('debug', f"[_send_command] Available plugins in self.plugins: {list(self.plugins.keys())}")
        self._log('debug', f"[_send_command] Available plugin_processes: {list(self.plugin_processes.keys())}")

        if plugin_name not in self.plugin_processes:
            self._log('error', f"[_send_command] Plugin {plugin_name} not in plugin_processes")
            self._log('error', f"[_send_command] Available: {list(self.plugin_processes.keys())}")
            raise Exception(f"Plugin {plugin_name} not loaded")

        process = self.plugin_processes[plugin_name]

        # 根据方法类型选择超时时间
        if method in ['search', 'getLyric']:
            timeout = self.FAST_COMMAND_TIMEOUT
        else:
            timeout = self.COMMAND_TIMEOUT

        # 重试机制
        for attempt in range(max_retries):
            try:
                # 创建请求
                request = {
                    'id': id(self) + attempt,  # 使用对象ID+重试次数作为请求ID
                    'method': method,
                    'params': params
                }

                self._log('debug', f"Sending command to plugin {plugin_name}: method={method}, params={json.dumps(params, ensure_ascii=False)}")

                # 发送请求
                process.stdin.write((json.dumps(request) + '\n').encode())
                await process.stdin.drain()

                # 读取响应
                line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout)
                response = json.loads(line.decode())
                self._log('debug', f"Received response from plugin {plugin_name}: {line.decode()}")

                # 检查响应是否有效
                if 'error' in response and response['error']:
                    self._log('error', f"Plugin {plugin_name} returned error: {response['error']}")
                    # 如果是最后一次重试，返回错误
                    if attempt == max_retries - 1:
                        return response
                    # 否则重试
                    await asyncio.sleep(self.RETRY_DELAY)
                    continue

                return response

            except asyncio.TimeoutError:
                self._log('error', f"Timeout waiting for response from plugin {plugin_name} (attempt {attempt + 1}/{max_retries})")
                if attempt == max_retries - 1:
                    raise Exception(f"Timeout waiting for response from plugin {plugin_name} after {max_retries} attempts")
                # 检查进程是否还活着
                if process.returncode is not None:
                    self._log('error', f"Plugin {plugin_name} process has exited")
                    raise Exception(f"Plugin {plugin_name} process has exited")
                await asyncio.sleep(self.RETRY_DELAY)

            except json.JSONDecodeError as e:
                self._log('warning', f"Could not decode JSON response from plugin {plugin_name} (attempt {attempt + 1}/{max_retries}): {e}")
                # 尝试读取多行直到获取有效响应
                for i in range(5):  # 最多尝试5次读取
                    try:
                        line = await asyncio.wait_for(process.stdout.readline(), timeout=5.0)
                        response = json.loads(line.decode())
                        self._log('debug', f"Successfully decoded JSON on attempt {i+1}")
                        return response
                    except (asyncio.TimeoutError, json.JSONDecodeError):
                        continue
                if attempt == max_retries - 1:
                    raise Exception(f"Failed to get valid response from plugin {plugin_name} after {max_retries} attempts")
                await asyncio.sleep(self.RETRY_DELAY)

            except Exception as e:
                self._log('error', f"Error sending command to plugin {plugin_name} (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(self.RETRY_DELAY)

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

    async def health_check(self, plugin_name: str) -> bool:
        """
        检查插件进程的健康状态
        返回 True 如果插件正常运行，False 如果已崩溃或未响应
        """
        if plugin_name not in self.plugin_processes:
            self._log('debug', f"Plugin {plugin_name} not loaded")
            return False

        process = self.plugin_processes[plugin_name]

        # 检查进程是否还活着
        if process.returncode is not None:
            self._log('warning', f"Plugin {plugin_name} process has exited with code {process.returncode}")
            # 清理已退出的进程
            del self.plugin_processes[plugin_name]
            if plugin_name in self.plugins:
                del self.plugins[plugin_name]
            return False

        # 发送简单的健康检查命令（使用 search 命令作为心跳）
        try:
            response = await self._send_command(plugin_name, 'search', {
                'keyword': '',
                'page': 1,
                'limit': 1,
                'source': 'all',
                'options': {}
            })
            # 如果收到响应，说明插件正常运行
            return True
        except Exception as e:
            self._log('error', f"Health check failed for plugin {plugin_name}: {e}")
            return False

    async def graceful_unload_plugin(self, plugin_name: str) -> bool:
        """
        优雅地卸载插件
        1. 发送关闭信号
        2. 等待插件清理
        3. 超时后强制终止
        """
        if plugin_name not in self.plugin_processes:
            self._log('warning', f"Plugin {plugin_name} not loaded")
            return True

        process = self.plugin_processes[plugin_name]
        self._log('info', f"Gracefully unloading plugin {plugin_name}...")

        try:
            # 尝试优雅关闭
            process.terminate()

            # 等待进程退出（最多5秒）
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
                self._log('info', f"Plugin {plugin_name} terminated gracefully")
            except asyncio.TimeoutError:
                # 超时后强制终止
                self._log('warning', f"Plugin {plugin_name} did not terminate gracefully, forcing...")
                process.kill()
                await process.wait()

            # 清理
            del self.plugin_processes[plugin_name]
            if plugin_name in self.plugins:
                del self.plugins[plugin_name]

            return True

        except Exception as e:
            self._log('error', f"Error unloading plugin {plugin_name}: {e}")
            return False

    async def reload_plugin(self, plugin_name: str) -> bool:
        """
        重新加载插件
        先优雅卸载，然后重新加载
        """
        self._log('info', f"Reloading plugin {plugin_name}...")

        # 先卸载
        if plugin_name in self.plugin_processes:
            await self.graceful_unload_plugin(plugin_name)

        # 重新加载
        return await self.load_plugin(plugin_name)

    def check_plugin_update(self, plugin_name: str, remote_version: str) -> Dict:
        """
        检查插件是否有更新
        返回格式：
        {
            "hasUpdate": true/false,
            "currentVersion": "当前版本",
            "remoteVersion": "远程版本",
            "updateUrl": "更新URL"
        }
        """
        plugin_info = self.get_plugin_info(plugin_name)

        if not plugin_info:
            return {
                "hasUpdate": False,
                "error": "Plugin not found"
            }

        current_version = plugin_info.get("version", "1.0.0")

        # 简单的版本比较（假设版本号格式为 v1.0.0 或 1.0.0）
        def normalize_version(version):
            # 移除 'v' 前缀
            version = version.lstrip('v')
            # 分割版本号
            parts = version.split('.')
            # 补全缺失的部分
            while len(parts) < 3:
                parts.append('0')
            # 转换为整数
            return tuple(int(p) for p in parts[:3])

        try:
            current = normalize_version(current_version)
            remote = normalize_version(remote_version)

            has_update = remote > current

            return {
                "hasUpdate": has_update,
                "currentVersion": current_version,
                "remoteVersion": remote_version,
                "updateUrl": plugin_info.get("homepage", "")
            }
        except Exception as e:
            self._log('error', f"Error comparing versions: {e}")
            return {
                "hasUpdate": False,
                "error": str(e)
            }

    def get_plugin_update_alert(self, plugin_name: str) -> Optional[Dict]:
        """
        获取插件更新提示信息
        如果插件在初始化时发送了 updateAlert 事件，返回该信息
        """
        # 这个方法需要配合 lx_plugin_runner.js 的 updateAlert 事件使用
        # 目前返回 None，将来可以从插件进程获取更新信息
        return None

    async def enable_plugin_update_alert(self, plugin_name: str, enabled: bool = True):
        """
        启用或禁用插件更新提示
        """
        # 这个方法可以用于配置插件是否允许显示更新提示
        # 目前只是一个占位符，将来可以添加到配置文件中
        pass
