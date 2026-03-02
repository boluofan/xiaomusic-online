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

    def adapt_playlist_result(self, lx_result: Dict) -> Dict:
        """
        将洛雪插件歌单结果转换为系统标准格式
        洛雪插件返回格式示例:
        {
          "id": "playlist_123",
          "name": "歌单名称",
          "creator": "创建者",
          "cover": "封面URL",
          "description": "描述",
          "playCount": 12345,
          "songCount": 100,
          "songs": [...]
        }
        """
        if not lx_result:
            return {}

        adapted_result = {
            "id": lx_result.get("id", ""),
            "name": lx_result.get("name", ""),
            "title": lx_result.get("name", ""),  # 兼容字段
            "creator": lx_result.get("creator", ""),
            "author": lx_result.get("creator", ""),  # 兼容字段
            "cover": lx_result.get("cover", ""),
            "coverUrl": lx_result.get("cover", ""),  # 兼容字段
            "description": lx_result.get("description", ""),
            "intro": lx_result.get("description", ""),  # 兼容字段
            "playCount": lx_result.get("playCount", 0),
            "play_count": lx_result.get("playCount", 0),  # 兼容字段
            "songCount": lx_result.get("songCount", 0),
            "song_count": lx_result.get("songCount", 0),  # 兼容字段
            "platform": lx_result.get("source", ""),
        }

        # 处理歌曲列表
        songs = lx_result.get("songs", [])
        if songs:
            adapted_result["songs"] = self.adapt_search_result(songs)

        # 保留原始洛雪字段作为扩展信息
        adapted_result["lx_data"] = lx_result

        return adapted_result

    def adapt_song_detail(self, lx_result: Dict) -> Dict:
        """
        将洛雪插件歌曲详情转换为系统标准格式
        洛雪插件返回格式示例:
        {
          "id": "tx_123456",
          "name": "歌曲名",
          "singer": "歌手名",
          "albumName": "专辑名",
          "interval": "03:45",
          "source": "tx",
          "album": {
            "id": "album_123",
            "name": "专辑名",
            "pic": "封面URL"
          },
          "artist": {
            "id": "artist_123",
            "name": "歌手名",
            "pic": "头像URL"
          }
        }
        """
        if not lx_result:
            return {}

        adapted_result = {
            "id": lx_result.get("id", ""),
            "title": lx_result.get("name", ""),
            "name": lx_result.get("name", ""),  # 兼容字段
            "artist": lx_result.get("singer", ""),
            "singer": lx_result.get("singer", ""),  # 兼容字段
            "album": lx_result.get("albumName", ""),
            "albumName": lx_result.get("albumName", ""),  # 兼容字段
            "platform": lx_result.get("source", ""),
            "source": lx_result.get("source", ""),  # 兼容字段
        }

        # 处理时长
        interval_str = lx_result.get("interval")
        if interval_str:
            try:
                parts = interval_str.split(':')
                if len(parts) == 2:
                    minutes = int(parts[0])
                    seconds = int(parts[1])
                    adapted_result["duration"] = minutes * 60 + seconds
                elif len(parts) == 3:
                    hours = int(parts[0])
                    minutes = int(parts[1])
                    seconds = int(parts[2])
                    adapted_result["duration"] = hours * 3600 + minutes * 60 + seconds
            except (ValueError, AttributeError):
                adapted_result["duration"] = 0

        # 处理专辑信息
        album_info = lx_result.get("album")
        if album_info:
            adapted_result["albumInfo"] = {
                "id": album_info.get("id", ""),
                "name": album_info.get("name", ""),
                "cover": album_info.get("pic", "")
            }

        # 处理艺术家信息
        artist_info = lx_result.get("artist")
        if artist_info:
            adapted_result["artistInfo"] = {
                "id": artist_info.get("id", ""),
                "name": artist_info.get("name", ""),
                "avatar": artist_info.get("pic", "")
            }

        # 处理封面
        pic = lx_result.get("pic")
        if pic:
            adapted_result["cover"] = pic
            adapted_result["coverUrl"] = pic

        # 保留原始洛雪字段作为扩展信息
        adapted_result["lx_data"] = lx_result

        return adapted_result

    def adapt_comment_result(self, lx_result: List[Dict]) -> List[Dict]:
        """
        将洛雪插件评论结果转换为系统标准格式
        """
        if not lx_result:
            return []

        adapted_result = []
        for item in lx_result:
            adapted_item = {
                "id": item.get("id", ""),
                "content": item.get("content", ""),
                "text": item.get("content", ""),  # 兼容字段
                "userId": item.get("userId", ""),
                "userName": item.get("userName", ""),
                "nickname": item.get("userName", ""),  # 兼容字段
                "avatar": item.get("avatar", ""),
                "likeCount": item.get("likeCount", 0),
                "liked_count": item.get("likeCount", 0),  # 兼容字段
                "time": item.get("time", 0),
                "platform": item.get("source", ""),
            }

            # 处理时间戳转换
            time_value = item.get("time")
            if time_value:
                try:
                    adapted_item["timestamp"] = int(time_value)
                except (ValueError, TypeError):
                    adapted_item["timestamp"] = 0

            # 保留原始洛雪字段作为扩展信息
            adapted_item["lx_data"] = item

            adapted_result.append(adapted_item)

        return adapted_result

    def adapt_hot_search(self, lx_result: List[Dict]) -> List[Dict]:
        """
        将洛雪插件热搜结果转换为系统标准格式
        """
        if not lx_result:
            return []

        adapted_result = []
        for item in lx_result:
            adapted_item = {
                "keyword": item.get("keyword", ""),
                "content": item.get("keyword", ""),  # 兼容字段
                "score": item.get("score", 0),
                "hotValue": item.get("score", 0),  # 兼容字段
                "platform": item.get("source", ""),
            }

            # 保留原始洛雪字段作为扩展信息
            adapted_item["lx_data"] = item

            adapted_result.append(adapted_item)

        return adapted_result
    
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