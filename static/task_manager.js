/**
 * 统一任务管理Vue组件
 * 根据 UI_REDESIGN_PLAN_A.md 设计文档实现
 */

Vue.component('task-manager-component', {
    template: `
    <div class="task-manager-container">
        <!-- 统计信息 -->
        <div class="stats-bar" v-if="groupCounts">
            <span class="stat-item">
                总数: <strong>{{ total }}</strong>
            </span>
            <span class="stat-item">
                草稿: <strong>{{ groupCounts.draft }}</strong>
            </span>
            <span class="stat-item">
                进行中: <strong>{{ groupCounts.processing }}</strong>
            </span>
            <span class="stat-item" :class="{ 'highlight-warning': groupCounts.waiting > 0 }">
                等待确认: <strong>{{ groupCounts.waiting }}</strong>
            </span>
            <span class="stat-item">
                已完成: <strong>{{ groupCounts.completed }}</strong>
            </span>
            <span class="stat-item">
                失败: <strong>{{ groupCounts.failed }}</strong>
            </span>
        </div>
        
        <!-- 任务列表 -->
        <div v-loading="loading" element-loading-text="加载中...">
            <el-empty v-if="!loading && tasks.length === 0" description="暂无任务" style="padding: 60px 0;"></el-empty>
            
            <div v-else class="tasks-grid">
                <task-card 
                    v-for="task in tasks" 
                    :key="task.id"
                    :task="task"
                    @view="viewTask"
                    @edit="editTask"
                    @start="startTask"
                    @retry="retryTask"
                    @delete="deleteTask"
                    @cancel="cancelTask"
                    @confirm="confirmTask"
                    @view-progress="viewTaskProgress"
                    @view-result="viewTaskResult"
                    @view-history="viewTaskHistory"
                ></task-card>
            </div>
        </div>
        
        <!-- 分页 -->
        <div class="pagination-container" v-if="total > 0">
            <el-pagination
                background
                layout="total, sizes, prev, pager, next, jumper"
                :current-page="pagination.page"
                :page-sizes="[6, 12, 18, 24]"
                :page-size="pagination.pageSize"
                :total="total"
                @size-change="handleSizeChange"
                @current-change="handlePageChange"
            ></el-pagination>
        </div>
        
        <!-- 图片流程进度对话框 -->
        <image-pipeline-progress
            :visible.sync="imagePipelineProgressVisible"
            :module-id="imagePipelineModuleId"
            @progress-complete="handleProgressComplete"
        ></image-pipeline-progress>
        
        <!-- 历史记录对话框 -->
        <el-dialog
            :title="'运行历史记录 - ' + (currentTask ? currentTask.name : '')"
            :visible.sync="historyDialogVisible"
            width="900px"
            append-to-body
        >
            <div v-loading="historyLoading">
                <el-empty v-if="!historyLoading && historyList.length === 0" description="暂无历史记录"></el-empty>
                
                <el-table 
                    v-else
                    :data="historyList"
                    style="width: 100%"
                >
                    <el-table-column label="运行时间" width="180">
                        <template slot-scope="scope">
                            <i class="el-icon-time"></i>
                            {{ formatDateTime(scope.row.created_at) }}
                        </template>
                    </el-table-column>
                    
                    <el-table-column label="状态" width="140">
                        <template slot-scope="scope">
                            <el-tag :type="getHistoryStatusType(scope.row.status)" size="small">
                                {{ cleanStatusText(scope.row.status_display) }}
                            </el-tag>
                        </template>
                    </el-table-column>
                    
                    <el-table-column label="完成度" width="150">
                        <template slot-scope="scope">
                            <el-progress 
                                :percentage="scope.row.completion_percentage" 
                                :stroke-width="8"
                                :show-text="false"
                            ></el-progress>
                            <span style="margin-left: 10px; font-size: 12px;">{{ scope.row.completion_percentage }}%</span>
                        </template>
                    </el-table-column>
                    
                    <el-table-column label="备注" min-width="120">
                        <template slot-scope="scope">
                            <span style="color: #606266; font-size: 13px;">{{ scope.row.message || '-' }}</span>
                        </template>
                    </el-table-column>
                    
                    <el-table-column label="操作" width="100" fixed="right">
                        <template slot-scope="scope">
                            <el-button
                                type="text"
                                size="small"
                                @click="viewHistoryDetail(scope.row)"
                            >
                                查看详情
                            </el-button>
                        </template>
                    </el-table-column>
                </el-table>
            </div>
            
            <span slot="footer" class="dialog-footer">
                <el-button @click="historyDialogVisible = false">关闭</el-button>
            </span>
        </el-dialog>
    </div>
    `,
    
    data() {
        return {
            loading: false,
            filters: {
                keyword: ''
            },
            pagination: {
                page: 1,
                pageSize: 6
            },
            tasks: [],
            total: 0,
            groupCounts: null,
            pollingInterval: null,  // 轮询定时器
            
            // 图片流程进度
            imagePipelineProgressVisible: false,
            imagePipelineModuleId: '',
            
            // 历史记录对话框
            historyDialogVisible: false,
            historyLoading: false,
            historyList: [],
            currentTask: null  // 当前查看历史的任务
        };
    },
    
    created() {
        this.fetchTasks();
    },
    
    mounted() {
        // 启动定时刷新（每5秒检查一次）
        this.startPolling();
    },
    
    beforeDestroy() {
        // 清除定时器
        this.stopPolling();
    },
    
    methods: {
        /**
         * 获取任务列表
         */
        async fetchTasks() {
            this.loading = true;
            try {
                const params = {
                    keyword: this.filters.keyword || undefined,
                    page: this.pagination.page,
                    page_size: this.pagination.pageSize
                };
                
                const response = await axios.get('/api/tasks/unified', { params });
                
                if (response.data.success) {
                    // 数据包装在 response.data.data 中
                    const data = response.data.data;
                    this.tasks = data.tasks || [];
                    this.total = data.total || 0;
                    this.groupCounts = data.group_counts || {};
                    
                    console.log('任务列表加载成功:', data);
                    
                    // 检查是否有活跃任务（运行中或等待确认）
                    this.checkActiveTasksAndPolling();
                } else {
                    this.$message.error('加载任务列表失败: ' + response.data.message);
                }
            } catch (error) {
                console.error('获取任务列表失败:', error);
                this.$message.error('加载任务列表失败');
            } finally {
                this.loading = false;
            }
        },
        
        /**
         * 分页大小改变
         */
        handleSizeChange(newSize) {
            this.pagination.pageSize = newSize;
            this.pagination.page = 1;
            this.fetchTasks();
        },
        
        /**
         * 页码改变
         */
        handlePageChange(newPage) {
            this.pagination.page = newPage;
            this.fetchTasks();
        },
        
        /**
         * 查看任务详情
         */
        viewTask(task) {
            if (task.task_id) {
                this.$emit('view-task-detail', task.task_id);
                return;
            }

            if (task.type === 'image') {
                this.$emit('view-image-task', task.id);
            } else {
                this.$emit('view-text-task', task.id);
            }
        },
        
        /**
         * 编辑任务
         */
        editTask(task) {
            if (task.type === 'image') {
                this.$emit('edit-image-task', task.id);
            } else {
                this.$emit('edit-text-task', task.id);
            }
        },
        
        /**
         * 启动任务
         */
        async startTask(task) {
            try {
                // 确认对话框
                await this.$confirm('确定要启动该任务吗？启动后将无法编辑。', '确认启动', {
                    confirmButtonText: '确定',
                    cancelButtonText: '取消',
                    type: 'warning'
                });
                
                // 根据任务类型调用不同的API
                let response;
                if (task.type === 'image') {
                    // 图片需求任务 - 启动图片流程
                    response = await axios.post('/api/image-pipeline/start', {
                        module_id: task.source_id
                    });
                } else {
                    // 文本PRD任务
                    response = await axios.post(`/api/prds/${task.source_id}/start-task`);
                }
                
                if (response.data.success) {
                    this.$message.success('任务启动成功');
                    this.fetchTasks();
                } else {
                    this.$message.error('启动任务失败: ' + (response.data.error || response.data.message));
                }
            } catch (error) {
                                                if (error !== 'cancel') {
                    console.error('启动任务失败:', error);
                    const errorMessage = error.response?.data?.error || '启动失败，请检查网络或联系管理员。';
                    this.$message.error(errorMessage);
                }
            }
        },
        
        /**
         * 重新运行失败任务
         */
        async retryTask(task) {
            try {
                // 确认对话框
                await this.$confirm(`确定要重新运行任务 "${task.name}" 吗？`, '重新运行', {
                    confirmButtonText: '确定',
                    cancelButtonText: '取消',
                    type: 'warning'
                });
                
                // 根据任务类型调用不同的API
                let response;
                if (task.type === 'image') {
                    // 图片需求任务 - 重新启动图片流程
                    response = await axios.post('/api/image-pipeline/start', {
                        module_id: task.source_id
                    });
                    
                    if (response.data.success) {
                        this.$message.success('任务已重新启动');
                        this.fetchTasks();
                    } else {
                        this.$message.error('重新运行失败: ' + (response.data.error || response.data.message));
                    }
                } else {
                    // 文本PRD任务
                    response = await axios.post(`/api/prds/${task.source_id}/start-task`);
                    
                    if (response.data.success) {
                        this.$message.success('任务已重新启动');
                        this.fetchTasks();
                    } else {
                        this.$message.error('重新运行失败: ' + response.data.message);
                    }
                }
            } catch (error) {
                if (error !== 'cancel') {
                    console.error('重新运行任务失败:', error);
                    const errorMessage = error.response?.data?.error || '重新运行失败，请检查网络或联系管理员。';
                    this.$message.error(errorMessage);
                }
            }
        },
        
        /**
         * 删除任务
         */
        async deleteTask(task) {
            try {
                await this.$confirm('确定要删除该任务吗？此操作不可恢复。', '确认删除', {
                    confirmButtonText: '确定',
                    cancelButtonText: '取消',
                    type: 'danger'
                });

                // 根据来源类型调用不同的API
                let response;
                if (task.source_type === 'requirement_module') {
                    // 图片需求：删除RequirementModule
                    response = await axios.delete(`/api/requirement-modules/${task.source_id}`);
                } else if (task.source_type === 'prd') {
                    // 文本需求（新架构）：删除PRD
                    response = await axios.delete(`/api/prds/${task.source_id}`);
                } else if (task.source_type === 'task') {
                    // 文本需求（旧架构）：删除Task
                    response = await axios.delete(`/api/tasks/${task.source_id}`);
                } else {
                    this.$message.error('未知的任务类型');
                    return;
                }

                if (response.data.success) {
                    this.$message.success('删除成功');
                    this.fetchTasks();
                } else {
                    this.$message.error('删除失败: ' + response.data.message);
                }
            } catch (error) {
                if (error !== 'cancel') {
                    console.error('删除任务失败:', error);
                    this.$message.error('删除失败');
                }
            }
        },
        
        /**
         * 取消任务
         */
        async cancelTask(task) {
            try {
                await this.$confirm('确定要取消该任务吗？', '确认取消', {
                    confirmButtonText: '确定',
                    cancelButtonText: '取消',
                    type: 'warning'
                });
                
                // 取消任务需要调用generation service的API
                const response = await axios.post(`/api/generation/${task.task_id}/cancel`);
                
                if (response.data.success) {
                    this.$message.success('任务已取消');
                    this.fetchTasks();
                } else {
                    this.$message.error('取消任务失败: ' + response.data.message);
                }
            } catch (error) {
                if (error !== 'cancel') {
                    console.error('取消任务失败:', error);
                    this.$message.error('取消任务失败');
                }
            }
        },
        
        /**
         * 立即确认（跳转到Task运行详情页）
         */
        confirmTask(task) {
            // 跳转到Task的运行详情页（显示人工确认界面）
            if (task.task_id) {
                this.$emit('view-task-detail', task.task_id);
            } else {
                this.$message.warning('该任务尚未启动');
            }
        },
        
        /**
         * 查看任务进度
         */
        viewTaskProgress(task) {
            if (!task.task_id) {
                this.$message.warning('该任务尚未启动');
                return;
            }
            
            // 统一跳转到任务详情页（不区分图片/文本）
            this.$emit('view-task-detail', task.task_id);
        },
        
        /**
         * 查看任务结果（跳转到Task运行详情页）
         */
        viewTaskResult(task) {
            // 跳转到Task的运行详情页（显示运行结果）
            if (task.task_id) {
                this.$emit('view-task-detail', task.task_id);
            } else {
                this.$message.warning('该任务尚无运行记录');
            }
        },
        
        /**
         * 检查是否有活跃任务，决定是否需要轮询
         */
        checkActiveTasksAndPolling() {
            // 检查是否有运行中或等待确认的任务
            const hasActiveTask = this.tasks.some(task => 
                task.status_group === 'processing' || task.status_group === 'waiting'
            );
            
            // 如果有活跃任务但轮询未启动，则启动轮询
            // 如果没有活跃任务但轮询已启动，则停止轮询
            if (hasActiveTask && !this.pollingInterval) {
                console.log('检测到活跃任务，启动自动刷新');
                this.startPolling();
            } else if (!hasActiveTask && this.pollingInterval) {
                console.log('无活跃任务，停止自动刷新');
                this.stopPolling();
            }
        },
        
        /**
         * 启动轮询
         */
        startPolling() {
            if (this.pollingInterval) return;
            
            // 每5秒刷新一次任务列表
            this.pollingInterval = setInterval(() => {
                console.log('自动刷新任务列表...');
                this.fetchTasks();
            }, 5000);
        },
        
        /**
         * 停止轮询
         */
        stopPolling() {
            if (this.pollingInterval) {
                clearInterval(this.pollingInterval);
                this.pollingInterval = null;
                console.log('已停止自动刷新');
            }
        },
        
        /**
         * 查看任务历史记录
         */
        async viewTaskHistory(task) {
            this.currentTask = task;
            this.historyDialogVisible = true;
            this.historyLoading = true;
            
            try {
                const response = await axios.get(`${apiBaseUrl}/tasks/unified/${task.id}/history`, {
                    params: {
                        type: task.type
                    }
                });
                
                if (response.data.success) {
                    this.historyList = response.data.data.history || [];
                    console.log('历史记录加载成功:', this.historyList);
                } else {
                    this.$message.error('加载历史记录失败: ' + response.data.message);
                }
            } catch (error) {
                console.error('加载历史记录异常:', error);
                this.$message.error('加载历史记录失败');
            } finally {
                this.historyLoading = false;
            }
        },
        
        /**
         * 查看历史记录详情
         */
        viewHistoryDetail(historyItem) {
            // 关闭历史记录对话框
            this.historyDialogVisible = false;
            
            // 跳转到Task详情页
            this.$emit('view-task-detail', historyItem.task_id);
        },
        
        /**
         * 格式化日期时间
         */
        formatDateTime(dateTimeStr) {
            if (!dateTimeStr) return '-';
            
            const date = new Date(dateTimeStr);
            return date.toLocaleString('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false
            });
        },
        
        /**
         * 获取历史记录状态类型
         */
        getHistoryStatusType(status) {
            const typeMap = {
                'created': 'info',
                'running': 'warning',
                'analyzing': 'warning',
                'collaborating': 'warning',
                'processing': 'warning',
                'waiting_confirmation': 'warning',
                'completed': 'success',
                'failed': 'danger',
                'cancelled': 'info'
            };
            return typeMap[status] || 'info';
        },

        cleanStatusText(text) {
            return (text || '')
                .replace(/[✅❌⚙️📝✋🚫]/g, '')
                .replace(/\s+/g, ' ')
                .trim();
        },
        
        /**
         * 处理图片流程完成
         */
        handleProgressComplete(status) {
            console.log('图片流程完成:', status);
            // 刷新任务列表
            this.fetchTasks();
        }
    }
});
