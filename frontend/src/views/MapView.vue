<template>
  <div class="map-view">
    <!-- 左侧边栏 -->
    <div class="sidebar">
      <!-- 系统标题 -->
      <div class="sidebar-header">
        <svg class="brand-header-decoration" viewBox="0 0 360 110" preserveAspectRatio="none" aria-hidden="true">
          <path d="M0 0H310L360 55L310 110H0Z" class="brand-header-shape" />
        </svg>
        <div class="brand-row">
          <div class="brand-copy">
            <div class="brand-org-row">
              <div class="brand-logo" aria-hidden="true">
                <svg class="brand-logo-svg" viewBox="0 0 48 48" focusable="false">
                  <circle cx="24" cy="24" r="22" fill="#ffffff" stroke="#d8e3ef" stroke-width="1.2" />
                  <path d="M7 24C11 14.5 18 8.5 27.5 7.5C23 11.5 19 16.5 16.5 22.5C13.8 23 10.5 23.6 7 24Z" fill="#1e6fa8" />
                  <path d="M14 34C20.5 31 24.5 24.8 27.7 17.6C30 22.5 33.8 27 41.5 30.8C35.2 37.8 24.8 40.3 14 34Z" fill="#5c9f3a" />
                  <path d="M15.5 28.5C21 27 25.7 23.8 29.8 17.2C28 26 24 32 17.2 35.2C13.5 33.4 10.6 30.8 8.5 27.5C11 28.4 13.2 28.8 15.5 28.5Z" fill="#ffffff" opacity="0.92" />
                  <path d="M8 24C12 14 19.8 7.6 30 7.5" fill="none" stroke="#1f5d93" stroke-width="1.1" stroke-linecap="round" />
                </svg>
              </div>
              <div class="brand-org">甘肃煤田地质局综合普查队</div>
            </div>
            <h1>藉河流域生态环境监管信息系统</h1>
          </div>
        </div>
      </div>

      <!-- 用户信息 -->
      <div class="user-section" :class="{ 'user-section--guest': !currentUser }">
        <div class="user-section-title">用户中心</div>
        <div class="user-info">
          <div class="user-identity">
            <User class="inline-icon user-icon" />
            <span>{{ currentUser ? `${currentUser.username}（${currentUser.role_display || currentUser.role || '用户'}）` : '未登录' }}</span>
          </div>
          <button v-if="!currentUser" class="login-btn user-login-inline" @click="openLoginDialog">
            登录
          </button>
        </div>
        <div v-if="currentUser" class="user-actions">
          <button class="admin-btn governance-btn" @click="openDataGovernanceDialog">数据与备份</button>
          <button v-if="canManageUsers" class="admin-btn" @click="openUserManagementDialog">用户管理</button>
          <button class="login-btn" @click="handleLogout">
            退出
          </button>
        </div>
      </div>

      <div v-if="loginDialogVisible" class="login-mask">
        <form class="login-dialog" @submit.prevent="handleLogin" @keydown.stop>
          <div class="login-title">系统登录</div>
          <label class="login-field">
            <span>用户名</span>
            <input
              ref="loginUsernameInput"
              v-model="loginForm.username"
              name="username"
              type="text"
              autocomplete="username"
              autocapitalize="none"
              spellcheck="false"
            />
          </label>
          <label class="login-field">
            <span>密码</span>
            <input
              v-model="loginForm.password"
              name="password"
              type="password"
              autocomplete="current-password"
            />
          </label>
          <div class="login-actions">
            <button type="button" class="dialog-cancel" @click="loginDialogVisible = false">取消</button>
            <button type="button" class="dialog-cancel" @click="openRegisterDialog">注册账号</button>
            <button type="submit" class="dialog-confirm" :disabled="loginLoading">
              {{ loginLoading ? '登录中...' : '登录' }}
            </button>
          </div>
        </form>
      </div>

      <!-- 图层管理 -->
      <div class="section">
        <div class="section-header" @click="toggleLayerManagement">
          <Files class="inline-icon section-icon" />
          <span>图层管理</span>
          <ArrowDown class="inline-icon collapse-icon" :class="{ 'collapsed': !layerManagementExpanded }" />
        </div>
        
        <div class="section-content" v-show="layerManagementExpanded">
          <!-- 业务图层 -->
          <div class="layer-group">
            <div class="layer-group-header" @click="toggleBusinessLayers">
              <h4>业务图层</h4>
              <ArrowDown class="inline-icon collapse-icon" :class="{ 'collapsed': !businessLayersExpanded }" />
            </div>
            <div class="layer-group-content" v-show="businessLayersExpanded">
              <button v-if="currentUser" class="upload-btn publish-btn" :disabled="businessLayerUploading" @click="triggerBusinessLayerUpload">
                <Upload class="button-icon" />
                {{ businessLayerUploading ? '发布中...' : '上传并发布业务图层' }}
              </button>
              <button v-if="currentUser" class="upload-btn service-btn" :disabled="businessLayerUploading" @click="openBusinessServiceDialog">
                <Connection class="button-icon" />
                接入标准服务
              </button>
              <input
                ref="businessLayerInput"
                type="file"
                accept=".zip,.kml,.tif,.tiff"
                style="display: none"
                @change="handleBusinessLayerUpload"
              >
              <div class="layer-item" v-for="layer in businessLayers" :key="layer.id">
                <div class="layer-info layer-info-rich">
                  <div class="layer-main-row">
                    <component :is="layer.icon" class="inline-icon layer-icon" />
                    <div class="layer-text">
                      <span>{{ layer.name }}</span>
                      <small v-if="layer.statusText" :class="['layer-status', layer.status]">{{ layer.statusText }}</small>
                    </div>
                  </div>
                  <div v-if="layer.source === 'service'" class="layer-meta-grid">
                    <span class="layer-pill">{{ layer.typeLabel }}</span>
                    <span class="layer-pill">{{ layer.sourceFormatLabel }}</span>
                    <span v-if="layer.healthText" :class="['layer-pill', 'health-pill', `health-${layer.healthStatus}`]">{{ layer.healthText }}</span>
                  </div>
                  <div v-if="layer.source === 'service'" class="layer-detail-list">
                    <div class="layer-detail-row">
                      <span class="detail-label">来源</span>
                      <span class="detail-value">{{ layer.originLabel }}</span>
                    </div>
                    <div class="layer-detail-row">
                      <span class="detail-label">服务</span>
                      <span class="detail-value layer-url" :title="layer.primaryServiceUrl">{{ layer.primaryServiceUrl || '未生成' }}</span>
                    </div>
                    <div class="layer-detail-row">
                      <span class="detail-label">时间</span>
                      <span class="detail-value">{{ layer.createdAtText }}</span>
                    </div>
                    <div v-if="layer.description" class="layer-detail-row">
                      <span class="detail-label">描述</span>
                      <span class="detail-value">{{ layer.description }}</span>
                    </div>
                    <div v-if="layer.healthMessage" class="layer-detail-row">
                      <span class="detail-label">检测</span>
                      <span class="detail-value">{{ layer.healthMessage }}</span>
                    </div>
                  </div>
                </div>
                <div class="layer-controls">
                  <button
                    v-if="currentUser && layer.source === 'service' && layer.status !== 'published'"
                    class="layer-action-btn"
                    :disabled="isBusinessLayerBusy(layer)"
                    title="重新发布"
                    @click.stop="handleBusinessLayerPublish(layer)"
                  >
                    <Refresh class="button-icon" />
                  </button>
                  <button
                    v-if="currentUser && layer.source === 'service' && layer.status === 'published'"
                    class="layer-action-btn"
                    :disabled="isBusinessLayerBusy(layer)"
                    title="撤销发布"
                    @click.stop="handleBusinessLayerUnpublish(layer)"
                  >
                    <Close class="button-icon" />
                  </button>
                  <button
                    v-if="currentUser && layer.source === 'service'"
                    class="layer-action-btn danger"
                    :disabled="isBusinessLayerBusy(layer)"
                    title="删除记录"
                    @click.stop="handleBusinessLayerDelete(layer)"
                  >
                    <Delete class="button-icon" />
                  </button>
                  <button
                    v-if="currentUser && layer.source === 'service'"
                    class="layer-action-btn"
                    :disabled="isBusinessLayerBusy(layer)"
                    title="样式配置"
                    @click.stop="openBusinessLayerStyleDialog(layer)"
                  >
                    <Setting class="button-icon" />
                  </button>
                  <button
                    v-if="currentUser && layer.source === 'service'"
                    class="layer-action-btn"
                    :disabled="isBusinessLayerBusy(layer)"
                    title="操作日志"
                    @click.stop="openBusinessLayerLogsDialog(layer)"
                  >
                    <Files class="button-icon" />
                  </button>
                  <label class="toggle-switch">
                    <input 
                      type="checkbox" 
                      :checked="layer.visible"
                      @change="handleBusinessLayerToggle(layer)"
                    />
                    <span class="slider"></span>
                  </label>
                </div>
              </div>
            </div>
          </div>

          <!-- 临时图层 -->
          <div v-if="currentUser" class="layer-group">
            <div class="layer-group-header" @click="toggleTempLayers">
              <h4>临时图层</h4>
              <ArrowDown class="inline-icon collapse-icon" :class="{ 'collapsed': !tempLayersExpanded }" />
            </div>
            <div class="layer-group-content" v-show="tempLayersExpanded">
              <button class="upload-btn" @click="triggerFileUpload">
                <Upload class="button-icon" />
                上传本地文件 (KML/SHP.zip)
              </button>
              <input 
                ref="fileInput" 
                type="file" 
                accept=".kml,.zip,.geojson,.json" 
                style="display: none"
                @change="handleFileUpload"
              >
            </div>
          </div>

          <button class="export-btn layer-export-btn" @click="exportMap">
            <Camera class="button-icon" />
            导出地图为图片
          </button>
        </div>
      </div>

      <!-- 工具箱 -->
      <div class="section">
        <div class="section-header" @click="toggleToolbox">
          <Setting class="inline-icon section-icon" />
          <span>工具箱</span>
          <ArrowDown class="inline-icon collapse-icon" :class="{ 'collapsed': !toolboxExpanded }" />
        </div>
        <div class="section-content" v-show="toolboxExpanded">
          <p class="tool-tip">使用地图左侧的工具栏进行图形绘制。</p>
          
          <!-- 坐标定位 -->
          <div class="coordinate-section">
            <h4>坐标定位</h4>
            <div class="coordinate-inputs">
              <input type="text" placeholder="经度,纬度" v-model="coordinateInput" />
              <button class="locate-btn" @click="locateCoordinate">
                <Search class="button-icon" />
              </button>
            </div>
          </div>

        </div>
      </div>

      <!-- 业务功能 -->
      <div class="section">
        <div class="section-header" @click="toggleBusinessFunctions">
          <DataAnalysis class="inline-icon section-icon" />
          <span>业务功能</span>
          <ArrowDown class="inline-icon collapse-icon" :class="{ 'collapsed': !businessFunctionsExpanded }" />
        </div>
        <div class="section-content" v-show="businessFunctionsExpanded">
          <div class="business-functions">
            <button
              v-for="func in businessFunctions"
              :key="func.id"
              type="button"
              class="function-item"
              :class="{ active: route.path === func.route, disabled: !canAccessBusinessFunction(func) }"
              :disabled="!canAccessBusinessFunction(func)"
              @click="handleBusinessFunctionClick(func)"
            >
              <span class="function-leading">
                <span class="function-icon-box">
                  <component :is="func.icon" class="inline-icon function-icon" />
                </span>
                <span class="function-copy">
                  <span class="function-name">{{ func.name }}</span>
                </span>
              </span>
              <ArrowRight class="inline-icon function-arrow" />
            </button>
          </div>
        </div>
      </div>

      <div v-if="userManagementDialogVisible" class="login-mask" @click.self="userManagementDialogVisible = false">
        <div class="service-dialog user-management-dialog">
          <div class="login-title">用户管理</div>
          <div class="user-admin-toolbar">
            <button class="dialog-confirm" @click="openCreateUserDialog">新增用户</button>
            <button class="dialog-cancel" @click="loadUsers">刷新</button>
          </div>
          <div v-if="userManagementLoading" class="empty-log">加载中...</div>
          <div v-else class="user-list">
            <div v-for="item in managedUsers" :key="item.id" class="user-card">
              <div class="user-card-head">
                <div>
                  <div class="user-card-name">{{ item.username }}</div>
                  <div class="user-card-meta">{{ item.role_display || item.role }} · {{ item.is_active ? '启用' : '禁用' }}</div>
                </div>
                <div class="user-card-actions">
                  <button class="layer-action-btn" title="编辑用户" @click="openEditUserDialog(item)">
                    <Setting class="button-icon" />
                  </button>
                  <button class="layer-action-btn" title="权限分配" @click="openPermissionDialog(item)">
                    <Files class="button-icon" />
                  </button>
                  <button class="layer-action-btn danger" title="删除用户" @click="handleDeleteUser(item)">
                    <Delete class="button-icon" />
                  </button>
                </div>
              </div>
              <div class="user-card-grid">
                <div>姓名：{{ [item.first_name, item.last_name].filter(Boolean).join(' ') || '未填写' }}</div>
                <div>邮箱：{{ item.email || '未填写' }}</div>
                <div>机构：{{ item.organization || '未填写' }}</div>
                <div>电话：{{ item.phone || '未填写' }}</div>
              </div>
            </div>
          </div>
          <div class="login-actions">
            <button class="dialog-confirm" @click="userManagementDialogVisible = false">关闭</button>
          </div>
        </div>
      </div>

      <div v-if="userEditDialogVisible" class="login-mask" @click.self="userEditDialogVisible = false">
        <div class="service-dialog">
          <div class="login-title">{{ userEditTitle }}</div>
          <div v-if="userFormError" class="form-error-banner">{{ userFormError }}</div>
          <label class="login-field">
            <span>用户名</span>
            <input v-model="userForm.username" type="text" autocomplete="off" />
          </label>
          <label class="login-field">
            <span>邮箱</span>
            <input v-model="userForm.email" type="email" autocomplete="off" />
          </label>
          <label class="login-field">
            <span>姓名</span>
            <input v-model="userForm.first_name" type="text" autocomplete="off" />
          </label>
          <label v-if="userEditMode !== 'register'" class="login-field">
            <span>角色</span>
            <select v-model="userForm.role">
              <option value="admin">管理员</option>
              <option value="user">普通用户</option>
              <option value="expert">专家</option>
            </select>
          </label>
          <label class="login-field">
            <span>手机号</span>
            <input v-model="userForm.phone" type="text" autocomplete="off" />
          </label>
          <label class="login-field">
            <span>所属机构</span>
            <input v-model="userForm.organization" type="text" autocomplete="off" />
          </label>
          <label class="login-field">
            <span>部门</span>
            <input v-model="userForm.department" type="text" autocomplete="off" />
          </label>
          <label class="login-field">
            <span>职位</span>
            <input v-model="userForm.position" type="text" autocomplete="off" />
          </label>
          <label v-if="userEditMode !== 'register'" class="login-field">
            <span>状态</span>
            <select v-model="userForm.is_active">
              <option :value="true">启用</option>
              <option :value="false">禁用</option>
            </select>
          </label>
          <label class="login-field">
            <span>{{ userEditMode === 'edit' ? '新密码（可留空）' : '密码' }}</span>
            <input v-model="userForm.password" type="password" autocomplete="new-password" />
          </label>
          <label v-if="userEditMode !== 'edit'" class="login-field">
            <span>确认密码</span>
            <input v-model="userForm.password_confirm" type="password" autocomplete="new-password" />
          </label>
          <div class="login-actions">
            <button class="dialog-cancel" @click="userEditDialogVisible = false">取消</button>
            <button class="dialog-confirm" :disabled="userSubmitting" @click="submitUserForm">
              {{ userSubmitting ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="permissionDialogVisible" class="login-mask" @click.self="permissionDialogVisible = false">
        <div class="service-dialog permission-dialog">
          <div class="login-title">权限分配</div>
          <div class="permission-subtitle">{{ activeManagedUser?.username }}</div>
          <div class="permission-groups">
            <div v-for="(permissionItems, moduleName) in permissionSchema" :key="moduleName" class="permission-group">
              <div class="permission-group-title">{{ permissionModuleLabels[moduleName] || moduleName }}</div>
              <div class="permission-options">
                <label v-for="permissionName in permissionItems" :key="`${moduleName}-${permissionName}`" class="permission-option">
                  <input
                    type="checkbox"
                    :checked="hasPermission(moduleName, permissionName)"
                    @change="togglePermission(moduleName, permissionName, $event.target.checked)"
                  />
                  <span>{{ permissionLabels[permissionName] || permissionName }}</span>
                </label>
              </div>
            </div>
          </div>
          <div class="login-actions">
            <button class="dialog-cancel" @click="permissionDialogVisible = false">取消</button>
            <button class="dialog-confirm" :disabled="permissionSubmitting" @click="savePermissions">
              {{ permissionSubmitting ? '保存中...' : '保存权限' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="dataGovernanceDialogVisible" class="login-mask" @click.self="dataGovernanceDialogVisible = false">
        <div class="service-dialog governance-dialog">
          <div class="login-title">数据与备份</div>
          <div class="governance-account">
            当前账号：{{ currentUser?.username }}（{{ currentUser?.role_display || currentUser?.role || '用户' }}）
          </div>
          <div class="governance-grid">
            <div class="governance-policy-card">
              <div class="governance-policy-title">系统数据备份</div>
              <div>管理员定期备份系统数据，备份频率为每日一次。</div>
              <div>备份数据保存期限为 3 年，备份介质需离线存储，确保数据安全。</div>
            </div>
            <div class="governance-policy-card">
              <div class="governance-policy-title">临时数据保留</div>
              <div>操作人员上传的临时数据，系统保留期限为 90 天，超过期限自动删除。</div>
              <div>重要数据需自行备份至本地指定目录。</div>
            </div>
          </div>
          <div class="governance-history-head">
            <span>我的结果缓存历史</span>
            <button type="button" class="mini-text-btn" @click="refreshAccountResultHistory">刷新</button>
          </div>
          <div v-if="accountResultHistory.length === 0" class="empty-log">当前账号暂无本机结果缓存</div>
          <div v-else class="governance-history-list">
            <div v-for="item in accountResultHistory" :key="item.id" class="governance-history-item">
              <div class="governance-history-main">
                <span class="layer-pill">{{ item.feature }}</span>
                <strong>{{ item.title }}</strong>
                <small>{{ item.subtitle }}</small>
              </div>
              <div class="governance-history-meta">
                <span>{{ item.timeText }}</span>
                <span>{{ item.ownerText }}</span>
                <span>{{ item.retentionText }}</span>
              </div>
            </div>
          </div>
          <div class="login-actions">
            <button class="dialog-confirm" @click="dataGovernanceDialogVisible = false">关闭</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 主地图区域 -->
    <div class="main-content">
      <div class="map-stage">
        <MapContainer ref="mapContainerRef" />
      </div>
    </div>

    <div v-if="businessServiceDialogVisible" class="login-mask" @click.self="businessServiceDialogVisible = false">
      <div class="service-dialog">
        <div class="login-title">接入标准服务图层</div>
        <label class="login-field">
          <span>图层名称</span>
          <input v-model="businessServiceForm.name" type="text" autocomplete="off" />
        </label>
        <label class="login-field">
          <span>服务类型</span>
          <select v-model="businessServiceForm.source_format" @change="syncBusinessServiceLayerType">
            <option value="wms">WMS</option>
            <option value="wfs">WFS</option>
            <option value="wcs">WCS</option>
          </select>
        </label>
        <label class="login-field">
          <span>图层类型</span>
          <select v-model="businessServiceForm.layer_type" :disabled="businessServiceForm.source_format !== 'wms'">
            <option value="vector">矢量</option>
            <option value="raster">栅格</option>
          </select>
        </label>
        <label class="login-field">
          <span>服务地址</span>
          <textarea v-model="businessServiceForm.service_url" rows="4" placeholder="请输入标准服务请求地址"></textarea>
        </label>
        <label class="login-field">
          <span>图层名称参数</span>
          <input v-model="businessServiceForm.service_type_name" type="text" autocomplete="off" placeholder="WMS 的 layers 或 WFS 的 typeName" />
        </label>
        <label class="login-field">
          <span>坐标系</span>
          <input v-model="businessServiceForm.service_srs" type="text" autocomplete="off" placeholder="例如 EPSG:4326 / EPSG:3857" />
        </label>
        <label class="login-field">
          <span>样式名称</span>
          <input v-model="businessServiceForm.style_name" type="text" autocomplete="off" placeholder="可选，用于记录样式或SLD名称" />
        </label>
        <label class="login-field">
          <span>说明</span>
          <textarea v-model="businessServiceForm.description" rows="3" placeholder="可选"></textarea>
        </label>
        <div class="login-actions">
          <button class="dialog-cancel" @click="businessServiceDialogVisible = false">取消</button>
          <button class="dialog-confirm" :disabled="businessServiceSubmitting" @click="handleBusinessServiceCreate">
            {{ businessServiceSubmitting ? '接入中...' : '保存并接入' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="businessLayerStyleDialogVisible" class="login-mask" @click.self="businessLayerStyleDialogVisible = false">
      <div class="service-dialog">
        <div class="login-title">业务图层样式配置</div>
        <label class="login-field">
          <span>样式名称</span>
          <input v-model="businessLayerStyleForm.style_name" type="text" autocomplete="off" />
        </label>
        <template v-if="businessLayerStyleForm.layer_type === 'vector'">
          <label class="login-field">
            <span>填充颜色</span>
            <div class="color-field">
              <input v-model="businessLayerStyleForm.fill_color" class="color-input" type="color" />
              <input v-model="businessLayerStyleForm.fill_color" type="text" placeholder="#1f8f4d" autocomplete="off" />
            </div>
          </label>
          <label class="login-field">
            <span>边线颜色</span>
            <div class="color-field">
              <input v-model="businessLayerStyleForm.stroke_color" class="color-input" type="color" />
              <input v-model="businessLayerStyleForm.stroke_color" type="text" placeholder="#1f8f4d" autocomplete="off" />
            </div>
          </label>
          <label class="login-field">
            <span>边线宽度</span>
            <input v-model="businessLayerStyleForm.stroke_width" type="number" min="0" step="0.5" />
          </label>
          <label class="login-field">
            <span>填充透明度</span>
            <input v-model="businessLayerStyleForm.fill_opacity" type="number" min="0" max="1" step="0.05" />
          </label>
          <label class="login-field">
            <span>分类字段</span>
            <input v-model="businessLayerStyleForm.classification_field" type="text" autocomplete="off" />
          </label>
          <label class="login-field">
            <span>分类配色</span>
            <select v-model="businessLayerStyleForm.color_scheme">
              <option value="green_yellow_red">绿黄红</option>
              <option value="blue_cyan_green">蓝青绿</option>
              <option value="purple_pink_red">紫粉红</option>
            </select>
          </label>
        </template>
        <template v-else>
          <label class="login-field">
            <span>色带方案</span>
            <select v-model="businessLayerStyleForm.raster_color_ramp">
              <option value="green_yellow_red">绿黄红</option>
              <option value="blue_cyan_green">蓝青绿</option>
              <option value="gray_blue">灰蓝</option>
            </select>
          </label>
          <label class="login-field">
            <span>栅格透明度</span>
            <input v-model="businessLayerStyleForm.raster_opacity" type="number" min="0" max="1" step="0.05" />
          </label>
          <label class="login-field">
            <span>NoData</span>
            <input v-model="businessLayerStyleForm.nodata" type="number" step="0.01" />
          </label>
        </template>
        <label class="login-field">
          <span>自定义 SLD</span>
          <textarea v-model="businessLayerStyleForm.sld_content" rows="6" placeholder="可选，填写后优先使用自定义SLD"></textarea>
        </label>
        <div class="login-actions">
          <button class="dialog-cancel" @click="businessLayerStyleDialogVisible = false">取消</button>
          <button class="dialog-confirm" :disabled="businessLayerStyleSubmitting" @click="handleBusinessLayerStyleSave">
            {{ businessLayerStyleSubmitting ? '保存中...' : '保存并应用' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="businessLayerLogsDialogVisible" class="login-mask" @click.self="businessLayerLogsDialogVisible = false">
      <div class="service-dialog">
        <div class="login-title">业务图层操作日志</div>
        <div class="log-list" v-if="businessLayerLogs.length">
          <div class="log-item" v-for="log in businessLayerLogs" :key="log.id">
            <div class="log-head">
              <span class="layer-pill">{{ log.action_display }}</span>
              <span :class="['layer-pill', 'health-pill', `health-${log.status === 'success' ? 'healthy' : log.status === 'failed' ? 'unhealthy' : 'unknown'}`]">
                {{ log.status_display }}
              </span>
              <button
                v-if="logHasDetails(log)"
                type="button"
                class="log-toggle-btn"
                @click="toggleBusinessLayerLogDetails(log.id)"
              >
                {{ businessLayerExpandedLogIds.has(log.id) ? '收起详情' : '查看详情' }}
              </button>
            </div>
            <div class="log-line">{{ log.message || '无说明' }}</div>
            <div class="log-line muted">{{ log.operator_name || '系统' }} · {{ formatDateTime(log.created_at) }}</div>
            <pre v-if="businessLayerExpandedLogIds.has(log.id)" class="log-details">{{ formatLogDetails(log.details) }}</pre>
          </div>
        </div>
        <div v-else class="empty-log">暂无操作日志</div>
        <div class="login-actions">
          <button class="dialog-confirm" @click="businessLayerLogsDialogVisible = false">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowRight,
  Camera,
  Close,
  Connection,
  DataAnalysis,
  Delete,
  Files,
  Guide,
  Histogram,
  MapLocation,
  Message,
  Refresh,
  Search,
  Setting,
  TrendCharts,
  Upload,
  User
} from '@element-plus/icons-vue'
import MapContainer from '../components/Map/MapContainer.vue'
import { useMapStore } from '../store/map'
import { useRoute, useRouter } from 'vue-router'
import { authService, spatialService } from '../services/api.js'
import { ensureCsrfCookie } from '../utils/http.js'
import { canViewHistoryItem, getCurrentUserContext, setCurrentUserContext } from '../utils/userContext.js'
import { loadMainMapAnalysisLayers } from '../utils/mainMapAnalysisLayers.js'

const router = useRouter()
const route = useRoute()
const mapStore = useMapStore()
const { toggleLayerVisibility } = mapStore

const fileInput = ref(null)
const businessLayerInput = ref(null)
const mapContainerRef = ref(null)
const loginUsernameInput = ref(null)
const coordinateInput = ref('')
const currentUser = ref(null)
const loginDialogVisible = ref(false)
const loginLoading = ref(false)
const userManagementDialogVisible = ref(false)
const userManagementLoading = ref(false)
const dataGovernanceDialogVisible = ref(false)
const userEditDialogVisible = ref(false)
const userEditMode = ref('create')
const userSubmitting = ref(false)
const userFormError = ref('')
const permissionDialogVisible = ref(false)
const permissionSubmitting = ref(false)
const activeManagedUser = ref(null)
const managedUsers = ref([])
const permissionSchema = ref({})
const permissionDraft = reactive({})
const analysisResultLayers = ref([])
let analysisLayerReloading = false
let analysisLayerReloadQueued = false
const accountResultHistory = ref([])
const businessLayerUploading = ref(false)
const businessLayerActionIds = ref(new Set())
const businessServiceDialogVisible = ref(false)
const businessServiceSubmitting = ref(false)
const businessLayerStyleDialogVisible = ref(false)
const businessLayerStyleSubmitting = ref(false)
const businessLayerLogsDialogVisible = ref(false)
const businessLayerLogs = ref([])
const businessLayerExpandedLogIds = ref(new Set())
const activeBusinessLayer = ref(null)
const loginForm = reactive({
  username: '',
  password: ''
})
const userForm = reactive({
  id: null,
  username: '',
  email: '',
  first_name: '',
  last_name: '',
  role: 'user',
  phone: '',
  organization: '',
  department: '',
  position: '',
  is_active: true,
  password: '',
  password_confirm: ''
})
const businessServiceForm = reactive({
  name: '',
  description: '',
  layer_type: 'vector',
  source_format: 'wms',
  service_url: '',
  service_type_name: '',
  service_srs: '',
  style_name: ''
})
const businessLayerStyleForm = reactive({
  layer_type: 'vector',
  style_name: '',
  fill_color: '#1f8f4d',
  stroke_color: '#1f8f4d',
  stroke_width: 2,
  fill_opacity: 0.18,
  classification_field: '',
  color_scheme: 'green_yellow_red',
  raster_color_ramp: 'green_yellow_red',
  raster_opacity: 0.72,
  nodata: '',
  sld_content: ''
})

// 折叠状态控制
const layerManagementExpanded = ref(true)
const businessLayersExpanded = ref(true)
const tempLayersExpanded = ref(true)
const toolboxExpanded = ref(true)
const businessFunctionsExpanded = ref(true)
const canManageUsers = computed(() => Boolean(currentUser.value?.is_admin || currentUser.value?.role === 'admin'))
const userEditTitle = computed(() => {
  if (userEditMode.value === 'register') return '注册账号'
  return userEditMode.value === 'create' ? '新增用户' : '编辑用户'
})
const permissionModuleLabels = {
  remote_sensing: '遥感生态指数分析',
  ecological_index: '生态环境指数计算',
  overlay_analysis: '重大工程叠加分析',
  climate_monitoring: '气候环境监测统计',
  feedback: '民众意见反馈',
  business_layers: '业务图层管理',
  user_management: '用户管理'
}
const permissionLabels = {
  view: '查看',
  use: '使用',
  manage: '管理'
}

const hasUserPermission = (moduleName, permissionName = 'view') => {
  if (!currentUser.value) return false
  return true
}

const canAccessBusinessFunction = (func) => {
  if (!func?.module) return true
  return hasUserPermission(func.module, func.permission || 'view')
}

// 业务图层数据
const businessLayers = reactive([
  {
    id: 'watershed-boundary',
    name: '藉河流域范围',
    type: 'vector',
    icon: Guide,
    visible: false
  },
  {
    id: 'watershed-points',
    name: '藉河流域点数据',
    type: 'vector',
    icon: MapLocation,
    visible: false
  },
  {
    id: 'townships',
    name: '乡镇行政区划',
    type: 'vector',
    icon: Files,
    visible: false
  }
])

// 业务功能
const businessFunctions = reactive([
  {
    id: 1,
    name: '遥感生态指数分析',
    icon: DataAnalysis,
    module: 'remote_sensing',
    permission: 'view',
    status: 'available'
  },
  {
    id: 2,
    name: '生态环境指数计算',
    icon: Histogram,
    module: 'ecological_index',
    permission: 'view',
    status: 'available'
  },
  {
    id: 3,
    name: '重大工程叠加分析',
    icon: Connection,
    module: 'overlay_analysis',
    permission: 'view',
    status: 'planned'
  },
  {
    id: 4,
    name: '气候环境监测统计',
    icon: TrendCharts,
    module: 'climate_monitoring',
    permission: 'view',
    status: 'available',
    route: '/climate-monitoring'
  },
  {
    id: 5,
    name: '民众意见反馈',
    icon: Message,
    module: 'feedback',
    permission: 'view',
    status: 'available',
    route: '/feedback'
  }
])

businessFunctions[0].route = '/remote-sensing-analysis'
businessFunctions[1].route = '/ecological-index'
businessFunctions[2].status = 'available'
businessFunctions[2].route = '/overlay-analysis'

onMounted(() => {
  ensureCsrfCookie().catch((error) => {
    console.warn('初始化 CSRF Cookie 失败，首次写操作可能需要重试:', error)
  })
  loadCurrentUser()
  loadBusinessLayers()
  window.addEventListener('tianshui-main-map-analysis-layers-updated', syncAnalysisResultLayers)
})

onUnmounted(() => {
  window.removeEventListener('tianshui-main-map-analysis-layers-updated', syncAnalysisResultLayers)
})

const loadCurrentUser = async () => {
  if (!getCurrentUserContext()) {
    currentUser.value = null
    analysisResultLayers.value = []
    accountResultHistory.value = []
    return
  }
  try {
    currentUser.value = await authService.getProfile({ silentError: true })
    setCurrentUserContext(currentUser.value)
    refreshAccountResultHistory()
    loadAnalysisResultLayers()
  } catch {
    currentUser.value = null
    setCurrentUserContext(null)
    analysisResultLayers.value = []
    mapContainerRef.value?.removeAnalysisResultLayers?.({ removePersisted: false })
  }
}

const openLoginDialog = async () => {
  try {
    await ensureCsrfCookie()
  } catch (error) {
    console.warn('打开登录框前获取 CSRF Cookie 失败:', error)
  }
  loginForm.username = ''
  loginForm.password = ''
  loginDialogVisible.value = true
  await nextTick()
  loginUsernameInput.value?.focus()
}

const openRegisterDialog = async () => {
  loginDialogVisible.value = false
  try {
    await ensureCsrfCookie()
  } catch (error) {
    console.warn('打开注册框前获取 CSRF Cookie 失败:', error)
  }
  resetUserForm()
  userEditMode.value = 'register'
  userEditDialogVisible.value = true
}

const resetUserForm = () => {
  userFormError.value = ''
  userForm.id = null
  userForm.username = ''
  userForm.email = ''
  userForm.first_name = ''
  userForm.last_name = ''
  userForm.role = 'user'
  userForm.phone = ''
  userForm.organization = ''
  userForm.department = ''
  userForm.position = ''
  userForm.is_active = true
  userForm.password = ''
  userForm.password_confirm = ''
}

const handleLogin = async () => {
  if (!loginForm.username || !loginForm.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loginLoading.value = true
  try {
    await ensureCsrfCookie()
    const result = await authService.login({
      username: loginForm.username,
      password: loginForm.password
    })
    currentUser.value = result.user
    setCurrentUserContext(result.user)
    refreshAccountResultHistory()
    loadAnalysisResultLayers()
    loginDialogVisible.value = false
    ElMessage.success('登录成功')
  } catch (error) {
    console.error(error)
  } finally {
    loginLoading.value = false
  }
}

const handleLogout = async () => {
  try {
    await authService.logout()
  } catch (error) {
    console.warn('后端登出请求未完成，已在前端清除登录状态:', error)
  } finally {
    currentUser.value = null
    setCurrentUserContext(null)
    analysisResultLayers.value = []
    mapContainerRef.value?.removeAnalysisResultLayers?.({ removePersisted: false })
    accountResultHistory.value = []
    managedUsers.value = []
    userManagementDialogVisible.value = false
    ElMessage.success('已退出登录')
  }
}

const loadUsers = async () => {
  if (!canManageUsers.value) return
  userManagementLoading.value = true
  try {
    const result = await authService.getUsers({}, { silentError: true })
    managedUsers.value = Array.isArray(result) ? result : (result.results || [])
  } finally {
    userManagementLoading.value = false
  }
}

const ensurePermissionSchema = async () => {
  if (!canManageUsers.value || Object.keys(permissionSchema.value).length > 0) return
  const result = await authService.getPermissionSchema({ silentError: true })
  permissionSchema.value = result.modules || {}
}

const openUserManagementDialog = async () => {
  if (!canManageUsers.value) {
    ElMessage.warning('仅管理员可管理用户')
    return
  }
  userManagementDialogVisible.value = true
  await Promise.all([loadUsers(), ensurePermissionSchema()])
}

const openCreateUserDialog = () => {
  resetUserForm()
  userEditMode.value = 'create'
  userEditDialogVisible.value = true
}

const openEditUserDialog = (user) => {
  resetUserForm()
  userEditMode.value = 'edit'
  userForm.id = user.id
  userForm.username = user.username || ''
  userForm.email = user.email || ''
  userForm.first_name = user.first_name || ''
  userForm.last_name = user.last_name || ''
  userForm.role = user.role || 'user'
  userForm.phone = user.phone || ''
  userForm.organization = user.organization || ''
  userForm.department = user.department || ''
  userForm.position = user.position || ''
  userForm.is_active = user.is_active !== false
  userEditDialogVisible.value = true
}

const submitUserForm = async () => {
  userFormError.value = ''
  if (!userForm.username.trim()) {
    userFormError.value = '请填写用户名'
    ElMessage.warning(userFormError.value)
    return
  }
  if (userEditMode.value !== 'edit' && !userForm.password) {
    userFormError.value = '请填写初始密码'
    ElMessage.warning(userFormError.value)
    return
  }
  if (userEditMode.value !== 'edit' && userForm.password.length < 8) {
    userFormError.value = '密码至少需要 8 位'
    ElMessage.warning(userFormError.value)
    return
  }
  if (userEditMode.value !== 'edit' && userForm.password !== userForm.password_confirm) {
    userFormError.value = '两次密码输入不一致'
    ElMessage.warning(userFormError.value)
    return
  }
  if (userEditMode.value === 'edit' && userForm.password && userForm.password.length < 8) {
    userFormError.value = '新密码至少需要 8 位'
    ElMessage.warning(userFormError.value)
    return
  }

  userSubmitting.value = true
  try {
    if (userEditMode.value !== 'edit') {
      const payload = {
        username: userForm.username.trim(),
        email: userForm.email.trim(),
        first_name: userForm.first_name.trim(),
        last_name: userForm.last_name.trim(),
        role: userEditMode.value === 'register' ? 'user' : userForm.role,
        phone: userForm.phone.trim(),
        organization: userForm.organization.trim(),
        department: userForm.department.trim(),
        position: userForm.position.trim(),
        is_active: userForm.is_active,
        password: userForm.password,
        password_confirm: userForm.password_confirm
      }
      if (userEditMode.value === 'register') {
        await authService.register(payload, { skipAuth: true, silentError: true })
        ElMessage.success('注册成功，请登录')
        loginForm.username = userForm.username.trim()
        loginForm.password = ''
        loginDialogVisible.value = true
      } else {
        await authService.createUser(payload, { silentError: true })
        ElMessage.success('用户创建成功')
      }
    } else {
      const payload = {
        username: userForm.username.trim(),
        email: userForm.email.trim(),
        first_name: userForm.first_name.trim(),
        last_name: userForm.last_name.trim(),
        role: userForm.role,
        phone: userForm.phone.trim(),
        organization: userForm.organization.trim(),
        department: userForm.department.trim(),
        position: userForm.position.trim(),
        is_active: userForm.is_active
      }
      if (userForm.password) {
        payload.password = userForm.password
      }
      await authService.updateUser(userForm.id, payload, { silentError: true })
      ElMessage.success('用户更新成功')
    }
    userEditDialogVisible.value = false
    if (canManageUsers.value) {
      await loadUsers()
    }
  } catch (error) {
    console.error(error)
    userFormError.value = getRequestErrorMessage(error, userEditMode.value === 'register' ? '注册失败' : '用户保存失败')
    ElMessage.error(userFormError.value)
  } finally {
    userSubmitting.value = false
  }
}

const handleDeleteUser = async (user) => {
  if (String(user.id) === String(currentUser.value?.id)) {
    ElMessage.warning('不能删除当前登录管理员')
    return
  }
  try {
    await ElMessageBox.confirm(`确定删除用户 ${user.username} 吗？`, '删除用户', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      customClass: 'user-delete-confirm-box',
      modalClass: 'user-delete-confirm-mask',
      distinguishCancelAndClose: true
    })
  } catch {
    return
  }

  try {
    await authService.deleteUser(user.id, { silentError: true })
    ElMessage.success('用户删除成功')
    if (String(activeManagedUser.value?.id) === String(user.id)) {
      activeManagedUser.value = null
      permissionDialogVisible.value = false
    }
    await loadUsers()
  } catch (error) {
    console.error(error)
    ElMessage.error(getRequestErrorMessage(error, '用户删除失败'))
  }
}

const clearPermissionDraft = () => {
  Object.keys(permissionDraft).forEach(key => {
    delete permissionDraft[key]
  })
}

const openPermissionDialog = async (user) => {
  activeManagedUser.value = user
  clearPermissionDraft()
  await ensurePermissionSchema()
  const response = await authService.getUserPermissions(user.id, { silentError: true })
  const permissionList = Array.isArray(response.permissions) ? response.permissions : []
  permissionList.forEach(item => {
    if (!permissionDraft[item.module]) {
      permissionDraft[item.module] = []
    }
    permissionDraft[item.module].push(item.permission)
  })
  permissionDialogVisible.value = true
}

const hasPermission = (moduleName, permissionName) => {
  return Array.isArray(permissionDraft[moduleName]) && permissionDraft[moduleName].includes(permissionName)
}

const togglePermission = (moduleName, permissionName, checked) => {
  const current = new Set(permissionDraft[moduleName] || [])
  if (checked) {
    current.add(permissionName)
  } else {
    current.delete(permissionName)
  }
  permissionDraft[moduleName] = Array.from(current)
}

const savePermissions = async () => {
  if (!activeManagedUser.value) return
  permissionSubmitting.value = true
  try {
    const payload = {}
    Object.keys(permissionSchema.value).forEach(moduleName => {
      payload[moduleName] = Array.isArray(permissionDraft[moduleName]) ? permissionDraft[moduleName] : []
    })
    await authService.assignUserPermissions(activeManagedUser.value.id, payload)
    ElMessage.success('权限保存成功')
    permissionDialogVisible.value = false
    await loadUsers()
  } catch (error) {
    console.error(error)
  } finally {
    permissionSubmitting.value = false
  }
}

// 跳转到遥感生态指数分析
const handleBusinessFunctionClick = async (func) => {
  if (!canAccessBusinessFunction(func)) {
    ElMessage.warning('当前账号没有访问该模块的权限，请联系管理员分配权限')
    return
  }
  if (func.route) {
    router.push(func.route)
    return
  }
  ElMessage.info(`${func.name} 暂未接入后端接口，当前仅作为业务入口占位`)
}

// 触发文件上传
const requireLayerLogin = () => {
  if (currentUser.value) return true
  ElMessage.warning('请先登录后再进行图层操作')
  openLoginDialog()
  return false
}

const triggerFileUpload = () => {
  if (!requireLayerLogin()) return
  fileInput.value?.click()
}

const triggerBusinessLayerUpload = () => {
  if (!requireLayerLogin()) return
  businessLayerInput.value?.click()
}

const syncBusinessServiceLayerType = () => {
  if (businessServiceForm.source_format === 'wfs') {
    businessServiceForm.layer_type = 'vector'
  } else if (businessServiceForm.source_format === 'wcs') {
    businessServiceForm.layer_type = 'raster'
  }
}

const openBusinessServiceDialog = () => {
  if (!requireLayerLogin()) return
  businessServiceForm.name = ''
  businessServiceForm.description = ''
  businessServiceForm.layer_type = 'vector'
  businessServiceForm.source_format = 'wms'
  businessServiceForm.service_url = ''
  businessServiceForm.service_type_name = ''
  businessServiceForm.service_srs = ''
  businessServiceForm.style_name = ''
  businessServiceDialogVisible.value = true
}

const layerIconByType = (layerType) => {
  if (layerType === 'raster') return Histogram
  return MapLocation
}

const formatDateTime = (value) => {
  if (!value) return '未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未记录'
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const sourceOriginLabel = (record) => {
  if (record.metadata?.is_external_service) return '外部标准服务'
  if (record.source_format === 'kml') return 'KML 上传转换发布'
  if (record.source_format === 'shapefile') return 'Shapefile ZIP 上传发布'
  if (record.source_format === 'geotiff') return 'GeoTIFF 上传发布'
  return '业务图层服务'
}

const primaryBusinessServiceUrl = (record) => record.wms_url || record.wfs_url || record.wcs_url || record.service_url || ''

const healthStatusText = (status) => {
  if (status === 'healthy') return '服务正常'
  if (status === 'unhealthy') return '服务异常'
  return '待检测'
}

const isPlaceholderServiceMessage = (record) => {
  const message = String(record?.service_health_message || '')
  const serviceUrl = String(record?.service_url || record?.wms_url || record?.wfs_url || record?.wcs_url || '')
  return (
    message.includes('示例地址未配置真实服务') ||
    serviceUrl.includes('example.com') ||
    serviceUrl.includes('example.org') ||
    serviceUrl.includes('example.net')
  )
}

const upsertBusinessLayer = (record) => {
  const id = String(record.id)
  const existing = businessLayers.find(item => item.id === id)
  const isPlaceholder = isPlaceholderServiceMessage(record)
  const healthStatus = isPlaceholder ? 'unknown' : (record.service_health_status || 'unknown')
  const next = {
    id,
    name: record.name,
    type: record.layer_type,
    icon: layerIconByType(record.layer_type),
    visible: existing?.visible || false,
    source: 'service',
    serviceLayer: record,
    status: record.status,
    statusText: record.status_display || record.status,
    description: record.description,
    typeLabel: record.layer_type_display || record.layer_type,
    sourceFormatLabel: record.source_format_display || record.source_format,
    originLabel: sourceOriginLabel(record),
    primaryServiceUrl: primaryBusinessServiceUrl(record),
    createdAtText: formatDateTime(record.created_at),
    healthStatus,
    healthText: isPlaceholder ? '待检测' : healthStatusText(healthStatus),
    healthMessage: isPlaceholder ? '示例地址未配置真实服务，暂不执行连通性检测' : (record.service_health_message || '')
  }
  if (existing) {
    Object.assign(existing, next)
  } else {
    businessLayers.unshift(next)
  }
}

const setBusinessLayerBusy = (layer, busy) => {
  const next = new Set(businessLayerActionIds.value)
  if (busy) {
    next.add(layer.id)
  } else {
    next.delete(layer.id)
  }
  businessLayerActionIds.value = next
}

const isBusinessLayerBusy = (layer) => businessLayerActionIds.value.has(layer.id)

const openBusinessLayerStyleDialog = (layer) => {
  if (!requireLayerLogin()) return
  const config = layer?.serviceLayer?.style_config || {}
  activeBusinessLayer.value = layer
  businessLayerStyleForm.layer_type = layer?.serviceLayer?.layer_type || 'vector'
  businessLayerStyleForm.style_name = layer?.serviceLayer?.style_name || ''
  businessLayerStyleForm.fill_color = config.fill_color || '#1f8f4d'
  businessLayerStyleForm.stroke_color = config.stroke_color || '#1f8f4d'
  businessLayerStyleForm.stroke_width = config.stroke_width ?? 2
  businessLayerStyleForm.fill_opacity = config.fill_opacity ?? 0.18
  businessLayerStyleForm.classification_field = config.classification_field || ''
  businessLayerStyleForm.color_scheme = config.color_scheme || 'green_yellow_red'
  businessLayerStyleForm.raster_color_ramp = config.raster_color_ramp || 'green_yellow_red'
  businessLayerStyleForm.raster_opacity = config.raster_opacity ?? 0.72
  businessLayerStyleForm.nodata = config.nodata ?? ''
  businessLayerStyleForm.sld_content = layer?.serviceLayer?.sld_content || ''
  businessLayerStyleDialogVisible.value = true
}

const openBusinessLayerLogsDialog = async (layer) => {
  if (!requireLayerLogin()) return
  activeBusinessLayer.value = layer
  businessLayerLogs.value = []
  businessLayerExpandedLogIds.value = new Set()
  businessLayerLogsDialogVisible.value = true
  try {
    const result = await spatialService.getBusinessLayerLogs(layer.serviceLayer.id)
    businessLayerLogs.value = Array.isArray(result) ? result : []
  } catch (error) {
    console.error(error)
    ElMessage.error('业务图层日志加载失败')
  }
}

const logHasDetails = (log) => log?.details && Object.keys(log.details).length > 0

const toggleBusinessLayerLogDetails = (logId) => {
  const next = new Set(businessLayerExpandedLogIds.value)
  if (next.has(logId)) {
    next.delete(logId)
  } else {
    next.add(logId)
  }
  businessLayerExpandedLogIds.value = next
}

const formatLogDetails = (details) => {
  try {
    return JSON.stringify(details || {}, null, 2)
  } catch {
    return '日志详情解析失败'
  }
}

const getRequestErrorMessage = (error, fallback) => {
  const data = error?.response?.data
  const flattenDetails = (value) => {
    if (!value) return ''
    if (typeof value === 'string') return value
    if (Array.isArray(value)) return value.map(flattenDetails).filter(Boolean).join('；')
    if (typeof value === 'object') {
      return Object.entries(value)
        .map(([key, item]) => {
          const message = flattenDetails(item)
          return message ? `${key}: ${message}` : ''
        })
        .filter(Boolean)
        .join('；')
    }
    return String(value)
  }
  const detailMessage = flattenDetails(data?.details)
  if (data?.error && detailMessage) {
    return `${data.error}：${detailMessage}`
  }
  return (
    data?.error ||
    detailMessage ||
    data?.detail ||
    data?.message ||
    data?.non_field_errors?.[0] ||
    (typeof data === 'string' ? data : '') ||
    fallback
  )
}

const loadBusinessLayers = async () => {
  try {
    const result = await spatialService.getBusinessLayers()
    const records = Array.isArray(result) ? result : (result.results || [])
    const recordIds = new Set(records.map(record => String(record.id)))
    for (let index = businessLayers.length - 1; index >= 0; index -= 1) {
      const item = businessLayers[index]
      if (item.source === 'service' && !recordIds.has(String(item.id))) {
        businessLayers.splice(index, 1)
      }
    }
    records.forEach(upsertBusinessLayer)
    await nextTick()
    mapContainerRef.value?.pruneBusinessServiceLayers(records)
  } catch (error) {
    console.warn('业务图层列表加载失败:', error)
  }
}

const safeJsonParse = (rawValue, fallback) => {
  if (!rawValue) return fallback
  try {
    return JSON.parse(rawValue)
  } catch (error) {
    console.warn('解析本地结果缓存失败:', error)
    return fallback
  }
}

const formatAnalysisLayerTime = (timestamp) => {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const formatFullDateTime = (timestamp) => {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const getRetentionText = (timestamp) => {
  const createdAt = Number(timestamp || 0)
  if (!createdAt) return '临时数据保留 90 天'
  const elapsedDays = Math.floor((Date.now() - createdAt) / (24 * 60 * 60 * 1000))
  const remainingDays = Math.max(0, 90 - elapsedDays)
  return `临时数据剩余约 ${remainingDays} 天`
}

const getOwnerText = (item) => {
  const owner = item?.owner || item?.payload?.owner || item?.resultData?.owner
  if (owner?.username) return `账号：${owner.username}`
  return '历史本机缓存'
}

const normalizeAccountHistoryItem = (item) => ({
  ...item,
  timeText: formatFullDateTime(item.timestamp) || '时间未知',
  ownerText: getOwnerText(item),
  retentionText: getRetentionText(item.timestamp)
})

const getRemoteAccountHistory = () => {
  const storageKeys = safeJsonParse(localStorage.getItem('analysis_cache_index'), [])
  if (!Array.isArray(storageKeys)) return []

  return storageKeys
    .map((storageKey) => safeJsonParse(localStorage.getItem(storageKey), null))
    .filter(item => item?.resultData && canViewHistoryItem(item, currentUser.value, {
      adminCanViewAll: true,
      adminCanViewOwnerless: true
    }))
    .map((item) => {
      const indices = Array.isArray(item.resultData.indices) ? item.resultData.indices : []
      const labels = indices
        .map(index => index.index_type_display || index.index_type?.toUpperCase())
        .filter(Boolean)
        .join('、')
      return normalizeAccountHistoryItem({
        id: `remote-${item.imageId}-${item.indexType}-${item.timestamp}`,
        feature: '遥感生态',
        title: item.fileName || '遥感生态指数结果',
        subtitle: labels || item.indexType?.toUpperCase() || '指数结果',
        timestamp: item.timestamp,
        owner: item.owner || item.resultData.owner
      })
    })
}

const getStoredResultHistory = (featureKey, featureLabel) => {
  const history = safeJsonParse(localStorage.getItem(`tianshui_result_history_v1:${featureKey}`), [])
  if (!Array.isArray(history)) return []
  return history
    .filter(item => canViewHistoryItem(item, currentUser.value, {
      adminCanViewAll: true,
      adminCanViewOwnerless: true
    }))
    .map(item => normalizeAccountHistoryItem({
      id: `${featureKey}-${item.id}`,
      feature: featureLabel,
      title: item.title || item.payload?.fileName || '处理结果',
      subtitle: item.subtitle || '结果缓存',
      timestamp: item.timestamp,
      owner: item.owner || item.payload?.owner,
      payload: item.payload
    }))
}

const refreshAccountResultHistory = () => {
  if (!currentUser.value) {
    accountResultHistory.value = []
    return
  }
  accountResultHistory.value = [
    ...getRemoteAccountHistory(),
    ...getStoredResultHistory('ecological_index', '生态环境'),
    ...getStoredResultHistory('climate_monitoring', '气候监测'),
    ...getStoredResultHistory('overlay_analysis_view', '叠加分析'),
  ]
    .sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0))
    .slice(0, 18)
}

const openDataGovernanceDialog = () => {
  refreshAccountResultHistory()
  dataGovernanceDialogVisible.value = true
}

const getRemoteResultLayersFromCache = () => {
  const storageKeys = safeJsonParse(localStorage.getItem('analysis_cache_index'), [])
  if (!Array.isArray(storageKeys)) return []

  return storageKeys.flatMap((storageKey) => {
    const cacheItem = safeJsonParse(localStorage.getItem(storageKey), null)
    if (!cacheItem || !canViewHistoryItem(cacheItem, currentUser.value, {
      adminCanViewAll: true,
      adminCanViewOwnerless: true
    })) {
      return []
    }
    const indices = Array.isArray(cacheItem?.resultData?.indices) ? cacheItem.resultData.indices : []
    return indices
      .filter(item => item?.compare_overlay?.overlay_image_url)
      .map(item => ({
        id: `remote-${cacheItem.imageId || cacheItem.backendImageId || storageKey}-${item.index_type}`,
        title: `${cacheItem.fileName || '遥感生态指数'} - ${item.index_type_display || item.index_type?.toUpperCase() || '结果'}`,
        subtitle: `遥感分析 ${formatAnalysisLayerTime(cacheItem.timestamp)}`,
        compareOverlay: item.compare_overlay,
        timestamp: Number(cacheItem.timestamp || 0)
      }))
  })
}

const getEcologicalResultLayersFromCache = () => {
  const history = safeJsonParse(localStorage.getItem('tianshui_result_history_v1:ecological_index'), [])
  if (!Array.isArray(history)) return []

  return history
    .filter(item => canViewHistoryItem(item, currentUser.value, {
      adminCanViewAll: true,
      adminCanViewOwnerless: true
    }))
    .filter(item => item?.payload?.compareOverlay?.overlay_image_url)
    .map(item => ({
      id: `ecological-${item.id}`,
      title: `${item.title || item.payload.fileName || '生态环境指数'} - 土地利用结果图`,
      subtitle: `生态指数 ${formatAnalysisLayerTime(item.timestamp)}`,
      compareOverlay: item.payload.compareOverlay,
      timestamp: Number(item.timestamp || 0)
    }))
}

const loadAnalysisResultLayers = async () => {
  if (analysisLayerReloading) {
    analysisLayerReloadQueued = true
    return
  }

  analysisLayerReloading = true
  await nextTick()
  try {
    do {
      analysisLayerReloadQueued = false

      if (!currentUser.value) {
        analysisResultLayers.value = []
        mapContainerRef.value?.removeAnalysisResultLayers?.({ removePersisted: false })
        continue
      }

      const layers = loadMainMapAnalysisLayers(currentUser.value, {
        adminCanViewAll: false,
        adminCanViewOwnerless: false
      })
      analysisResultLayers.value = layers
      mapContainerRef.value?.removeAnalysisResultLayers?.({ removePersisted: false })
      layers.forEach((item) => {
        mapContainerRef.value?.addResultOverlayLayer(item.compareOverlay, {
          id: item.id,
          name: '分析结果图层',
          subtitle: item.title,
          opacity: item.opacity || 0.68
        })
      })
    } while (analysisLayerReloadQueued)
  } finally {
    analysisLayerReloading = false
  }
}

const syncAnalysisResultLayers = async () => {
  await loadAnalysisResultLayers()
}

const handleBusinessLayerUpload = async (event) => {
  const file = event.target.files[0]
  event.target.value = ''
  if (!file) return
  if (!requireLayerLogin()) return

  businessLayerUploading.value = true
  try {
    const result = await spatialService.uploadBusinessLayer(file, {
      name: file.name.replace(/\.[^.]+$/, '')
    })
    upsertBusinessLayer(result)
    if (result.status === 'published') {
      ElMessage.success(`${result.name} 已上传并发布到 GeoServer`)
    } else {
      ElMessage.warning(`${result.name} 已保存，但发布未完成：${result.error_message || result.status_display}`)
    }
  } catch (error) {
    console.error(error)
    ElMessage.error(getRequestErrorMessage(error, '业务图层上传或发布失败，请检查文件格式和GeoServer状态'))
  } finally {
    businessLayerUploading.value = false
  }
}

const handleBusinessServiceCreate = async () => {
  if (!requireLayerLogin()) return
  syncBusinessServiceLayerType()
  if (!businessServiceForm.name.trim()) {
    ElMessage.warning('请填写图层名称')
    return
  }
  if (!businessServiceForm.service_url.trim()) {
    ElMessage.warning('请填写标准服务地址')
    return
  }

  businessServiceSubmitting.value = true
  try {
    const result = await spatialService.createBusinessServiceLayer({
      name: businessServiceForm.name.trim(),
      description: businessServiceForm.description.trim(),
      layer_type: businessServiceForm.layer_type,
      source_format: businessServiceForm.source_format,
      service_url: businessServiceForm.service_url.trim(),
      service_type_name: businessServiceForm.service_type_name.trim(),
      service_srs: businessServiceForm.service_srs.trim(),
      style_name: businessServiceForm.style_name.trim()
    })
    upsertBusinessLayer(result)
    businessServiceDialogVisible.value = false
    ElMessage.success(`${result.name} 已接入业务图层服务`)
  } catch (error) {
    console.error(error)
    ElMessage.error(getRequestErrorMessage(error, '标准服务接入失败，请检查服务地址和图层名称'))
  } finally {
    businessServiceSubmitting.value = false
  }
}

const handleBusinessLayerPublish = async (layer) => {
  if (!requireLayerLogin()) return
  if (!layer?.serviceLayer?.id || isBusinessLayerBusy(layer)) return
  setBusinessLayerBusy(layer, true)
  try {
    const result = await spatialService.publishBusinessLayer(layer.serviceLayer.id)
    upsertBusinessLayer(result)
    ElMessage.success(`${result.name} 已发布到 GeoServer`)
  } catch (error) {
    console.error(error)
    ElMessage.error(getRequestErrorMessage(error, '重新发布失败，请检查GeoServer状态'))
  } finally {
    setBusinessLayerBusy(layer, false)
  }
}

const handleBusinessLayerUnpublish = async (layer) => {
  if (!requireLayerLogin()) return
  if (!layer?.serviceLayer?.id || isBusinessLayerBusy(layer)) return
  try {
    await ElMessageBox.confirm(
      `撤销后 ${layer.name} 会从GeoServer服务中移除，但源文件记录仍保留。`,
      '撤销发布',
      { type: 'warning', confirmButtonText: '撤销发布', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  setBusinessLayerBusy(layer, true)
  try {
    mapContainerRef.value?.removeBusinessServiceLayer(layer.serviceLayer)
    layer.visible = false
    const result = await spatialService.unpublishBusinessLayer(layer.serviceLayer.id)
    upsertBusinessLayer(result)
    ElMessage.success(`${result.name} 已撤销发布`)
  } catch (error) {
    console.error(error)
    ElMessage.error(getRequestErrorMessage(error, '撤销发布失败，请检查GeoServer状态'))
  } finally {
    setBusinessLayerBusy(layer, false)
  }
}

const handleBusinessLayerDelete = async (layer) => {
  if (!requireLayerLogin()) return
  if (!layer?.serviceLayer?.id || isBusinessLayerBusy(layer)) return
  try {
    await ElMessageBox.confirm(
      `确定删除 ${layer.name} 吗？如果已发布，会同时尝试清理GeoServer服务。`,
      '删除业务图层',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  setBusinessLayerBusy(layer, true)
  try {
    await spatialService.deleteBusinessLayer(layer.serviceLayer.id)
    mapContainerRef.value?.removeBusinessServiceLayer(layer.serviceLayer)
    const index = businessLayers.findIndex(item => item.id === layer.id)
    if (index > -1) businessLayers.splice(index, 1)
    mapContainerRef.value?.pruneBusinessServiceLayers(
      businessLayers.filter(item => item.source === 'service').map(item => item.serviceLayer)
    )
    ElMessage.success(`${layer.name} 已删除`)
  } catch (error) {
    console.error(error)
    ElMessage.error(getRequestErrorMessage(error, '删除业务图层失败'))
  } finally {
    setBusinessLayerBusy(layer, false)
  }
}

const handleBusinessLayerStyleSave = async () => {
  if (!requireLayerLogin()) return
  if (!activeBusinessLayer.value?.serviceLayer?.id) return
  businessLayerStyleSubmitting.value = true
  try {
    const targetLayer = activeBusinessLayer.value
    const payload = {
      style_name: businessLayerStyleForm.style_name
    }
    if (businessLayerStyleForm.sld_content !== (targetLayer.serviceLayer.sld_content || '')) {
      payload.sld_content = businessLayerStyleForm.sld_content
    }
    if (businessLayerStyleForm.layer_type === 'vector') {
      Object.assign(payload, {
        fill_color: businessLayerStyleForm.fill_color,
        stroke_color: businessLayerStyleForm.stroke_color,
        stroke_width: Number(businessLayerStyleForm.stroke_width),
        fill_opacity: Number(businessLayerStyleForm.fill_opacity),
        classification_field: businessLayerStyleForm.classification_field,
        color_scheme: businessLayerStyleForm.color_scheme
      })
    } else {
      Object.assign(payload, {
        raster_color_ramp: businessLayerStyleForm.raster_color_ramp,
        raster_opacity: Number(businessLayerStyleForm.raster_opacity),
        nodata: businessLayerStyleForm.nodata === '' ? null : Number(businessLayerStyleForm.nodata)
      })
    }
    const result = await spatialService.updateBusinessLayerStyle(targetLayer.serviceLayer.id, payload)
    upsertBusinessLayer(result)
    mapContainerRef.value?.addBusinessServiceLayer(result, targetLayer.visible)
    businessLayerStyleDialogVisible.value = false
    ElMessage.success(`${result.name} 样式已更新`)
  } catch (error) {
    console.error(error)
    ElMessage.error(getRequestErrorMessage(error, '业务图层样式更新失败'))
  } finally {
    businessLayerStyleSubmitting.value = false
  }
}

// 处理文件上传
const handleFileUpload = (event) => {
  const file = event.target.files[0]
  event.target.value = ''
  if (!requireLayerLogin()) return
  if (file) {
    mapContainerRef.value?.loadLocalFile(file).then((success) => {
      if (success) {
        ElMessage.success(`${file.name} 已加载为临时图层`)
      }
    })
  }
}

// 坐标定位
const locateCoordinate = () => {
  mapContainerRef.value?.locateCoordinate(coordinateInput.value)
}

// 导出地图
const exportMap = () => {
  mapContainerRef.value?.exportMap('png')
}

const handleBusinessLayerToggle = async (layer) => {
  layer.visible = !layer.visible
  if (layer.source === 'service') {
    if (layer.status !== 'published') {
      layer.visible = false
      ElMessage.warning(`${layer.name} 尚未发布成功，不能加载到地图`)
      return
    }
    if (layer.serviceLayer?.source_format === 'wcs' && !layer.serviceLayer?.wms_url) {
      layer.visible = false
      ElMessage.info(`${layer.name} 当前接入的是 WCS 覆盖服务，可用于数据访问，暂不支持直接地图渲染`)
      return
    }
    const applied = mapContainerRef.value?.addBusinessServiceLayer(layer.serviceLayer, layer.visible)
    if (!applied) {
      layer.visible = false
      ElMessage.error(`${layer.name} 缺少可加载的 WMS/WFS 服务地址`)
    }
    return
  }

  const applied = mapContainerRef.value?.setLayerVisibleById(layer.id, layer.visible)
  if (applied) {
    return
  }
  ElMessage.info(`${layer.name} 正在加载真实图层数据，请稍后再试`)
}

// 折叠切换方法
const toggleLayerManagement = () => {
  layerManagementExpanded.value = !layerManagementExpanded.value
}

const toggleBusinessLayers = () => {
  businessLayersExpanded.value = !businessLayersExpanded.value
}

const toggleTempLayers = () => {
  tempLayersExpanded.value = !tempLayersExpanded.value
}

const toggleToolbox = () => {
  toolboxExpanded.value = !toolboxExpanded.value
}

const toggleBusinessFunctions = () => {
  businessFunctionsExpanded.value = !businessFunctionsExpanded.value
}
</script>

<style scoped>
.map-view {
  position: relative;
  display: flex;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  background: #06182d;
}

/* 左侧边栏 */
.sidebar {
  width: 360px;
  height: 100vh;
  background: #0b2340;
  border-right: 1px solid #18385d;
  display: flex;
  flex-direction: column;
  box-shadow: 2px 0 18px rgba(0, 0, 0, 0.22);
  overflow-y: auto;
  overflow-x: hidden;
  flex-shrink: 0;
  color: #c4d4eb;
  position: relative;
  z-index: 4;
}

.sidebar-header,
.user-section,
.section {
  flex-shrink: 0;
}

.sidebar-header {
  position: relative;
  min-height: 110px;
  padding: 0;
  text-align: left;
  background: #0b2340;
  border-bottom: 1px solid #18385d;
  overflow: hidden;
}

.brand-header-decoration {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.brand-header-shape {
  fill: #06182d;
}

.brand-row {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  min-height: 110px;
  padding: 22px 34px 20px 24px;
  min-width: 0;
}

.brand-logo {
  position: relative;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  border: 1px solid rgba(255, 255, 255, 0.28);
  border-radius: 50%;
  background: #ffffff;
  box-shadow: none;
  overflow: hidden;
}

.brand-logo-svg {
  display: block;
  width: 100%;
  height: 100%;
}

.brand-copy {
  min-width: 0;
  width: 100%;
}

.brand-org-row {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.brand-org {
  color: #91a9c4;
  font-size: 14px;
  line-height: 1.3;
  font-weight: 400;
  white-space: nowrap;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar-header h1 {
  margin: 9px 0 0;
  font-size: 21px;
  line-height: 1.22;
  font-weight: 700;
  color: #ffffff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: clip;
}

/* 左侧信息区 */
.user-section,
.section {
  margin: 0 16px 18px;
  border-radius: 8px;
  border: 1px solid #18385d;
  background: transparent;
  box-shadow: none;
}

/* 用户信息 */
.user-section {
  margin-top: 14px;
  padding: 14px;
  background: #102d4d;
  border-color: #1d4264;
  box-shadow: none;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  align-items: stretch;
  gap: 10px;
  overflow: visible;
}

.user-section-title {
  padding-bottom: 10px;
  border-bottom: 1px solid #18385d;
  color: #26b6e8;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.3;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #edf6fb;
  min-width: 0;
}

.user-info span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: normal;
  line-height: 1.35;
}

.inline-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: currentColor;
}

.button-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.user-icon {
  width: 28px;
  height: 28px;
  padding: 5px;
  border: 1px solid #1677ff;
  border-radius: 50%;
  color: #26b6e8;
}

.user-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
}

.admin-btn {
  background: #1677ff;
  color: #ffffff;
  border: 1px solid #1677ff;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  line-height: 1.2;
  font-weight: 600;
  min-height: 36px;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
}

.admin-btn:hover {
  background: #2688ff;
  border-color: #2688ff;
}

.governance-btn {
  color: #ffffff;
  border-color: #1677ff;
  background: #1677ff;
}

.governance-btn:hover {
  background: #2688ff;
  border-color: #2688ff;
}

.login-btn {
  background: #102d4d;
  color: #c4d4eb;
  border: 1px solid #24527d;
  padding: 8px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  line-height: 1.2;
  min-height: 36px;
  width: 100%;
}

.login-btn:hover {
  background: #183b61;
  border-color: #2d6a9f;
  color: #ffffff;
}

.login-mask {
  position: fixed;
  inset: 0;
  z-index: 9000;
  background: rgba(8, 23, 43, 0.78);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.login-dialog {
  width: 320px;
  padding: 22px;
  border-radius: 10px;
  background: #102d4d;
  border: 1px solid #1c4265;
  box-shadow: 0 18px 42px rgba(0, 0, 0, 0.36);
}

.service-dialog {
  width: min(460px, calc(100vw - 32px));
  max-height: calc(100vh - 48px);
  overflow-y: auto;
  padding: 22px;
  border-radius: 10px;
  background: #102d4d;
  border: 1px solid #1c4265;
  box-shadow: 0 18px 42px rgba(0, 0, 0, 0.36);
}

.login-title {
  margin-bottom: 18px;
  color: #ffffff;
  font-size: 18px;
  font-weight: 700;
}

.form-error-banner {
  margin: -6px 0 14px;
  padding: 10px 12px;
  border: 1px solid rgba(239, 68, 68, 0.28);
  border-radius: 7px;
  background: rgba(239, 68, 68, 0.12);
  color: #ffaaa3;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
}

:global(.el-overlay.user-delete-confirm-mask),
:global(.el-overlay.is-message-box) {
  z-index: 5000 !important;
}

:global(.user-delete-confirm-box) {
  z-index: 5001 !important;
}

:global(.user-delete-confirm-box .el-message-box__btns .el-button--primary) {
  background: #d92d20;
  border-color: #d92d20;
}

.login-field {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-bottom: 14px;
  color: #c4d4eb;
  font-size: 13px;
}

.login-field input {
  height: 36px;
  padding: 0 10px;
  border: 1px solid #1c4265;
  border-radius: 6px;
  color: #ffffff;
  background: #102d4d;
  outline: none;
}

.login-field select,
.login-field textarea {
  padding: 8px 10px;
  border: 1px solid #1c4265;
  border-radius: 6px;
  color: #ffffff;
  background: #102d4d;
  outline: none;
  font: inherit;
  resize: vertical;
}

.color-field {
  display: flex;
  align-items: center;
  gap: 10px;
}

.color-input {
  width: 42px;
  min-width: 42px;
  height: 36px;
  padding: 4px;
  border: 1px solid #1c4265;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
}

.login-field input:focus,
.login-field select:focus,
.login-field textarea:focus {
  border-color: #1677ff;
  box-shadow: none;
}

.login-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.login-dialog .login-actions button {
  min-height: 36px;
  padding: 0 16px;
  border-radius: 6px;
  line-height: 1;
  white-space: nowrap;
  flex: 0 0 auto;
}

.login-dialog .login-actions .dialog-confirm {
  min-width: 84px;
}

.login-dialog .login-actions .dialog-cancel {
  background: #102d4d;
  border: 1px solid #24527d;
  color: #c4d4eb;
}

.login-dialog .login-actions .dialog-cancel:hover {
  background: #183b61;
  border-color: #2d6a9f;
  color: #ffffff;
}

.user-management-dialog {
  width: min(920px, calc(100vw - 48px));
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  margin-left: 56px;
  background: #0f223d;
  border-color: #285276;
}

.user-admin-toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-bottom: 0;
}

.user-management-dialog .login-title {
  margin-bottom: 0;
  line-height: 1.35;
}

.user-management-dialog .empty-log,
.user-management-dialog .user-list,
.user-management-dialog .login-actions {
  grid-column: 1 / -1;
}

.user-list {
  display: grid;
  gap: 12px;
  max-height: 55vh;
  overflow-y: auto;
}

.user-card {
  border: 1px solid #1d4264;
  border-radius: 8px;
  padding: 14px 16px;
  background: #132a48;
}

.user-card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 10px;
}

.user-card-name {
  font-size: 15px;
  font-weight: 700;
  color: #ffffff;
}

.user-card-meta {
  font-size: 12px;
  color: #8299bc;
  margin-top: 4px;
}

.user-card-actions {
  display: flex;
  gap: 8px;
  flex: 0 0 auto;
}

.user-card-actions .layer-action-btn {
  width: 34px;
  height: 34px;
  padding: 0;
  border-color: #285276;
  background: #0d2745;
}

.user-card-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 16px;
  font-size: 13px;
  color: #c4d4eb;
}

.user-card-grid div {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.permission-dialog {
  width: min(860px, calc(100vw - 32px));
}

.governance-dialog {
  width: min(900px, calc(100vw - 32px));
}

.governance-account {
  margin-top: -6px;
  margin-bottom: 14px;
  color: #5f7488;
  font-size: 13px;
}

.governance-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.governance-policy-card {
  padding: 14px;
  border: 1px solid #dbe6f0;
  border-radius: 8px;
  background: #f8fbfd;
  color: #4e6478;
  font-size: 13px;
  line-height: 1.7;
}

.governance-policy-title {
  margin-bottom: 8px;
  color: #24405f;
  font-weight: 700;
}

.governance-history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 8px 0 10px;
  color: #24405f;
  font-size: 14px;
  font-weight: 700;
}

.governance-history-list {
  display: grid;
  gap: 10px;
  max-height: 42vh;
  overflow-y: auto;
}

.governance-history-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 12px;
  border: 1px solid #dbe6f0;
  border-radius: 8px;
  background: #102d4d;
}

.governance-history-main {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 5px;
  min-width: 0;
}

.governance-history-main strong,
.governance-history-main small {
  max-width: 100%;
  overflow: visible;
  text-overflow: clip;
  white-space: normal;
  word-break: break-word;
}

.governance-history-main strong {
  color: #26384a;
  font-size: 13px;
}

.governance-history-main small,
.governance-history-meta {
  color: #6f8498;
  font-size: 12px;
}

.governance-history-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 5px;
  flex-shrink: 0;
}

.permission-subtitle {
  margin-bottom: 14px;
  font-size: 13px;
  color: #5f7488;
}

.permission-groups {
  display: grid;
  gap: 14px;
  max-height: 55vh;
  overflow-y: auto;
}

.permission-group {
  border: 1px solid #dbe6f0;
  border-radius: 8px;
  padding: 14px 16px;
  background: #f8fbfd;
}

.permission-group-title {
  margin-bottom: 10px;
  font-size: 14px;
  font-weight: 700;
  color: #24405f;
}

.permission-options {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
}

.permission-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #4e6478;
}

.dialog-cancel,
.dialog-confirm {
  height: 34px;
  padding: 0 16px;
  border-radius: 6px;
  cursor: pointer;
}

.dialog-cancel {
  border: 1px solid #d9e2ec;
  color: #4b5563;
  background: #fff;
}

.dialog-confirm {
  border: 1px solid #2f97b9;
  color: #fff;
  background: #2f97b9;
}

.dialog-confirm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 功能区块 */
.section {
  margin: 0 16px 20px;
  padding: 0 0 18px;
  border: none;
  border-bottom: 1px solid #18385d;
  border-radius: 0;
  background: transparent;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-weight: 700;
  color: #ffffff;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
  padding: 0 2px;
  border-radius: 6px;
  font-size: 14px;
  line-height: 1.35;
}

.section-header:hover {
  background: transparent;
}

.collapse-icon {
  margin-left: auto;
  font-size: 12px;
  transition: transform 0.3s;
  color: #8299bc;
}

.collapse-icon.collapsed {
  transform: rotate(-90deg);
}

.section-content {
  animation: slideDown 0.3s ease-out;
  padding: 0 2px;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.section-icon {
  color: #26b6e8;
  width: 15px;
  height: 15px;
  flex: 0 0 15px;
}

/* 图层管理 */
.layer-group {
  margin-bottom: 16px;
}

.layer-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
  padding: 2px 0;
  margin-bottom: 10px;
  transition: background 0.2s;
  border-radius: 4px;
}

.layer-group-header:hover {
  background: transparent;
}

.layer-group-header h4 {
  margin: 0;
  font-size: 14px;
  color: #8299bc;
  font-weight: 600;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.layer-group-content {
  padding: 0;
}

.analysis-layer-box {
  margin-top: 12px;
  padding: 10px;
  border: 1px solid #1c4265;
  border-radius: 7px;
  background: #0d2745;
}

.analysis-layer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
  color: #ffffff;
  font-size: 13px;
  font-weight: 700;
}

.mini-text-btn {
  border: 1px solid #24527d;
  border-radius: 5px;
  background: #102d4d;
  color: #c4d4eb;
  padding: 3px 8px;
  font-size: 12px;
  cursor: pointer;
}

.analysis-layer-empty {
  color: #8299bc;
  font-size: 12px;
  line-height: 1.5;
}

.analysis-layer-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.analysis-layer-item {
  width: 100%;
  min-height: 42px;
  padding: 7px 9px;
  border: 1px solid #1c4265;
  border-radius: 6px;
  background: #0d2745;
  color: #c4d4eb;
  text-align: left;
  cursor: pointer;
}

.analysis-layer-item span,
.analysis-layer-item small {
  display: block;
  overflow: visible;
  text-overflow: clip;
  white-space: normal;
  word-break: break-word;
}

.analysis-layer-item span {
  font-size: 12px;
  font-weight: 700;
  line-height: 1.35;
}

.analysis-layer-item small {
  margin-top: 3px;
  color: #8299bc;
  font-size: 11px;
  line-height: 1.35;
}

.layer-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  min-height: 40px;
  padding: 8px 9px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  gap: 10px;
}

.layer-item:last-child {
  border-bottom: 1px solid transparent;
}

.layer-item:hover {
  background: #183b61;
  border-color: #1c4265;
}

.layer-info {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  min-width: 0;
}

.layer-info-rich {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  flex: 1;
}

.layer-main-row {
  display: flex;
  align-items: flex-start;
  gap: 0;
  min-width: 0;
}

.layer-icon,
.function-icon {
  color: #26b6e8;
}

.layer-main-row > .layer-icon {
  display: none;
}

.layer-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.layer-text span {
  overflow: visible;
  text-overflow: clip;
  white-space: normal;
  word-break: break-word;
  line-height: 1.35;
}

.layer-status {
  margin-top: 2px;
  font-size: 11px;
  line-height: 1.2;
  color: #8299bc;
}

.layer-status.published {
  color: #77d9a3;
}

.layer-status.failed {
  color: #ff9f98;
}

.layer-status.publishing {
  color: #ffcf7a;
}

.layer-meta-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.layer-pill {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 6px;
  border: 1px solid #1c4265;
  background: #0d2745;
  color: #c4d4eb;
  font-size: 11px;
  line-height: 1;
}

.health-pill.health-healthy {
  border-color: rgba(119, 217, 163, 0.28);
  background: rgba(23, 118, 79, 0.16);
  color: #8fefbe;
}

.health-pill.health-unhealthy {
  border-color: rgba(255, 159, 152, 0.28);
  background: rgba(136, 50, 45, 0.16);
  color: #ffb5ad;
}

.layer-detail-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.layer-detail-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: 12px;
  line-height: 1.5;
}

.detail-label {
  width: 34px;
  flex-shrink: 0;
  color: #8299bc;
}

.detail-value {
  color: #c4d4eb;
  word-break: break-word;
}

.layer-url {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.log-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.log-item {
  padding: 12px;
  border: 1px solid #1c4265;
  border-radius: 8px;
  background: #0d2745;
}

.log-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.log-line {
  font-size: 12px;
  color: #c4d4eb;
  line-height: 1.5;
}

.log-line.muted {
  color: #8299bc;
  margin-top: 4px;
}

.log-toggle-btn {
  height: 24px;
  padding: 0 8px;
  border: 1px solid #24527d;
  border-radius: 6px;
  background: #102d4d;
  color: #c4d4eb;
  font-size: 11px;
  cursor: pointer;
}

.log-toggle-btn:hover {
  background: #183b61;
}

.log-details {
  margin: 8px 0 0;
  padding: 10px;
  border-radius: 6px;
  background: #102d4d;
  color: #c4d4eb;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.empty-log {
  padding: 16px 0;
  color: #8299bc;
  font-size: 13px;
  text-align: center;
}

.layer-controls {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
  padding-top: 1px;
}

.layer-action-btn {
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px solid #24527d;
  border-radius: 5px;
  background: #102d4d;
  color: #c4d4eb;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.layer-action-btn:hover {
  background: #183b61;
  border-color: #2d6a9f;
}

.layer-action-btn.danger {
  color: #ffb4ae;
}

.layer-action-btn.danger:hover {
  background: rgba(177, 54, 47, 0.16);
  border-color: rgba(255, 159, 152, 0.28);
}

.layer-action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 开关样式 */
.toggle-switch {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 20px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #0b2340;
  border: 1px solid #47708f;
  transition: .4s;
  border-radius: 20px;
}

.slider:before {
  position: absolute;
  content: "";
  height: 16px;
  width: 16px;
  left: 2px;
  bottom: 2px;
  background-color: white;
  transition: .4s;
  border-radius: 50%;
}

input:checked + .slider {
  background-color: #1677ff;
}

input:checked + .slider:before {
  transform: translateX(20px);
}

.load-btn {
  background: #102d4d;
  border: 1px solid #1c4265;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  color: #c4d4eb;
}

.load-btn:hover {
  background: #183b61;
  border-color: #1677ff;
}

/* 上传按钮 */
.upload-btn {
  width: 100%;
  background: #1677ff;
  color: white;
  border: 1px solid #1677ff;
  padding: 12px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s;
  box-sizing: border-box;
  min-height: 44px;
  height: auto;
  line-height: 1.35;
  white-space: normal;
}

.upload-btn:hover {
  background: #2688ff;
  border-color: #2688ff;
  transform: none;
  box-shadow: none;
}

.publish-btn {
  margin-bottom: 8px;
  background: #1677ff;
}

.publish-btn:hover {
  background: #2688ff;
}

.publish-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
  transform: none;
}

.service-btn {
  margin-bottom: 10px;
  background: #102d4d;
  border-color: #24527d;
  color: #c4d4eb;
}

.service-btn:hover {
  background: #183b61;
  border-color: #2d6a9f;
  color: #ffffff;
}

/* 工具箱 */
.tool-tip {
  font-size: 12px;
  color: #8299bc;
  margin-bottom: 12px;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.coordinate-section h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
  color: #c4d4eb;
  font-weight: normal;
}

.coordinate-inputs {
  display: flex;
  gap: 8px;
}

.coordinate-inputs input {
  flex: 1;
  padding: 8px;
  border: 1px solid #1c4265;
  border-radius: 4px;
  font-size: 12px;
  color: #c4d4eb;
  background: #102d4d;
  min-width: 0;
}

.locate-btn {
  background: #1677ff;
  color: white;
  border: 1px solid #1677ff;
  padding: 8px 12px;
  border-radius: 4px;
  cursor: pointer;
}

.locate-btn:hover {
  background: #2688ff;
}

.export-btn {
  width: 100%;
  background: #1677ff;
  color: white;
  border: 1px solid #1677ff;
  padding: 12px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s;
  box-sizing: border-box;
  min-height: 44px;
  height: auto;
  margin-top: 12px;
  line-height: 1.35;
  white-space: normal;
}

.export-btn:hover {
  background: #2688ff;
  border-color: #2688ff;
  transform: none;
  box-shadow: none;
}

/* 业务功能 */
.business-functions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.function-item {
  appearance: none;
  width: 100%;
  min-height: 58px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 10px 10px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: #c4d4eb;
  cursor: pointer;
  box-shadow: none;
  transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
  font-size: 13px;
  text-align: left;
}

.function-item:hover,
.function-item.active {
  background: #183b61;
  border-color: #1c4265;
  color: #ffffff;
  box-shadow: none;
  transform: none;
}

.function-item.disabled,
.function-item:disabled {
  opacity: 0.52;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.function-item.disabled:hover,
.function-item:disabled:hover {
  background: transparent;
  border-color: transparent;
  color: #c4d4eb;
}

.function-leading {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.function-icon-box {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #c4d4eb;
  background: #102d4d;
  border: 1px solid #1c4265;
  flex-shrink: 0;
  overflow: hidden;
}

.function-icon-box svg {
  width: 15px;
  height: 15px;
}

.function-item:hover .function-icon-box,
.function-item.active .function-icon-box {
  color: #ffffff;
  background: #183b61;
  border-color: #1677ff;
}

.function-copy {
  display: flex;
  align-items: center;
  min-width: 0;
  flex: 1;
}

.function-name {
  flex: 1;
  min-width: 0;
  overflow: visible;
  text-overflow: clip;
  white-space: normal;
  line-height: 1.35;
  font-weight: 600;
  font-size: 13px;
}

.function-arrow {
  width: 16px;
  height: 16px;
  color: #8299bc;
  opacity: 0.7;
  transform: translateX(-2px);
  transition: opacity 0.18s ease, transform 0.18s ease;
  flex-shrink: 0;
}

.function-item:hover .function-arrow,
.function-item.active .function-arrow {
  opacity: 1;
  transform: translateX(0);
}

/* 主地图区域 */
.main-content {
  flex: 1;
  position: relative;
  min-width: 0;
  height: 100vh;
  padding: 12px;
  background: #06182d;
  overflow: hidden;
}

.map-stage {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  border: 1px solid #1c4265;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
}

.map-login-float {
  position: absolute;
  top: 18px;
  right: 348px;
  z-index: 1200;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 74px;
  height: 38px;
  padding: 0 16px;
  border: 1px solid #24527d;
  border-radius: 6px;
  background: #102d4d;
  color: #ffffff;
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.18);
}

.map-login-float:hover {
  background: #183b61;
  border-color: #2d6a9f;
}

.sidebar .section-content {
  padding: 0 2px;
}

.sidebar .upload-zone {
  background: #183b61;
  border-color: #1c4265;
}

.sidebar .upload-zone:hover {
  background: #183b61;
  border-color: #1677ff;
  box-shadow: none;
}

.sidebar .upload-text,
.sidebar .upload-hint,
.sidebar .upload-types,
.sidebar .layer-name,
.sidebar .analysis-layer-empty,
.sidebar .log-line.muted {
  color: #c4d4eb;
}

.sidebar .layer-group-content {
  padding: 0 8px;
}

.sidebar .coordinate-section h4 {
  margin-top: 2px;
}

.sidebar .coordinate-inputs input::placeholder {
  color: #8299bc;
}

.sidebar .layer-action-btn,
.sidebar .log-toggle-btn,
.sidebar .mini-text-btn,
.sidebar .load-btn {
  transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}

/* 主界面最终深蓝 GIS 按钮与层级覆盖。 */
.map-view {
  --gis-page: #06182d;
  --gis-workspace: #06182d;
  --gis-sidebar: #0b2340;
  --gis-card: #102d4d;
  --gis-module: #0d2745;
  --gis-hover: #183b61;
  --gis-primary: #1677ff;
  --gis-primary-hover: #2688ff;
  --gis-accent: #26b6e8;
  --gis-border: #1c4265;
  --gis-border-strong: #285a82;
  --gis-text: #ffffff;
  --gis-muted: #c4d4eb;
  --gis-subtle: #8299bc;
  --gis-disabled: #5d7494;
  background: var(--gis-page);
  color: var(--gis-text);
}

.sidebar {
  background: var(--gis-sidebar);
  border-right: 1px solid var(--gis-border);
  box-shadow: 2px 0 18px rgba(0, 0, 0, 0.24);
}

.sidebar-header {
  background: var(--gis-page);
  border-bottom: 1px solid var(--gis-border);
}

.user-info span {
  color: var(--gis-muted);
}

.sidebar-header h1 {
  color: var(--gis-text);
}

.user-section,
.section,
.analysis-layer-box {
  background: var(--gis-card);
  border: 1px solid var(--gis-border);
  box-shadow: none;
}

.section-header,
.layer-group-header h4,
.coordinate-section h4,
.analysis-layer-head {
  color: var(--gis-text);
}

.section-icon,
.user-icon,
.layer-icon,
.function-icon,
.analysis-layer-head .inline-icon {
  color: var(--gis-accent);
}

.admin-btn,
.login-btn,
.upload-btn,
.publish-btn,
.service-btn,
.export-btn,
.locate-btn,
.dialog-confirm {
  border: 1px solid var(--gis-primary);
  border-radius: 6px;
  background: var(--gis-primary);
  color: #ffffff;
  box-shadow: none;
}

.admin-btn:hover,
.login-btn:hover,
.upload-btn:hover,
.publish-btn:hover,
.service-btn:hover,
.export-btn:hover,
.locate-btn:hover,
.dialog-confirm:hover {
  background: var(--gis-primary-hover);
  border-color: var(--gis-primary-hover);
  box-shadow: none;
  transform: none;
}

.governance-btn {
  background: var(--gis-primary);
  border-color: var(--gis-primary);
  color: #ffffff;
}

.login-btn,
.service-btn {
  background: #102d4d;
  border-color: #24527d;
  color: #c4d4eb;
}

.login-btn:hover,
.service-btn:hover {
  background: #183b61;
  border-color: #2d6a9f;
  color: #ffffff;
}

.dialog-cancel,
.mini-text-btn,
.load-btn,
.log-toggle-btn,
.layer-action-btn {
  border: 1px solid var(--gis-border);
  border-radius: 6px;
  background: var(--gis-module);
  color: var(--gis-muted);
  box-shadow: none;
}

.dialog-cancel:hover,
.mini-text-btn:hover,
.load-btn:hover,
.log-toggle-btn:hover,
.layer-action-btn:hover {
  background: var(--gis-hover);
  border-color: var(--gis-border-strong);
  color: var(--gis-text);
}

.function-item {
  background: transparent;
  border: 1px solid transparent;
  color: #9fb5ca;
  box-shadow: none;
}

.function-item:hover {
  background: var(--gis-module);
  border-color: var(--gis-border);
  color: var(--gis-text);
  transform: none;
}

.function-item.active {
  background: #183b61;
  border-color: var(--gis-border-strong);
  color: var(--gis-text);
  box-shadow: inset 3px 0 0 var(--gis-primary);
  transform: none;
}

.function-icon-box {
  background: var(--gis-module);
  border-color: var(--gis-border);
  color: var(--gis-accent);
}

.function-item:hover .function-icon-box,
.function-item.active .function-icon-box {
  background: var(--gis-hover);
  border-color: var(--gis-border-strong);
  color: var(--gis-accent);
}

.analysis-layer-item,
.log-item,
.coordinate-inputs input {
  background: var(--gis-module);
  border: 1px solid var(--gis-border);
  color: var(--gis-muted);
}

.coordinate-inputs input:focus {
  border-color: var(--gis-border-strong);
  box-shadow: none;
}

.layer-pill {
  background: var(--gis-module);
  border-color: var(--gis-border);
  color: var(--gis-muted);
}

.slider {
  background-color: #31506e;
}

input:checked + .slider {
  background-color: var(--gis-primary);
}

.main-content {
  background: var(--gis-workspace);
}

/* Final visual corrections for the referenced GIS workstation layout. */
.map-view .sidebar-header {
  min-height: 110px !important;
  padding: 0 !important;
  background: #0b2340 !important;
  border-bottom-color: #18385d !important;
  clip-path: none !important;
  overflow: hidden !important;
}

.map-view .user-section {
  margin: 14px 16px 18px !important;
  padding: 14px !important;
  background: #102d4d !important;
  border: 1px solid #1d4264 !important;
  border-radius: 8px !important;
  box-shadow: none !important;
}

.map-view .section {
  margin: 0 16px 20px !important;
  padding: 0 0 18px !important;
  background: transparent !important;
  border: none !important;
  border-bottom: 1px solid #18385d !important;
  border-radius: 0 !important;
}

.map-view .user-actions {
  display: grid !important;
  grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
  gap: 8px !important;
}

.map-view .user-actions .admin-btn,
.map-view .user-actions .login-btn {
  width: 100% !important;
  min-width: 0 !important;
  padding: 8px 6px !important;
  white-space: nowrap !important;
}

.map-view .user-icon {
  width: 28px !important;
  height: 28px !important;
  padding: 5px !important;
  border: 1px solid #1677ff !important;
  border-radius: 50% !important;
  color: #26b6e8 !important;
}

.map-view .section-header {
  padding: 0 2px !important;
}

.map-view .section-icon {
  width: 15px !important;
  height: 15px !important;
  flex: 0 0 15px !important;
}

.map-view .layer-main-row > .layer-icon {
  display: none !important;
}

.map-view .layer-main-row {
  gap: 0 !important;
}

@media (max-width: 1100px) {
  .user-management-dialog {
    margin-left: 0 !important;
  }

  .user-card-grid {
    grid-template-columns: 1fr !important;
  }

  .map-login-float {
    display: none !important;
  }
}
</style> 
