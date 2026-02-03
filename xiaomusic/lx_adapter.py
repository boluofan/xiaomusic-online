from typing import Any, Dict, List, Optional


class LXAdapter:
    """
    洛雪插件适配器
    负责将洛雪插件返回的数据格式转换为系统标准格式
    """
    
    def __init__(self):
        pass
    
    def adapt_search_result(self, lx_result: List[Dict]) -> List[Dict]:
        """
        将洛雪插件搜索结果转换为系统标准格式
        洛雪插件返回格式示例:
        [
          {
            "id": "tx_123456",
            "name": "歌曲名",
            "singer": "歌手名",
            "albumName": "专辑名",
            "interval": "03:45",
            "source": "tx"
          }
        ]
        
        系统标准格式:
        [
          {
            "id": "tx_123456",
            "title": "歌曲名",
            "artist": "歌手名", 
            "album": "专辑名",
            "duration": 225,  # 以秒为单位
            "platform": "tx"  # 来源平台
          }
        ]
        """
        if not lx_result:
            return []
        
        adapted_result = []
        for item in lx_result:
            adapted_item = {
                "id": item.get("id", ""),
                "title": item.get("name", ""),  # 洛雪使用name字段
                "artist": item.get("singer", ""),  # 洛雪使用singer字段
                "album": item.get("albumName", ""),  # 洛雪使用albumName字段
                "platform": item.get("source", ""),  # 来源平台
            }
            
            # 处理时长格式 (洛雪格式为 MM:SS，需要转换为秒)
            interval_str = item.get("interval")
            if interval_str:
                try:
                    parts = interval_str.split(':')
                    if len(parts) == 2:  # MM:SS
                        minutes = int(parts[0])
                        seconds = int(parts[1])
                        adapted_item["duration"] = minutes * 60 + seconds
                    elif len(parts) == 3:  # HH:MM:SS
                        hours = int(parts[0])
                        minutes = int(parts[1])
                        seconds = int(parts[2])
                        adapted_item["duration"] = hours * 3600 + minutes * 60 + seconds
                    else:
                        adapted_item["duration"] = 0
                except (ValueError, AttributeError):
                    adapted_item["duration"] = 0
            else:
                adapted_item["duration"] = 0
            
            # 保留原始洛雪字段作为扩展信息
            adapted_item["lx_data"] = item
            
            adapted_result.append(adapted_item)
        
        return adapted_result
    
    def adapt_media_source(self, lx_result: Optional[Dict]) -> Optional[Dict]:
        """
        将洛雪插件媒体源结果转换为系统标准格式
        洛雪插件返回格式示例:
        {
          "url": "https://music.example.com/song.mp3",
          "bitrate": "320kbps",
          "size": "8.5MB",
          "source": "tx"
        }
        
        系统标准格式:
        {
          "url": "https://music.example.com/song.mp3",
          "quality": "320kbps",
          "size": "8.5MB", 
          "platform": "tx"
        }
        """
        if not lx_result:
            return None
        
        adapted_result = {
            "url": lx_result.get("url", ""),
            "quality": lx_result.get("bitrate", ""),  # 洛雪使用bitrate字段
            "size": lx_result.get("size", ""),
            "platform": lx_result.get("source", ""),  # 来源平台
        }
        
        # 保留原始洛雪字段作为扩展信息
        adapted_result["lx_data"] = lx_result
        
        return adapted_result
    
    def adapt_lyric(self, lx_result: Optional[str]) -> Optional[str]:
        """
        将洛雪插件歌词结果转换为系统标准格式
        洛雪插件直接返回歌词字符串，与系统格式一致
        """
        return lx_result
    
    def adapt_album_result(self, lx_result: List[Dict]) -> List[Dict]:
        """
        将洛雪插件专辑结果转换为系统标准格式
        """
        if not lx_result:
            return []
        
        adapted_result = []
        for item in lx_result:
            adapted_item = {
                "id": item.get("id", ""),
                "title": item.get("name", ""),
                "artist": item.get("artist", ""),
                "cover": item.get("cover", ""),
                "description": item.get("description", ""),
                "platform": item.get("source", ""),
            }
            
            # 处理歌曲列表
            songs = item.get("songs", [])
            if songs:
                adapted_item["songs"] = self.adapt_search_result(songs)
            
            # 保留原始洛雪字段作为扩展信息
            adapted_item["lx_data"] = item
            
            adapted_result.append(adapted_item)
        
        return adapted_result
    
    def adapt_artist_result(self, lx_result: List[Dict]) -> List[Dict]:
        """
        将洛雪插件艺术家结果转换为系统标准格式
        """
        if not lx_result:
            return []
        
        adapted_result = []
        for item in lx_result:
            adapted_item = {
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "avatar": item.get("avatar", ""),
                "description": item.get("description", ""),
                "platform": item.get("source", ""),
            }
            
            # 处理专辑列表
            albums = item.get("albums", [])
            if albums:
                adapted_item["albums"] = self.adapt_album_result(albums)
            
            # 保留原始洛雪字段作为扩展信息
            adapted_item["lx_data"] = item
            
            adapted_result.append(adapted_item)
        
        return adapted_result
    
    def adapt_recommend_result(self, lx_result: List[Dict]) -> List[Dict]:
        """
        将洛雪插件推荐结果转换为系统标准格式
        推荐结果通常与搜索结果格式类似
        """
        return self.adapt_search_result(lx_result)
    
    def adapt_to_lx_format(self, system_result: Dict) -> Dict:
        """
        将系统标准格式转换为洛雪插件格式（用于向插件传递数据）
        """
        if not system_result:
            return {}
        
        adapted_result = {
            "id": system_result.get("id", ""),
            "name": system_result.get("title", ""),  # 系统使用title，洛雪使用name
            "singer": system_result.get("artist", ""),  # 系统使用artist，洛雪使用singer
            "albumName": system_result.get("album", ""),  # 系统使用album，洛雪使用albumName
        }
        
        # 处理时长格式转换为MM:SS
        duration = system_result.get("duration", 0)
        if duration:
            minutes = duration // 60
            seconds = duration % 60
            adapted_result["interval"] = f"{minutes:02d}:{seconds:02d}"
        else:
            adapted_result["interval"] = ""
        
        # 设置平台来源
        platform = system_result.get("platform", "")
        if platform:
            adapted_result["source"] = platform
        else:
            adapted_result["source"] = "all"

        return adapted_result