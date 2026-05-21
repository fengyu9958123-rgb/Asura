/**
 * 工作台（Dashboard）Vue组件
 * 根据 UI_REDESIGN_PLAN_A.md 设计文档实现
 */

Vue.component('dashboard-component', {
    template: `
    <div class="dashboard-container">
        <!-- 顶部统计卡片 -->
        <el-row :gutter="20" class="stats-row">
            <el-col :span="6">
                <el-card class="stat-card" shadow="hover">
                    <div class="stat-content">
                        <i class="el-icon-document stat-icon" style="color: #409EFF;"></i>
                        <div class="stat-info">
                            <p class="stat-label">总任务数</p>
                            <p class="stat-value">{{ stats.total_tasks }}</p>
                        </div>
                    </div>
                </el-card>
            </el-col>
            
            <el-col :span="6">
                <el-card class="stat-card" shadow="hover">
                    <div class="stat-content">
                        <i class="el-icon-loading stat-icon" style="color: #67C23A;"></i>
                        <div class="stat-info">
                            <p class="stat-label">运行中</p>
                            <p class="stat-value">{{ stats.processing_tasks }}</p>
                        </div>
                    </div>
                </el-card>
            </el-col>
            
            <el-col :span="6">
                <el-card class="stat-card" shadow="hover">
                    <div class="stat-content">
                        <i class="el-icon-warning stat-icon" style="color: #E6A23C;"></i>
                        <div class="stat-info">
                            <p class="stat-label">等待确认</p>
                            <p class="stat-value" style="color: #E6A23C;">
                                {{ stats.waiting_confirmation }}
                            </p>
                        </div>
                    </div>
                </el-card>
            </el-col>
            
            <el-col :span="6">
                <el-card class="stat-card" shadow="hover">
                    <div class="stat-content">
                        <i class="el-icon-success stat-icon" style="color: #00D4AA;"></i>
                        <div class="stat-info">
                            <p class="stat-label">今日完成</p>
                            <p class="stat-value" style="color: #00D4AA;">
                                {{ stats.completed_today }}
                            </p>
                        </div>
                    </div>
                </el-card>
            </el-col>
        </el-row>
        
        <!-- 快速入口 -->
        <el-row :gutter="20" class="quick-actions-row">
            <el-col :span="12">
                <el-card class="action-card" shadow="hover" @click.native="createImageTask">
                    <div class="action-content">
                        <i class="el-icon-picture action-icon" style="color: #00D4AA;"></i>
                        <div class="action-info">
                            <h3>📸 新建图片需求任务</h3>
                            <p>上传产品原型图、UI设计图等</p>
                        </div>
                        <i class="el-icon-arrow-right"></i>
                    </div>
                </el-card>
            </el-col>
            
            <el-col :span="12">
                <el-card class="action-card" shadow="hover" @click.native="createTextTask">
                    <div class="action-content">
                        <i class="el-icon-document action-icon" style="color: #409EFF;"></i>
                        <div class="action-info">
                            <h3>📄 新建文本PRD任务</h3>
                            <p>上传文本格式的PRD文档</p>
                        </div>
                        <i class="el-icon-arrow-right"></i>
                    </div>
                </el-card>
            </el-col>
        </el-row>
        
        <!-- 最近任务 -->
        <el-card class="recent-tasks-card" shadow="hover">
            <div slot="header" class="clearfix">
                <span style="font-size: 16px; font-weight: 600;">📋 最近任务</span>
                <el-button 
                    style="float: right; padding: 8px 15px;" 
                    type="text" 
                    @click="viewAllTasks"
                >
                    查看全部 <i class="el-icon-arrow-right"></i>
                </el-button>
            </div>
            
            <div v-loading="loading" element-loading-text="加载中...">
                <el-empty v-if="!loading && recentTasks.length === 0" description="暂无任务"></el-empty>
                
                <div v-else class="recent-tasks-list">
                    <div 
                        v-for="task in recentTasks" 
                        :key="task.id"
                        class="task-item"
                        @click="viewTaskDetail(task)"
                    >
                        <div class="task-info">
                            <div class="task-header">
                                <el-tag 
                                    :type="getTaskTypeColor(task.type)" 
                                    size="mini"
                                >
                                    {{ task.type === 'image' ? '图片需求' : '文本PRD' }}
                                </el-tag>
                                <span class="task-name">{{ task.name }}</span>
                            </div>
                            <div class="task-meta">
                                <el-tag :type="getStatusTagType(task.status_group)" size="small">
                                    {{ task.status_display }}
                                </el-tag>
                                <span class="task-time">
                                    {{ formatTime(task.updated_at) }}
                                </span>
                            </div>
                        </div>
                        <i class="el-icon-arrow-right"></i>
                    </div>
                </div>
            </div>
        </el-card>
    </div>
    `,
    
    data() {
        return {
            loading: false,
            stats: {
                total_tasks: 0,
                processing_tasks: 0,
                waiting_confirmation: 0,
                completed_today: 0
            },
            recentTasks: []
        };
    },
    
    created() {
        this.fetchDashboardStats();
    },
    
    methods: {
        /**
         * 获取工作台统计数据
         */
        async fetchDashboardStats() {
            this.loading = true;
            try {
                const response = await axios.get('/api/tasks/unified/dashboard');
                
                if (response.data.success) {
                    // 数据包装在 response.data.data 中
                    const data = response.data.data;
                    this.stats = {
                        total_tasks: data.total_tasks || 0,
                        processing_tasks: data.processing_tasks || 0,
                        waiting_confirmation: data.waiting_confirmation || 0,
                        completed_today: data.completed_today || 0
                    };
                    this.recentTasks = data.recent_tasks || [];
                    
                    console.log('工作台统计数据加载成功:', data);
                } else {
                    this.$message.error('加载工作台数据失败: ' + response.data.message);
                }
            } catch (error) {
                console.error('获取工作台统计数据失败:', error);
                this.$message.error('加载工作台数据失败');
            } finally {
                this.loading = false;
            }
        },
        
        /**
         * 创建图片需求任务
         */
        createImageTask() {
            this.$emit('navigate', 'createImageRequirement');
        },
        
        /**
         * 创建文本PRD任务
         */
        createTextTask() {
            this.$emit('navigate', 'createTextPRD');
        },
        
        /**
         * 查看所有任务
         */
        viewAllTasks() {
            this.$emit('navigate', 'taskList');
        },
        
        /**
         * 查看任务详情
         */
        viewTaskDetail(task) {
            if (task.task_id) {
                this.$emit('view-task-detail', task.task_id);
                return;
            }

            if (task.type === 'image') {
                // 图片需求任务详情
                this.$emit('view-image-task', task.id);
            } else {
                // 文本PRD任务详情
                this.$emit('view-text-task', task.id);
            }
        },
        
        /**
         * 获取任务类型颜色
         */
        getTaskTypeColor(type) {
            return type === 'image' ? '' : 'info';
        },
        
        /**
         * 获取状态标签类型
         */
        getStatusTagType(statusGroup) {
            const mapping = {
                'draft': 'info',
                'pending': 'primary',
                'processing': 'success',
                'waiting': 'warning',
                'completed': 'success',
                'failed': 'danger'
            };
            return mapping[statusGroup] || 'info';
        },
        
        /**
         * 格式化时间
         */
        formatTime(timeStr) {
            if (!timeStr) return '';
            
            const date = new Date(timeStr);
            const now = new Date();
            const diff = now - date;
            
            // 小于1分钟
            if (diff < 60 * 1000) {
                return '刚刚';
            }
            // 小于1小时
            if (diff < 60 * 60 * 1000) {
                return Math.floor(diff / (60 * 1000)) + '分钟前';
            }
            // 小于24小时
            if (diff < 24 * 60 * 60 * 1000) {
                return Math.floor(diff / (60 * 60 * 1000)) + '小时前';
            }
            // 小于7天
            if (diff < 7 * 24 * 60 * 60 * 1000) {
                return Math.floor(diff / (24 * 60 * 60 * 1000)) + '天前';
            }
            
            // 超过7天，显示具体日期
            return date.toLocaleDateString('zh-CN', {
                month: 'short',
                day: 'numeric'
            });
        }
    }
});
