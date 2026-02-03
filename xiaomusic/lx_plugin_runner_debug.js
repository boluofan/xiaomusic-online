const fs = require('fs');
const path = require('path');
const { Worker, isMainThread, parentPort, workerData } = require('worker_threads');

// 模拟洛雪插件API - 适配溯音插件
const EVENT_NAMES = {
  INIT: 'inited',
  SEARCH: 'search',
  GET_LYRIC: 'get_lyric',
  GET_MEDIA_SOURCE: 'musicUrl',
  GET_ALBUM: 'get_album',
  GET_ARTIST: 'get_artist',
  GET_RECOMMEND: 'get_recommend',
  REQUEST: 'request',
  SHOW_CONFIG_VIEW: 'showConfigView',
};

// 模拟request函数 - 使用Node.js内置模块
const request = (url, options, callback) => {
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
  
  const req = httpModule.request(reqOptions, (res) => {
    let responseData = '';
    
    res.on('data', (chunk) => {
      responseData += chunk;
    });
    
    res.on('end', () => {
      try {
        const parsedData = JSON.parse(responseData);
        if (callback) {
          callback(null, { body: parsedData });
        }
      } catch (e) {
        if (callback) {
          callback(new Error(`Invalid JSON response: ${responseData}`), null);
        } else {
          console.error('Invalid JSON response:', responseData);
        }
      }
    });
  });
  
  req.on('error', (error) => {
    if (callback) {
      callback(error, null);
    } else {
      console.error('Request error:', error);
    }
  });
  
  // 设置超时
  req.setTimeout(timeout, () => {
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

// 发送消息到主进程
const send = (event, data) => {
  if (parentPort) {
    parentPort.postMessage({ event, data });
  } else {
    // 如果没有parentPort（主进程），写入stdout
    process.stdout.write(JSON.stringify({ event, data }) + '\n');
  }
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
    try {
      // 读取插件文件
      const pluginCode = fs.readFileSync(this.pluginPath, 'utf-8');
      
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
      
      console.log(`About to execute plugin: ${this.pluginPath}`);
      const script = new vm.Script(pluginCode);
      script.runInNewContext(sandbox);
      console.log(`Plugin executed successfully: ${this.pluginPath}`);
      
      return true;
    } catch (error) {
      console.error(`Failed to load plugin ${this.pluginPath}:`, error);
      console.error(`Error stack: ${error.stack}`);
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
    return new Promise((resolve, reject) => {
      try {
        if (!globalThis.lx || !globalThis.lx.send) {
          throw new Error('LX API not available');
        }

        // 为搜索结果设置一个临时处理器
        const searchHandler = (result) => {
          // 清理事件处理器
          if (globalThis.lx.events[EVENT_NAMES.SEARCH]) {
            const index = globalThis.lx.events[EVENT_NAMES.SEARCH].indexOf(searchHandler);
            if (index > -1) {
              globalThis.lx.events[EVENT_NAMES.SEARCH].splice(index, 1);
            }
          }
          resolve(result);
        };

        globalThis.lx.on(EVENT_NAMES.SEARCH, searchHandler);
        
        // 发送搜索请求到溯音插件
        globalThis.lx.send(EVENT_NAMES.REQUEST, {
          action: 'search',
          source: source,
          info: {
            keyword: keyword,
            page: page,
            limit: limit
          }
        });
      } catch (error) {
        console.error(`Search failed:`, error);
        reject(error);
      }
    });
  }

  // 获取媒体源
  async getMediaSource(musicItem, source = 'all', options = {}) {
    return new Promise((resolve, reject) => {
      try {
        if (!globalThis.lx || !globalThis.lx.send) {
          throw new Error('LX API not available');
        }

        // 为媒体源结果设置一个临时处理器
        const mediaSourceHandler = (result) => {
          // 清理事件处理器
          if (globalThis.lx.events[EVENT_NAMES.GET_MEDIA_SOURCE]) {
            const index = globalThis.lx.events[EVENT_NAMES.GET_MEDIA_SOURCE].indexOf(mediaSourceHandler);
            if (index > -1) {
              globalThis.lx.events[EVENT_NAMES.GET_MEDIA_SOURCE].splice(index, 1);
            }
          }
          resolve(result);
        };

        globalThis.lx.on(EVENT_NAMES.GET_MEDIA_SOURCE, mediaSourceHandler);
        
        // 发送媒体源请求到溯音插件
        globalThis.lx.send(EVENT_NAMES.REQUEST, {
          action: 'musicUrl',
          source: source,
          info: {
            musicInfo: musicItem,
            type: options.quality || '128k'
          }
        });
      } catch (error) {
        console.error(`Get media source failed:`, error);
        reject(error);
      }
    });
  }
}

// 主进程处理
if (isMainThread) {
  // 作为主进程运行
  const pluginPath = process.argv[2];
  if (!pluginPath) {
    console.error('Usage: node lx_plugin_runner.js <plugin_path>');
    process.exit(1);
  }

  console.log(`Loading plugin: ${pluginPath}`);
  const runner = new LXPluginRunner(pluginPath);
  
  runner.loadPlugin()
    .then(success => {
      if (success) {
        console.log('Plugin loaded successfully');
        
        // 监听来自主进程的消息
        process.stdin.setEncoding('utf8');
        let buffer = '';
        
        process.stdin.on('data', async (data) => {
          buffer += data;
          
          // 检查是否有完整的JSON行
          let newlineIndex;
          while ((newlineIndex = buffer.indexOf('\n')) !== -1) {
            const line = buffer.substring(0, newlineIndex);
            buffer = buffer.substring(newlineIndex + 1);
            
            if (line.trim() === '') continue;
            
            try {
              const message = JSON.parse(line);
              const { id, method, params } = message;
              
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
              } catch (e) {
                error = e.message;
              }
              
              const response = {
                id: id,
                result: result,
                error: error
              };
              
              process.stdout.write(JSON.stringify(response) + '\n');
            } catch (e) {
              console.error('Error processing message:', e);
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
        console.log('Sending initialization response');
        process.stdout.write(JSON.stringify(initResponse) + '\n');
      } else {
        console.error('Failed to load plugin');
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
      console.error('Error loading plugin:', error);
      const errorResponse = {
        id: null,
        result: null,
        error: error.message
      };
      process.stdout.write(JSON.stringify(errorResponse) + '\n');
      process.exit(1);
    });
}