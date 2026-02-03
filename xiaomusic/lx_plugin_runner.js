const fs = require('fs');
const path = require('path');
const { Worker, isMainThread, parentPort, workerData } = require('worker_threads');

// 日志文件路径
const logFilePath = path.join(__dirname, '..', 'lx_debug.log');

// 日志辅助函数
const logToFile = (level, message) => {
  const timestamp = new Date().toISOString();
  const logMessage = `[${timestamp}] [${level}] ${message}\n`;
  
  // 写入到日志文件
  fs.appendFile(logFilePath, logMessage, (err) => {
    if (err && err.code !== 'ENOENT') {
      // 写入日志文件失败时，输出到 stderr 以避免污染 stdout
      console.error(`[LX_LOG_ERROR] Failed to write to log file: ${err.message}`);
    }
  });
  
  // 注意：不要使用 console.log 输出到控制台，因为这会污染 stdout 流
  // Python 端通过 stdout 读取 JSON 响应，任何额外的输出都会导致解析失败
  // 如果需要实时调试，请直接查看 lx_debug.log 文件
};

// 日志级别函数
const logDebug = (message) => logToFile('DEBUG', message);
const logInfo = (message) => logToFile('INFO', message);
const logWarn = (message) => logToFile('WARN', message);
const logError = (message) => logToFile('ERROR', message);

// 初始化日志文件
logInfo('========== LX Plugin Runner Starting ==========');
logInfo(`Node version: ${process.version}`);
logInfo(`Working directory: ${process.cwd()}`);
logInfo(`Log file: ${logFilePath}`);

// 模拟洛雪插件API - 适配溯音插件
const EVENT_NAMES = {
  inited: 'inited',
  INIT: 'inited',
  search: 'search',
  SEARCH: 'search',
  get_lyric: 'get_lyric',
  GET_LYRIC: 'get_lyric',
  musicUrl: 'musicUrl',
  GET_MEDIA_SOURCE: 'musicUrl',
  get_album: 'get_album',
  GET_ALBUM: 'get_album',
  get_artist: 'get_artist',
  GET_ARTIST: 'get_artist',
  get_recommend: 'get_recommend',
  GET_RECOMMEND: 'get_recommend',
  request: 'request',
  REQUEST: 'request',
  showConfigView: 'showConfigView',
  SHOW_CONFIG_VIEW: 'showConfigView',
};

// 模拟request函数 - 使用Node.js内置模块
const request = (url, options, callback) => {
  logDebug(`[HTTP Request] ${options?.method || 'GET'} ${url}`);
  
  const { URL } = require('url');
  const parsedUrl = new URL(url);
  
  let httpModule;
  if (parsedUrl.protocol === 'https:') {
    httpModule = require('https');
  } else {
    httpModule = require('http');
  }
  
  const { method = 'GET', timeout = 5000 } = options || {};
  const data = options?.data ? JSON.stringify(options.data) : null;
  const headers = { ...options?.headers } || {};
  
  // 设置适当的Content-Type
  if (data) {
    headers['Content-Type'] = 'application/json';
  }
  
  const reqOptions = {
    hostname: parsedUrl.hostname,
    port: parsedUrl.port,
    path: parsedUrl.pathname + parsedUrl.search,
    method: method,
    headers: headers,
  };
  
  const startTime = Date.now();
  
  const req = httpModule.request(reqOptions, (res) => {
    let responseData = '';
    
    res.on('data', (chunk) => {
      responseData += chunk;
    });
    
    res.on('end', () => {
      const duration = Date.now() - startTime;
      logDebug(`[HTTP Response] Status: ${res.statusCode}, Duration: ${duration}ms, Size: ${responseData.length} bytes`);
      
      try {
        const parsedData = JSON.parse(responseData);
        if (callback) {
          callback(null, { body: parsedData });
        }
      } catch (e) {
        logError(`[HTTP Error] Failed to parse JSON response: ${responseData.substring(0, 200)}`);
        if (callback) {
          callback(new Error(`Invalid JSON response: ${responseData}`), null);
        } else {
          console.error('Invalid JSON response:', responseData);
        }
      }
    });
  });
  
  req.on('error', (error) => {
    const duration = Date.now() - startTime;
    logError(`[HTTP Error] Request failed after ${duration}ms: ${error.message}`);
    if (callback) {
      callback(error, null);
    } else {
      console.error('Request error:', error);
    }
  });
  
  // 设置超时
  req.setTimeout(timeout, () => {
    const duration = Date.now() - startTime;
    logError(`[HTTP Timeout] Request timeout after ${duration}ms (limit: ${timeout}ms)`);
    req.destroy();
    if (callback) {
      callback(new Error(`Request timeout after ${timeout}ms`), null);
    }
  });
  
  // 如果有请求体数据，则写入
  if (data) {
    req.write(data);
  }
  
  req.end();
};

// 事件系统
const events = {};
const on = (event, callback) => {
  if (!events[event]) {
    events[event] = [];
  }
  events[event].push(callback);
};
const emit = (event, data) => {
  if (events[event]) {
    events[event].forEach(callback => {
      try {
        callback(data);
      } catch (error) {
        console.error(`Event callback error for ${event}:`, error);
      }
    });
  }
};

// 发送消息到主进程 - 仅用于插件内部事件
const send = (event, data) => {
  if (parentPort) {
    parentPort.postMessage({ event, data });
  } else {
    // 溯音插件在初始化时会发送sources信息，这对于主程序了解插件能力是必要的
    // 但也要发送最终的初始化完成信号
    // 我们需要区分这两种情况
    if (event === 'inited') {  // 溯音插件使用 'inited' 作为初始化事件名
      // 这是插件初始化信息（包含sources等），需要发送给主程序
      process.stdout.write(JSON.stringify({ event, data }) + '\n');
    } else {
              // 其他事件仅用于插件内部处理，不输出到stdout以免干扰命令响应
              logDebug(`[LX Plugin Event] ${event}: ${JSON.stringify(data).substring(0, 200)}`);
            }  }
};

// 处理来自外部（主进程）的请求 - 触发插件的事件处理器
const handleExternalRequest = (action, source, info) => {
  logInfo(`[Request] Action: ${action}, Source: ${source}, Info: ${JSON.stringify(info).substring(0, 200)}`);
  
  return new Promise((resolve, reject) => {
    try {
      // 查找插件注册的 request 事件处理器
      const requestHandlers = events[EVENT_NAMES.REQUEST];
      if (!requestHandlers || requestHandlers.length === 0) {
        logError(`[Request] No request handler registered for action: ${action}`);
        reject(new Error('No request handler registered'));
        return;
      }

      const startTime = Date.now();
      
      // 调用插件的请求处理器
      const handler = requestHandlers[0]; // 假设只有一个处理器
      const resultPromise = handler({ action, source, info });
      
      // 等待处理器完成
      if (resultPromise && typeof resultPromise.then === 'function') {
        resultPromise
          .then(result => {
            const duration = Date.now() - startTime;
            logInfo(`[Request] Success: ${action}, Duration: ${duration}ms`);
            logDebug(`[Request] Result: ${JSON.stringify(result).substring(0, 300)}`);
            resolve(result);
          })
          .catch(error => {
            const duration = Date.now() - startTime;
            logError(`[Request] Failed: ${action}, Duration: ${duration}ms, Error: ${error.message}`);
            reject(error);
          });
      } else {
        // 同步结果
        const duration = Date.now() - startTime;
        logInfo(`[Request] Success (sync): ${action}, Duration: ${duration}ms`);
        resolve(resultPromise);
      }
    } catch (error) {
      logError(`[Request] Exception: ${action}, Error: ${error.message}`);
      reject(error);
    }
  });
};

// 设置全局洛雪API
globalThis.lx = {
  EVENT_NAMES,
  version: '1.0.0',
  platform: 'nodejs',
  search: { limit: 30, page: 1 },
  request,
  events,
  on,
  emit,
  send
};

class LXPluginRunner {
  constructor(pluginPath) {
    this.pluginPath = pluginPath;
    this.plugin = null;
    this.pluginConfig = {};
  }

  // 读取并执行插件代码
  async loadPlugin() {
    logInfo(`[Load Plugin] Starting to load plugin: ${this.pluginPath}`);
    try {
      // 读取插件文件
      const pluginCode = fs.readFileSync(this.pluginPath, 'utf-8');
      logDebug(`[Load Plugin] Plugin code size: ${pluginCode.length} bytes`);
      
      // 创建一个新的上下文来执行插件代码
      const vm = require('vm');
      const sandbox = {
        console: console,
        require: require,
        setTimeout: setTimeout,
        setInterval: setInterval,
        clearTimeout: clearTimeout,
        clearInterval: clearInterval,
        Buffer: Buffer,
        process: process,
        __filename: this.pluginPath,
        __dirname: path.dirname(this.pluginPath),
        // 洛雪插件API
        globalThis: globalThis,  // 直接使用已设置的globalThis
        // 为兼容性添加到全局作用域
        EVENT_NAMES: EVENT_NAMES,
        request: request,
        on: on,
        send: send
      };
      
      logDebug(`[Load Plugin] About to execute plugin in VM context`);
      const script = new vm.Script(pluginCode);
      script.runInNewContext(sandbox);
      logInfo(`[Load Plugin] Plugin executed successfully: ${this.pluginPath}`);
      
      return true;
    } catch (error) {
      logError(`[Load Plugin] Failed to load plugin ${this.pluginPath}: ${error.message}`);
      logError(`[Load Plugin] Error stack: ${error.stack}`);
      if (parentPort) {
        parentPort.postMessage({
          event: 'error',
          data: { error: error.message, stack: error.stack }
        });
      }
      return false;
    }
  }

  // 执行搜索
  async search(keyword, page = 1, limit = 30, source = 'all', options = {}) {
    logInfo(`[Search] Keyword: "${keyword}", Page: ${page}, Limit: ${limit}, Source: ${source}`);
    try {
      if (!globalThis.lx || !globalThis.lx.events) {
        logError(`[Search] LX API not available`);
        throw new Error('LX API not available');
      }

      // 直接通过 emit 触发插件的事件处理器
      const result = await handleExternalRequest('search', source, {
        keyword,
        page,
        limit
      });
      logInfo(`[Search] Completed successfully, result count: ${Array.isArray(result) ? result.length : 'N/A'}`);
      return result;
    } catch (error) {
      logError(`[Search] Failed: ${error.message}`);
      throw error;
    }
  }

  // 获取媒体源
  async getMediaSource(musicItem, source = 'all', options = {}) {
    const songName = musicItem?.name || 'Unknown';
    logInfo(`[GetMediaSource] Song: "${songName}", Source: ${source}, Quality: ${options?.quality || '128k'}`);
    try {
      if (!globalThis.lx || !globalThis.lx.events) {
        logError(`[GetMediaSource] LX API not available`);
        throw new Error('LX API not available');
      }

      // 直接通过 emit 触发插件的事件处理器
      const result = await handleExternalRequest('musicUrl', source, {
        musicInfo: musicItem,
        type: options.quality || '128k'
      });
      logInfo(`[GetMediaSource] Completed successfully for song: "${songName}"`);
      return result;
    } catch (error) {
      logError(`[GetMediaSource] Failed for song "${songName}": ${error.message}`);
      throw error;
    }
  }

  // 获取歌词
  async getLyric(musicItem, source = 'all', options = {}) {
    const songName = musicItem?.name || 'Unknown';
    logInfo(`[GetLyric] Song: "${songName}", Source: ${source}`);
    try {
      if (!globalThis.lx || !globalThis.lx.events) {
        logError(`[GetLyric] LX API not available`);
        throw new Error('LX API not available');
      }

      // 直接通过 emit 触发插件的事件处理器
      const result = await handleExternalRequest('lyric', source, {
        musicInfo: musicItem
      });
      logInfo(`[GetLyric] Completed successfully for song: "${songName}"`);
      return result;
    } catch (error) {
      logError(`[GetLyric] Failed for song "${songName}": ${error.message}`);
      throw error;
    }
  }

  // 获取专辑
  async getAlbum(albumId, page = 1, limit = 30, source = 'all', options = {}) {
    logInfo(`[GetAlbum] Album ID: "${albumId}", Page: ${page}, Limit: ${limit}, Source: ${source}`);
    try {
      if (!globalThis.lx || !globalThis.lx.events) {
        logError(`[GetAlbum] LX API not available`);
        throw new Error('LX API not available');
      }

      // 直接通过 emit 触发插件的事件处理器
      const result = await handleExternalRequest('album', source, {
        albumId: albumId,
        page: page,
        limit: limit
      });
      logInfo(`[GetAlbum] Completed successfully, result count: ${Array.isArray(result) ? result.length : 'N/A'}`);
      return result;
    } catch (error) {
      logError(`[GetAlbum] Failed for album "${albumId}": ${error.message}`);
      throw error;
    }
  }

  // 获取艺术家
  async getArtist(artistId, page = 1, limit = 30, source = 'all', options = {}) {
    logInfo(`[GetArtist] Artist ID: "${artistId}", Page: ${page}, Limit: ${limit}, Source: ${source}`);
    try {
      if (!globalThis.lx || !globalThis.lx.events) {
        logError(`[GetArtist] LX API not available`);
        throw new Error('LX API not available');
      }

      // 直接通过 emit 触发插件的事件处理器
      const result = await handleExternalRequest('artist', source, {
        artistId: artistId,
        page: page,
        limit: limit
      });
      logInfo(`[GetArtist] Completed successfully, result count: ${Array.isArray(result) ? result.length : 'N/A'}`);
      return result;
    } catch (error) {
      logError(`[GetArtist] Failed for artist "${artistId}": ${error.message}`);
      throw error;
    }
  }

  // 获取推荐
  async getRecommend(musicItem, page = 1, limit = 30, source = 'all', options = {}) {
    const songName = musicItem?.name || 'Unknown';
    logInfo(`[GetRecommend] Song: "${songName}", Page: ${page}, Limit: ${limit}, Source: ${source}`);
    try {
      if (!globalThis.lx || !globalThis.lx.events) {
        logError(`[GetRecommend] LX API not available`);
        throw new Error('LX API not available');
      }

      // 直接通过 emit 触发插件的事件处理器
      const result = await handleExternalRequest('recommend', source, {
        musicInfo: musicItem,
        page: page,
        limit: limit
      });
      logInfo(`[GetRecommend] Completed successfully, result count: ${Array.isArray(result) ? result.length : 'N/A'}`);
      return result;
    } catch (error) {
      logError(`[GetRecommend] Failed for song "${songName}": ${error.message}`);
      throw error;
    }
  }
}

// 主进程处理
if (isMainThread) {
  // 作为主进程运行
  const pluginPath = process.argv[2];
  if (!pluginPath) {
    logError('Usage: node lx_plugin_runner.js <plugin_path>');
    process.exit(1);
  }

  logInfo(`[Main] Loading plugin: ${pluginPath}`);
  const runner = new LXPluginRunner(pluginPath);
  
  runner.loadPlugin()
    .then(success => {
      if (success) {
        logInfo('[Main] Plugin loaded successfully, waiting for commands...');
        // 不输出到 stdout，避免污染 JSON 响应流
        
        // 监听来自主进程的消息
        process.stdin.setEncoding('utf8');
        let buffer = '';
        let messageCount = 0;
        
        process.stdin.on('data', async (data) => {
          buffer += data;
          
          // 检查是否有完整的JSON行
          let newlineIndex;
          while ((newlineIndex = buffer.indexOf('\n')) !== -1) {
            const line = buffer.substring(0, newlineIndex);
            buffer = buffer.substring(newlineIndex + 1);
            
            if (line.trim() === '') continue;
            
            messageCount++;
            logDebug(`[Main] Received message #${messageCount}: ${line.substring(0, 200)}...`);
            
            try {
              const message = JSON.parse(line);
              const { id, method, params } = message;
              
              logInfo(`[Main] Processing method: ${method}, ID: ${id}`);
              
              const startTime = Date.now();
              let result;
              let error = null;
              
              try {
                switch (method) {
                  case 'search':
                    result = await runner.search(
                      params.keyword,
                      params.page,
                      params.limit,
                      params.source,
                      params.options
                    );
                    break;
                  case 'getMediaSource':
                    result = await runner.getMediaSource(
                      params.musicItem,
                      params.source,
                      params.options
                    );
                    break;
                  case 'getLyric':
                    result = await runner.getLyric(
                      params.musicItem,
                      params.source,
                      params.options
                    );
                    break;
                  case 'getAlbum':
                    result = await runner.getAlbum(
                      params.albumId,
                      params.page,
                      params.limit,
                      params.source,
                      params.options
                    );
                    break;
                  case 'getArtist':
                    result = await runner.getArtist(
                      params.artistId,
                      params.page,
                      params.limit,
                      params.source,
                      params.options
                    );
                    break;
                  case 'getRecommend':
                    result = await runner.getRecommend(
                      params.musicItem,
                      params.page,
                      params.limit,
                      params.source,
                      params.options
                    );
                    break;
                  default:
                    throw new Error(`Unknown method: ${method}`);
                }
                
                const duration = Date.now() - startTime;
                logInfo(`[Main] Method ${method} completed in ${duration}ms`);
                
              } catch (e) {
                error = e.message;
                logError(`[Main] Method ${method} failed: ${error}`);
              }
              
              const response = {
                id: id,
                result: result,
                error: error
              };
              
              logDebug(`[Main] Sending response for message #${messageCount}`);
              process.stdout.write(JSON.stringify(response) + '\n');
            } catch (e) {
              logError(`[Main] Error processing message: ${e.message}`);
              const errorResponse = {
                id: message ? message.id : null,
                result: null,
                error: e.message
              };
              process.stdout.write(JSON.stringify(errorResponse) + '\n');
            }
          }
        });
        
        // 发送初始化完成消息
        const initResponse = {
          id: null,
          result: { initialized: true },
          error: null
        };
        logInfo('[Main] Sending initialization response');
        // 不输出到 stdout，避免污染 JSON 响应流
        process.stdout.write(JSON.stringify(initResponse) + '\n');
      } else {
        logError('[Main] Failed to load plugin');
        const errorResponse = {
          id: null,
          result: null,
          error: 'Failed to load plugin'
        };
        process.stdout.write(JSON.stringify(errorResponse) + '\n');
        process.exit(1);
      }
    })
    .catch(error => {
      logError(`[Main] Error loading plugin: ${error.message}`);
      const errorResponse = {
        id: null,
        result: null,
        error: error.message
      };
      process.stdout.write(JSON.stringify(errorResponse) + '\n');
      process.exit(1);
    });
}
