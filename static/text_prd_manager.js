/**
 * 文本需求管理组件
 * 功能：上传、列表、详情、编辑、配置、启动任务
 */

Vue.component('text-prd-manager', {
    props: {
        initialView: {
            type: String,
            default: 'list' // 默认显示列表
        }
    },
    template: `
    <div class="text-prd-manager">
        <!-- 列表视图 -->
        <div v-if="currentView === 'list'" class="prd-list-view">
            <el-card class="box-card">
                <!-- 标题栏 -->
                <div slot="header" class="clearfix">
                    <span class="section-title">文本需求</span>
                    <el-button 
                        type="primary" 
                        size="small" 
                        style="float: right;"
                        @click="showUploadDialog = true">
                        <i class="el-icon-upload"></i> 导入文本需求
                    </el-button>
                </div>
                
                <!-- 过滤器 -->
                <div class="filter-bar">
                    <el-radio-group v-model="statusFilter" size="small" @change="loadPRDList">
                        <el-radio-button label="">全部</el-radio-button>
                        <el-radio-button label="draft">草稿</el-radio-button>
                        <el-radio-button label="processing">处理中</el-radio-button>
                        <el-radio-button label="completed">已完成</el-radio-button>
                    </el-radio-group>
                </div>
                
                <!-- PRD列表 -->
                <el-table 
                    :data="prdList" 
                    style="width: 100%; margin-top: 20px;"
                    v-loading="loading">
                    <el-table-column prop="name" label="需求名称" min-width="200">
                        <template slot-scope="scope">
                            <i class="el-icon-document"></i>
                            {{ scope.row.name }}
                        </template>
                    </el-table-column>
                    <el-table-column prop="status" label="状态" width="120">
                        <template slot-scope="scope">
                            <el-tag :type="getStatusType(scope.row)" size="small">
                                {{ getStatusText(scope.row) }}
                            </el-tag>
                        </template>
                    </el-table-column>
                    <el-table-column prop="created_at" label="创建时间" width="180">
                        <template slot-scope="scope">
                            {{ formatDateTime(scope.row.created_at) }}
                        </template>
                    </el-table-column>
                    <el-table-column label="操作" width="280">
                        <template slot-scope="scope">
                            <div style="display: flex; gap: 5px; flex-wrap: wrap; align-items: center;">
                                <el-button 
                                    type="info" 
                                    size="mini" 
                                    @click="viewPRDDetail(scope.row.id)">
                                    查看详情
                                </el-button>
                                <el-button 
                                    type="success" 
                                    size="mini" 
                                    v-if="scope.row.status === 'draft'"
                                    @click="startTaskFromPRD(scope.row.id)">
                                    生成用例
                                </el-button>
                                <el-button 
                                    type="primary" 
                                    size="mini" 
                                    v-if="scope.row.generated_task_id"
                                    @click="viewTask(scope.row.generated_task_id)">
                                    查看任务
                                </el-button>
                                <el-button 
                                    type="danger" 
                                    size="mini" 
                                    v-if="scope.row.status === 'draft'"
                                    @click="deletePRD(scope.row.id)">
                                    删除
                                </el-button>
                            </div>
                        </template>
                    </el-table-column>
                </el-table>
                
                <!-- 分页 -->
                <el-pagination
                    v-if="total > pageSize"
                    @current-change="handlePageChange"
                    :current-page="currentPage"
                    :page-size="pageSize"
                    layout="total, prev, pager, next"
                    :total="total"
                    style="margin-top: 20px; text-align: right;">
                </el-pagination>
            </el-card>
        </div>
        
        <!-- 详情视图 -->
        <div v-else-if="currentView === 'detail'" class="prd-detail-view">
            <el-card class="box-card">
                <div slot="header" class="clearfix">
                    <el-button 
                        type="text" 
                        size="small" 
                        @click="backToList">
                        <i class="el-icon-arrow-left"></i> 返回列表
                    </el-button>
                    <span class="section-title" style="margin-left: 10px;">
                        文本需求详情
                    </span>
                </div>
                
                <div v-if="currentPRD" class="prd-detail-content">
                    <!-- 基本信息 -->
                    <div style="background: #fff; border: 1px solid #EBEEF5; border-radius: 4px; overflow: hidden; margin-bottom: 20px;">
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr style="background: #F5F7FA;">
                                <td style="padding: 12px 15px; width: 120px; color: #606266; font-size: 14px; border-bottom: 1px solid #EBEEF5; font-weight: 500;">
                                    需求名称
                                </td>
                                <td style="padding: 12px 15px; color: #303133; font-size: 14px; border-bottom: 1px solid #EBEEF5; border-left: 1px solid #EBEEF5;">
                                    {{ currentPRD.name }}
                                </td>
                                <td style="padding: 12px 15px; width: 100px; color: #606266; font-size: 14px; border-bottom: 1px solid #EBEEF5; border-left: 1px solid #EBEEF5; font-weight: 500;">
                                    状态
                                </td>
                                <td style="padding: 12px 15px; width: 120px; color: #303133; font-size: 14px; border-bottom: 1px solid #EBEEF5; border-left: 1px solid #EBEEF5;">
                                    <el-tag :type="getStatusType(currentPRD)" size="small">
                                        {{ getStatusText(currentPRD) }}
                                    </el-tag>
                                </td>
                            </tr>
                            <tr>
                                <td style="padding: 12px 15px; width: 120px; color: #606266; font-size: 14px; background: #F5F7FA; font-weight: 500;">
                                    创建时间
                                </td>
                                <td style="padding: 12px 15px; color: #303133; font-size: 14px; border-left: 1px solid #EBEEF5;">
                                    {{ formatDateTime(currentPRD.created_at) }}
                                </td>
                                <td style="padding: 12px 15px; width: 100px; color: #606266; font-size: 14px; background: #F5F7FA; border-left: 1px solid #EBEEF5; font-weight: 500;">
                                    更新时间
                                </td>
                                <td style="padding: 12px 15px; width: 120px; color: #303133; font-size: 14px; border-left: 1px solid #EBEEF5;">
                                    {{ formatDateTime(currentPRD.updated_at) }}
                                </td>
                            </tr>
                        </table>
                    </div>
                    
                    <!-- PRD内容 -->
                    <div class="content-section">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <h3 style="margin: 0;">需求内容</h3>
                            <div v-if="!editingContent">
                                <el-button 
                                    type="primary" 
                                    size="small"
                                    @click="startEditContent">
                                    <i class="el-icon-edit"></i> 编辑内容
                                </el-button>
                            </div>
                        </div>
                        <div v-if="!editingContent" class="content-display">
                            <div class="markdown-content" v-html="renderedContent"></div>
                        </div>
                        <div v-else class="content-edit">
                            <el-alert
                                v-if="currentPRD.status !== 'draft'"
                                type="warning"
                                :closable="false"
                                style="margin-bottom: 10px;">
                                <span slot="title">
                                    提醒：此需求状态为「{{ getStatusText(currentPRD) }}」，编辑内容可能会影响关联任务的结果。
                                </span>
                            </el-alert>
                            <el-input 
                                type="textarea" 
                                v-model="editContentForm.content"
                                :rows="20"
                                placeholder="请输入 Markdown 格式的需求内容">
                            </el-input>
                            <div style="margin-top: 10px;">
                                <el-button type="primary" @click="saveContent">
                                    <i class="el-icon-check"></i> 保存
                                </el-button>
                                <el-button @click="cancelEditContent">
                                    取消
                                </el-button>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 操作按钮 -->
                    <div class="action-bar" v-if="currentPRD.status === 'draft'">
                        <el-button 
                            type="success" 
                            size="large"
                            @click="startTaskFromCurrentPRD">
                            <i class="el-icon-video-play"></i> 生成测试用例
                        </el-button>
                        <el-button 
                            type="danger" 
                            size="large"
                            @click="deleteCurrentPRD">
                            <i class="el-icon-delete"></i> 删除需求
                        </el-button>
                    </div>
                    
                    <div class="action-bar" v-else>
                        <el-alert 
                            type="info" 
                            :closable="false"
                            show-icon>
                            <span slot="title">
                                需求状态为 {{ getStatusText(currentPRD) }}，
                                <el-link 
                                    type="primary" 
                                    v-if="currentPRD.generated_task_id"
                                    @click="viewTask(currentPRD.generated_task_id)">
                                    查看关联任务 →
                                </el-link>
                            </span>
                        </el-alert>
                    </div>
                </div>
            </el-card>
        </div>
        
        <!-- 上传对话框 -->
        <el-dialog 
            title="导入文本需求" 
            :visible.sync="showUploadDialog"
            width="600px"
            :append-to-body="true">
            <div class="text-upload-intro">
                上传 Markdown/TXT 文件，或直接粘贴 PRD 内容。系统会先检查需求逻辑，再生成最终 PRD 与测试用例。
            </div>
            <el-form :model="uploadForm" label-width="90px">
                <el-form-item label="文档名称">
                    <el-input 
                        v-model="uploadForm.name" 
                        placeholder="请输入文档名称">
                    </el-input>
                </el-form-item>
                <el-form-item label="选择文件">
                    <input 
                        type="file" 
                        accept=".txt,.md,.markdown,.text,.log"
                        @change="handleFileSelect"
                        ref="fileInput">
                </el-form-item>
                <el-form-item label="或粘贴内容">
                    <el-input 
                        type="textarea" 
                        v-model="uploadForm.content"
                        :rows="10"
                        placeholder="请粘贴需求文档内容，支持纯文本或 Markdown">
                    </el-input>
                </el-form-item>
            </el-form>
            <span slot="footer" class="dialog-footer">
                <el-button @click="showUploadDialog = false">取消</el-button>
                <el-button type="primary" @click="uploadPRD" :loading="uploading">
                    <i class="el-icon-upload"></i> 上传
                </el-button>
            </span>
        </el-dialog>
    </div>
    `,
    
    data() {
        return {
            // 视图控制
            currentView: 'list',  // list/detail
            
            // 列表数据
            prdList: [],
            statusFilter: '',
            total: 0,
            currentPage: 1,
            pageSize: 20,
            loading: false,
            
            // 详情数据
            currentPRD: null,
            editingContent: false,
            editContentForm: {
                content: ''
            },
            
            // 上传对话框
            showUploadDialog: false,
            uploadForm: {
                name: '',
                content: ''
            },
            uploading: false
        };
    },
    
    computed: {
        renderedContent() {
            if (!this.currentPRD || !this.currentPRD.content) {
                return '';
            }
            return safeRenderMarkdown(this.currentPRD.content);
        }
    },
    
    mounted() {
        // 根据传入的 initialView 设置初始视图
        if (this.initialView) {
            this.currentView = this.initialView === 'create' ? 'list' : this.initialView;
            // 如果是 create 模式，自动打开上传对话框
            if (this.initialView === 'create') {
                this.$nextTick(() => {
                    this.showUploadDialog = true;
                });
            }
        }
        // 如果是列表视图，加载列表
        if (this.currentView === 'list') {
            this.loadPRDList();
        }
    },
    
    methods: {
        // ========== 列表操作 ==========
        
        async loadPRDList() {
            this.loading = true;
            try {
                const params = {
                    status: this.statusFilter,
                    limit: this.pageSize,
                    offset: (this.currentPage - 1) * this.pageSize
                };
                
                const response = await axios.get(`${apiBaseUrl}/prds`, { params });
                
                if (response.data.success) {
                    this.prdList = response.data.data.prds;
                    this.total = response.data.data.total;
                } else {
                    this.$message.error('加载文本需求列表失败: ' + response.data.message);
                }
            } catch (error) {
                console.error('加载文本需求列表异常:', error);
                this.$message.error('加载文本需求列表失败');
            } finally {
                this.loading = false;
            }
        },
        
        handlePageChange(page) {
            this.currentPage = page;
            this.loadPRDList();
        },
        
        // ========== 上传 ==========
        
        handleFileSelect(event) {
            const file = event.target.files[0];
            if (!file) return;
            
            // 自动填充文件名
            if (!this.uploadForm.name) {
                this.uploadForm.name = file.name;
            }
            
            // 读取文件内容
            const reader = new FileReader();
            reader.onload = (e) => {
                this.uploadForm.content = e.target.result;
            };
            reader.readAsText(file);
        },
        
        async uploadPRD() {
            if (!this.uploadForm.content) {
                this.$message.warning('请选择文件或粘贴内容');
                return;
            }
            
            if (!this.uploadForm.name) {
                this.uploadForm.name = `Spec_${new Date().getTime()}.md`;
            }
            
            this.uploading = true;
            try {
                const response = await axios.post(`${apiBaseUrl}/prds/upload`, {
                    name: this.uploadForm.name,
                    content: this.uploadForm.content
                });
                
                if (response.data.success) {
                    this.$message.success('上传成功');
                    this.showUploadDialog = false;
                    
                    // 重置表单
                    this.uploadForm = { name: '', content: '' };
                    this.$refs.fileInput.value = '';
                    
                    // 刷新列表并跳转到详情
                    await this.loadPRDList();
                    this.viewPRDDetail(response.data.data.prd_id);
                } else {
                    this.$message.error('上传失败: ' + response.data.message);
                }
            } catch (error) {
                console.error('导入文本需求异常:', error);
                this.$message.error('上传失败');
            } finally {
                this.uploading = false;
            }
        },
        
        // ========== 详情操作 ==========
        
        async viewPRDDetail(prd_id) {
            this.loading = true;
            try {
                const response = await axios.get(`${apiBaseUrl}/prds/${prd_id}`);
                
                if (response.data.success) {
                    this.currentPRD = response.data.data.prd;
                    
                    // 切换到详情视图
                    this.currentView = 'detail';
                } else {
                    this.$message.error('加载文本需求详情失败: ' + response.data.message);
                }
            } catch (error) {
                console.error('加载文本需求详情异常:', error);
                this.$message.error('加载文本需求详情失败');
            } finally {
                this.loading = false;
            }
        },
        
        backToList() {
            // 先触发事件通知父组件（用于从统一任务管理返回）
            this.$emit('back-to-parent');
            
            // 组件内部视图切换（用于组件独立使用时）
            this.currentView = 'list';
            this.currentPRD = null;
            this.editingContent = false;
            this.loadPRDList();
        },
        
        // ========== 内容编辑 ==========
        
        startEditContent() {
            this.editContentForm.content = this.currentPRD.content;
            this.editingContent = true;
        },
        
        cancelEditContent() {
            this.editingContent = false;
        },
        
        async saveContent() {
            try {
                // 如果不是草稿状态，显示二次确认
                if (this.currentPRD.status !== 'draft') {
                    const confirmResult = await this.$confirm(
                        '此需求已关联任务，修改内容可能会影响任务结果。确认保存？',
                        '确认保存',
                        {
                            confirmButtonText: '确认保存',
                            cancelButtonText: '取消',
                            type: 'warning'
                        }
                    ).catch(() => false);
                    
                    if (!confirmResult) return;
                }
                
                const response = await axios.put(
                    `${apiBaseUrl}/prds/${this.currentPRD.id}`,
                    { content: this.editContentForm.content }
                );
                
                if (response.data.success) {
                    this.$message.success('内容保存成功');
                    this.currentPRD.content = this.editContentForm.content;
                    this.editingContent = false;
                } else {
                    this.$message.error('保存内容失败: ' + response.data.message);
                }
            } catch (error) {
                if (error !== false) {  // 不是用户取消
                    console.error('保存内容异常:', error);
                    this.$message.error('保存内容失败');
                }
            }
        },
        
        // ========== 任务启动 ==========
        
        async startTaskFromCurrentPRD() {
            this.startTaskFromPRD(this.currentPRD.id);
        },
        
        async startTaskFromPRD(prd_id) {
            try {
                // 先获取最新的需求数据，确认需求存在且可启动。
                const prdResponse = await axios.get(`${apiBaseUrl}/prds/${prd_id}`);
                if (!prdResponse.data.success) {
                    this.$message.error('无法获取需求信息');
                    return;
                }
                
                const prd = (prdResponse.data.data && prdResponse.data.data.prd) || prdResponse.data.prd;
                if (!prd) {
                    this.$message.error('无法获取需求信息');
                    return;
                }
                
                // 确认对话框
                const confirmResult = await this.$confirm(
                    '将基于当前需求生成测试用例，确认继续？',
                    '确认生成',
                    {
                        confirmButtonText: '确认生成',
                        cancelButtonText: '取消',
                        type: 'info'
                    }
                ).catch(() => false);
                
                if (!confirmResult) return;
                
                // 启动任务
                const response = await axios.post(`${apiBaseUrl}/prds/${prd_id}/start-task`, {});
                
                if (response.data.success) {
                    this.$message.success(response.data.message);
                    
                    // 跳转到任务详情
                    this.viewTask(response.data.data.task_id);
                } else {
                    this.$message.error('启动任务失败: ' + response.data.message);
                }
            } catch (error) {
                if (error !== false) {  // 不是用户取消
                    console.error('启动任务异常:', error);
                    this.$message.error('启动任务失败');
                }
            }
        },
        
        viewTask(task_id) {
            // 触发父组件的事件，切换到任务详情Tab
            this.$root.$emit('view-task-detail', task_id);
        },
        
        // ========== 删除 ==========
        
        async deleteCurrentPRD() {
            this.deletePRD(this.currentPRD.id, true);
        },
        
        async deletePRD(prd_id, isFromDetail = false) {
            try {
                const confirmResult = await this.$confirm(
                    '确认删除该文本需求？删除后无法恢复。',
                    '确认删除',
                    {
                        confirmButtonText: '确认删除',
                        cancelButtonText: '取消',
                        type: 'warning'
                    }
                ).catch(() => false);
                
                if (!confirmResult) return;
                
                const response = await axios.delete(`${apiBaseUrl}/prds/${prd_id}`);
                
                if (response.data.success) {
                    this.$message.success('删除成功');
                    
                    if (isFromDetail) {
                        // 从详情页删除，返回列表
                        this.backToList();
                    } else {
                        // 从列表删除，刷新列表
                        this.loadPRDList();
                    }
                } else {
                    this.$message.error('删除失败: ' + response.data.message);
                }
            } catch (error) {
                if (error !== false) {
                    console.error('删除文本需求异常:', error);
                    this.$message.error('删除失败');
                }
            }
        },
        
        // ========== 工具方法 ==========
        
        /**
         * 获取实际显示状态（优先使用Task状态）
         */
        getActualStatus(prd) {
            // 如果有Task状态，优先使用Task状态
            if (prd.task_status) {
                return prd.task_status;
            }
            // 否则使用PRD状态
            return prd.status;
        },
        
        getStatusType(statusOrPrd) {
            // 兼容传入status字符串或prd对象
            const status = typeof statusOrPrd === 'string' 
                ? statusOrPrd 
                : this.getActualStatus(statusOrPrd);
            
            const typeMap = {
                'draft': 'info',
                'created': 'info',
                'processing': 'warning',
                'running': 'warning',
                'analyzing': 'warning',
                'collaborating': 'warning',
                'waiting_confirmation': 'warning',
                'completed': 'success',
                'failed': 'danger',
                'cancelled': 'info'
            };
            return typeMap[status] || 'info';
        },
        
        getStatusText(statusOrPrd) {
            // 兼容传入status字符串或prd对象
            const status = typeof statusOrPrd === 'string' 
                ? statusOrPrd 
                : this.getActualStatus(statusOrPrd);
            
            const textMap = {
                'draft': '草稿',
                'created': '🎯 待启动',
                'processing': '运行中',
                'running': '运行中',
                'analyzing': '🔍 分析中',
                'collaborating': '🤝 协作中',
                'waiting_confirmation': '✋ 等待确认',
                'completed': '已完成',
                'failed': '失败',
                'cancelled': '🚫 已取消'
            };
            return textMap[status] || status;
        },
        
        formatDateTime(dateTimeStr) {
            if (!dateTimeStr) return '-';
            try {
                const date = new Date(dateTimeStr);
                return date.toLocaleString('zh-CN', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                });
            } catch (e) {
                return dateTimeStr;
            }
        }
    }
});
