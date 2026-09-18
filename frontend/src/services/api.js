/**
 * API服务层
 * 封装所有后端接口的调用方法
 */

import request from '../utils/http.js'
import { API_ENDPOINTS, buildApiUrl } from '../config/api.js'

// 用户认证服务
export const authService = {
  // 用户登录
  login(credentials) {
    return request.post(buildApiUrl(API_ENDPOINTS.AUTH.LOGIN), credentials)
  },
  
  // 用户注册
  register(userData, config = {}) {
    return request.post(buildApiUrl(API_ENDPOINTS.AUTH.REGISTER), userData, config)
  },
  
  // 获取用户信息
  getProfile(config = {}) {
    return request.get(buildApiUrl(API_ENDPOINTS.AUTH.PROFILE), {}, config)
  },

  getCurrentUser(config = {}) {
    return request.get(buildApiUrl(API_ENDPOINTS.AUTH.ME), {}, config)
  },

  getUsers(params = {}, config = {}) {
    return request.get(buildApiUrl(API_ENDPOINTS.AUTH.USERS), params, config)
  },

  createUser(userData, config = {}) {
    return request.post(buildApiUrl(API_ENDPOINTS.AUTH.USERS), userData, config)
  },

  updateUser(userId, userData, config = {}) {
    return request.put(buildApiUrl(API_ENDPOINTS.AUTH.USER_DETAIL(userId)), userData, config)
  },

  deleteUser(userId, config = {}) {
    return request.delete(buildApiUrl(API_ENDPOINTS.AUTH.USER_DETAIL(userId)), config)
  },

  getPermissionSchema(config = {}) {
    return request.get(buildApiUrl(API_ENDPOINTS.AUTH.PERMISSION_SCHEMA), {}, config)
  },

  getUserPermissions(userId, config = {}) {
    return request.get(buildApiUrl(API_ENDPOINTS.AUTH.USER_PERMISSIONS(userId)), {}, config)
  },

  assignUserPermissions(userId, permissions, config = {}) {
    return request.put(buildApiUrl(API_ENDPOINTS.AUTH.USER_ASSIGN_PERMISSIONS(userId)), {
      permissions
    }, config)
  },
  
  // 用户登出
  logout() {
    return request.post(buildApiUrl(API_ENDPOINTS.AUTH.LOGOUT), {}, { skipAuth: true, silentError: true })
  },
  
  // 刷新token
  refreshToken() {
    return request.post(buildApiUrl(API_ENDPOINTS.AUTH.REFRESH_TOKEN))
  }
}

// 遥感影像服务
export const remoteSensingService = {
  // 获取影像列表
  getList(params = {}) {
    return request.get(buildApiUrl(API_ENDPOINTS.REMOTE_SENSING.LIST), params)
  },
  
  // 上传影像
  upload(file, metadata = {}) {
    const formData = new FormData()
    formData.append('file', file)  // 改为'file'而不是'file_path'
    
    // 添加其他元数据
    Object.keys(metadata).forEach(key => {
      formData.append(key, metadata[key])
    })
    
    // 确保路径以斜杠开头，避免相对路径问题
    const url = buildApiUrl(API_ENDPOINTS.REMOTE_SENSING.UPLOAD);
    console.log('上传请求URL:', url);
    return request.upload(url, formData, { skipAuth: true })
  },

  // 上传影像并直接计算指定指数，不要求先保存为系统图层
  analyzeUpload(file, indexType = 'ndvi', metadata = {}) {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('index_type', indexType)
    Object.keys(metadata).forEach(key => {
      if (metadata[key] !== null && metadata[key] !== undefined) {
        formData.append(key, metadata[key])
      }
    })
    return request.upload(buildApiUrl(API_ENDPOINTS.REMOTE_SENSING.ANALYZE_UPLOAD), formData, { skipAuth: true })
  },
  
  // 获取影像详情
  getDetail(id) {
    return request.get(buildApiUrl(API_ENDPOINTS.REMOTE_SENSING.DETAIL(id)))
  },
  
  // 更新影像信息
  update(id, data) {
    return request.put(buildApiUrl(API_ENDPOINTS.REMOTE_SENSING.UPDATE(id)), data)
  },
  
  // 删除影像
  delete(id) {
    return request.delete(buildApiUrl(API_ENDPOINTS.REMOTE_SENSING.DELETE(id)))
  },
  
  // 计算生态指数
  calculateIndices(imageId, indices = ['ndvi', 'ndwi', 'ndbi'], options = {}) {
    const url = buildApiUrl(API_ENDPOINTS.REMOTE_SENSING.CALCULATE_INDICES(imageId));
    const data = { indices: indices, priority: options.priority || 'normal' };
    // 调用方在网络层重试时可传回同一个 key；普通点击自动生成新的 key，
    // 同影像/同指数的跨 key 重复仍由服务端 active_fingerprint 去重。
    const idempotencyKey = options.idempotencyKey || (typeof crypto !== 'undefined' && crypto.randomUUID
      ? crypto.randomUUID()
      : `eco-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`)

    console.log('calculateIndices 调用详情:', {
      url: url,
      data: data,
      imageId: imageId,
      indices: indices
    });

    // 网络层重试和用户重复点击携带同一个键时，后端只会创建一项计算任务。
    return request.post(url, data, { headers: { 'X-Idempotency-Key': idempotencyKey } })
  },

  // 获取影像的生态指数结果
  getIndices(imageId, config = {}) {
    const url = buildApiUrl(API_ENDPOINTS.REMOTE_SENSING.GET_INDICES(imageId));
    console.log('getIndices 调用详情:', {
      url: url,
      imageId: imageId
    });
    return request.get(url, {}, config)
  }
}

// 生态指数服务
export const ecologicalIndicesService = {
  // 获取指数列表
  getList(params = {}) {
    return request.get(buildApiUrl(API_ENDPOINTS.ECOLOGICAL_INDICES.LIST), params)
  },
  
  // 创建指数计算任务
  create(data) {
    const idempotencyKey = typeof crypto !== 'undefined' && crypto.randomUUID
      ? crypto.randomUUID()
      : `eco-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
    return request.post(buildApiUrl(API_ENDPOINTS.ECOLOGICAL_INDICES.CREATE), data, {
      headers: { 'X-Idempotency-Key': idempotencyKey }
    })
  },
  
  // 获取指数详情
  getDetail(id) {
    return request.get(buildApiUrl(API_ENDPOINTS.ECOLOGICAL_INDICES.DETAIL(id)))
  },
  
  // 计算生态指数
  calculate(data) {
    return request.post(buildApiUrl(API_ENDPOINTS.ECOLOGICAL_INDICES.CALCULATE), data)
  },
  
  // 计算RSEI
  calculateRSEI(data) {
    return request.post(buildApiUrl(API_ENDPOINTS.ECOLOGICAL_INDICES.RSEI_CALCULATE), data)
  }
}

// 处理任务服务
export const processingTaskService = {
  // 获取任务列表
  getList(params = {}) {
    return request.get(buildApiUrl(API_ENDPOINTS.PROCESSING_TASKS.LIST), params)
  },
  
  // 创建任务
  create(data) {
    return request.post(buildApiUrl(API_ENDPOINTS.PROCESSING_TASKS.CREATE), data)
  },
  
  // 获取任务详情
  getDetail(id) {
    return request.get(buildApiUrl(API_ENDPOINTS.PROCESSING_TASKS.DETAIL(id)))
  },
  
  // 获取任务状态
  getStatus(id) {
    return request.get(buildApiUrl(API_ENDPOINTS.PROCESSING_TASKS.STATUS(id)))
  }
}

// 地理空间服务
export const spatialService = {
  // 获取WMS服务能力
  getWMSCapabilities() {
    return request.get(buildApiUrl(API_ENDPOINTS.SPATIAL.WMS_CAPABILITIES))
  },
  
  // WMS地图服务
  getWMSMap(params) {
    return request.get(buildApiUrl(API_ENDPOINTS.SPATIAL.WMS_MAP), params)
  },
  
  // 获取WFS服务能力
  getWFSCapabilities() {
    return request.get(buildApiUrl(API_ENDPOINTS.SPATIAL.WFS_CAPABILITIES))
  },
  
  // 获取空间图层列表
  getSpatialLayers() {
    return request.get(buildApiUrl(API_ENDPOINTS.SPATIAL.SPATIAL_LAYERS))
  },

  // 获取系统高分影像列表
  getHighResImageryList() {
    return request.get(buildApiUrl(API_ENDPOINTS.SPATIAL.HIGHRES_IMAGERY_LIST), {}, { skipAuth: true })
  },

  // 发布系统高分影像到GeoServer
  publishHighResImagery(data) {
    return request.post(buildApiUrl(API_ENDPOINTS.SPATIAL.HIGHRES_IMAGERY_PUBLISH), data, { skipAuth: true })
  },

  // 获取已发布/已上传业务图层
  getBusinessLayers(params = {}) {
    return request.get(buildApiUrl(API_ENDPOINTS.SPATIAL.BUSINESS_LAYERS), params, { skipAuth: true })
  },

  // 上传业务图层并发布到GeoServer
  uploadBusinessLayer(file, metadata = {}) {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('name', metadata.name || file.name.replace(/\.[^.]+$/, ''))
    if (metadata.description) {
      formData.append('description', metadata.description)
    }
    return request.upload(buildApiUrl(API_ENDPOINTS.SPATIAL.BUSINESS_LAYERS), formData)
  },

  // 接入外部标准服务业务图层
  createBusinessServiceLayer(data) {
    return request.post(buildApiUrl(API_ENDPOINTS.SPATIAL.BUSINESS_LAYERS), data)
  },

  // 重新发布业务图层
  publishBusinessLayer(id) {
    return request.post(buildApiUrl(API_ENDPOINTS.SPATIAL.BUSINESS_LAYER_PUBLISH(id)))
  },

  // 撤销GeoServer发布，保留上传记录
  unpublishBusinessLayer(id) {
    return request.post(buildApiUrl(API_ENDPOINTS.SPATIAL.BUSINESS_LAYER_UNPUBLISH(id)))
  },

  // 删除业务图层记录
  deleteBusinessLayer(id) {
    return request.delete(buildApiUrl(API_ENDPOINTS.SPATIAL.BUSINESS_LAYER_DETAIL(id)))
  },

  // 更新业务图层样式
  updateBusinessLayerStyle(id, data) {
    return request.post(buildApiUrl(API_ENDPOINTS.SPATIAL.BUSINESS_LAYER_STYLE(id)), data)
  },

  parseLocalVectorLayer(file) {
    const formData = new FormData()
    formData.append('file', file)
    return request.upload(buildApiUrl(API_ENDPOINTS.SPATIAL.PARSE_LOCAL_VECTOR_LAYER), formData, { skipAuth: true })
  },

  // 获取业务图层操作日志
  getBusinessLayerLogs(id) {
    return request.get(buildApiUrl(API_ENDPOINTS.SPATIAL.BUSINESS_LAYER_LOGS(id)))
  },
  
  // 发布图层到GeoServer
  publishToGeoServer(data) {
    return request.post(buildApiUrl(API_ENDPOINTS.SPATIAL.PUBLISH_TO_GEOSERVER), data)
  },
  
  // 获取GeoServer状态
  getGeoServerStatus() {
    return request.get(buildApiUrl(API_ENDPOINTS.SPATIAL.GEOSERVER_STATUS))
  }
}

// 民众意见反馈服务
export const feedbackService = {
  // 提交反馈
  create(data) {
    return request.post(buildApiUrl(API_ENDPOINTS.FEEDBACK.CREATE), data, { skipAuth: true })
  },
  // 获取反馈列表（可选：管理员查看）
  getList(params = {}) {
    return request.get(buildApiUrl(API_ENDPOINTS.FEEDBACK.LIST), params, { skipAuth: true })
  },
  // 获取反馈详情
  getDetail(id) {
    return request.get(buildApiUrl(API_ENDPOINTS.FEEDBACK.DETAIL(id)), {}, { skipAuth: true })
  },
  // 删除单条反馈
  delete(id) {
    return request.delete(buildApiUrl(API_ENDPOINTS.FEEDBACK.DELETE(id)), { skipAuth: true })
  },
  // 清空反馈记录
  clear() {
    return request.delete(buildApiUrl(API_ENDPOINTS.FEEDBACK.CLEAR), { skipAuth: true })
  }
}

// 气候监测服务
export const climateMonitoringService = {
  // 上传气候数据文件
  uploadClimateData(file, metadata = {}) {
    // 验证文件
    if (!file) {
      return Promise.reject(new Error('文件不能为空'))
    }
    
    if (!(file instanceof File)) {
      return Promise.reject(new Error('无效的文件对象'))
    }
    
    // 验证文件大小（栅格数据可能较大）
    const maxSize = 20 * 1024 * 1024 * 1024
    if (file.size > maxSize) {
      return Promise.reject(new Error('文件大小不能超过20GB'))
    }
    
    // 验证文件类型
    const fileExtension = file.name.toLowerCase().substring(file.name.lastIndexOf('.'))
    const shapefileSidecars = ['.shp', '.dbf', '.shx', '.prj', '.cpg', '.sbn', '.sbx']
    if (shapefileSidecars.includes(fileExtension)) {
      return Promise.reject(new Error('请将完整 Shapefile 组件打包为一个 ZIP 后上传，系统会自动读取属性表进行气候统计分析'))
    }
    if (!['.csv', '.xlsx', '.xls', '.tif', '.tiff', '.zip'].includes(fileExtension)) {
      return Promise.reject(new Error('支持 CSV、Excel、GeoTIFF 直接上传；ADF 或完整 Shapefile 组件请打包为 ZIP 后上传'))
    }
    
    const formData = new FormData()
    formData.append('file', file)
    
    // 添加元数据
    Object.keys(metadata).forEach(key => {
      if (metadata[key] !== null && metadata[key] !== undefined) {
        formData.append(key, metadata[key])
      }
    })
    
    return request.upload(buildApiUrl(API_ENDPOINTS.CLIMATE_MONITORING.UPLOAD), formData, { skipAuth: true })
  },
  
  // 开始气候数据分析
  analyzeClimateData(fileId, analysisType = 'comprehensive') {
    // 验证文件ID
    if (!fileId) {
      return Promise.reject(new Error('文件ID不能为空'))
    }
    
    if (typeof fileId !== 'string' && typeof fileId !== 'number') {
      return Promise.reject(new Error('文件ID格式无效'))
    }
    
    // 验证分析类型
    const validAnalysisTypes = ['comprehensive', 'temperature', 'precipitation', 'humidity', 'wind', 'wind_speed']
    if (!validAnalysisTypes.includes(analysisType)) {
      return Promise.reject(new Error(`无效的分析类型: ${analysisType}`))
    }
    const normalizedAnalysisType = analysisType === 'wind_speed' ? 'wind' : analysisType
    
    return request.post(buildApiUrl(API_ENDPOINTS.CLIMATE_MONITORING.ANALYZE), {
      file_id: fileId,
      analysis_type: normalizedAnalysisType
    }, { skipAuth: true })
  },
  
  // 获取分析结果
  getAnalysisResults(taskId) {
    // 验证任务ID
    if (!taskId) {
      return Promise.reject(new Error('任务ID不能为空'))
    }
    
    if (typeof taskId !== 'string' && typeof taskId !== 'number') {
      return Promise.reject(new Error('任务ID格式无效'))
    }
    
    return request.get(buildApiUrl(API_ENDPOINTS.CLIMATE_MONITORING.RESULTS(taskId)), {}, { skipAuth: true })
  },
  
  // 获取分析状态
  getAnalysisStatus(taskId) {
    // 验证任务ID
    if (!taskId) {
      return Promise.reject(new Error('任务ID不能为空'))
    }
    
    if (typeof taskId !== 'string' && typeof taskId !== 'number') {
      return Promise.reject(new Error('任务ID格式无效'))
    }
    
    return request.get(buildApiUrl(API_ENDPOINTS.CLIMATE_MONITORING.STATUS(taskId)), {}, { skipAuth: true })
  },
  
  // 下载分析报告
  downloadReport(taskId) {
    // 验证任务ID
    if (!taskId) {
      return Promise.reject(new Error('任务ID不能为空'))
    }
    
    if (typeof taskId !== 'string' && typeof taskId !== 'number') {
      return Promise.reject(new Error('任务ID格式无效'))
    }
    
    return request.download(buildApiUrl(API_ENDPOINTS.CLIMATE_MONITORING.DOWNLOAD_REPORT(taskId)))
  }
}

// 导出所有服务
export default {
  auth: authService,
  remoteSensing: remoteSensingService,
  ecologicalIndices: ecologicalIndicesService,
  processingTask: processingTaskService,
  spatial: spatialService,
  feedback: feedbackService,
  climateMonitoring: climateMonitoringService
}
