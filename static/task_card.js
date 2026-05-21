/**
 * 任务卡片组件
 * 可复用的任务卡片，用于任务列表和工作台
 * 方案A：主按钮 + 下拉菜单
 */

Vue.component('task-card', {
    props: ['task'],
    template: `
    <el-card 
        class="task-card" 
        :class="'status-' + task.status_group"
        shadow="hover"
        @click.native="$emit('view', task)"
    >
        <div class="task-card-header">
            <div class="task-title-row">
                <h3 class="task-title">{{ task.name }}</h3>
            </div>
            
            <el-tag 
                :type="getStatusTagType()"
                size="small"
            >
                {{ cleanStatusText(task.status_display) }}
            </el-tag>
        </div>
        
        <div class="task-card-content">
            <!-- 内容摘要 -->
            <div class="task-summary">
                <!-- 任务类型 -->
                <span class="task-type-badge">
                    <i :class="task.type === 'image' ? 'el-icon-picture-outline' : 'el-icon-document'"></i>
                    {{ task.type === 'image' ? '图片需求' : '文本需求' }}
                </span>
                
                <!-- 图片数量（仅图片类型） -->
                <span v-if="task.type === 'image'" class="task-info-item">
                    <i class="el-icon-picture-outline"></i>
                    {{ task.content.image_count }} 张图片
                </span>
                
            </div>
            
            <!-- 进度条（运行中状态显示） -->
            <div v-if="task.status_group === 'processing'" class="task-progress">
                <el-progress
                    :percentage="task.progress || task.completion_percentage || 0"
                    :stroke-width="6"
                    :color="getProgressColor()"
                ></el-progress>
            </div>
            
            <!-- 等待确认提示 -->
            <div v-if="task.status_group === 'waiting'" class="task-confirmation">
                <i class="el-icon-warning"></i>
                <span>有 {{ task.confirmation_count }} 个问题等待您确认</span>
            </div>
            
            <!-- 时间信息 -->
            <div class="task-time">
                <span><i class="el-icon-time"></i> {{ formatTime(task.updated_at) }}</span>
            </div>
        </div>
        
        <div class="task-card-footer" @click.stop>
            <!-- 方案A：主按钮 + 下拉菜单 -->
            <div class="task-actions">
                <!-- 主操作按钮（1-2个） -->
                <div class="primary-actions">
                    <!-- 已完成/失败：查看结果 -->
                    <el-button 
                        v-if="task.status_group === 'completed' || task.status_group === 'failed'"
                        size="small"
                        type="success"
                        icon="el-icon-document"
                        @click="$emit('view-result', task)"
                    >
                        查看结果
                    </el-button>
                    
                    <!-- 运行中/等待确认：查看进度 -->
                    <el-button 
                        v-if="task.status_group === 'processing' || task.status_group === 'waiting'"
                        size="small"
                        type="success"
                        icon="el-icon-data-line"
                        @click="$emit('view-progress', task)"
                    >
                        查看进度
                    </el-button>
                    
                    <!-- 等待确认：立即确认 -->
                    <el-button 
                        v-if="task.status_group === 'waiting'"
                        size="small"
                        type="warning"
                        icon="el-icon-warning"
                        @click="$emit('confirm', task)"
                    >
                        立即确认
                    </el-button>
                    
                    <!-- 草稿/待启动：启动按钮 -->
                    <el-button 
                        v-if="task.can_start && (task.status_group === 'draft' || task.status_group === 'pending')"
                        size="small"
                        type="primary"
                        icon="el-icon-video-play"
                        @click="$emit('start', task)"
                    >
                        启动
                    </el-button>
                </div>
                
                <!-- 更多操作（下拉菜单） -->
                <el-dropdown trigger="click" @command="handleCommand">
                    <el-button size="small" icon="el-icon-more">
                        更多
                    </el-button>
                    <el-dropdown-menu slot="dropdown">
                        <!-- 编辑 -->
                        <el-dropdown-item 
                            v-if="task.can_edit"
                            command="edit"
                            icon="el-icon-edit"
                        >
                            编辑
                        </el-dropdown-item>
                        
                        <!-- 历史记录（运行过至少一次才显示） -->
                        <el-dropdown-item 
                            v-if="task.history_count > 0"
                            command="history"
                            icon="el-icon-time"
                        >
                            历史记录 ({{ task.history_count }}次)
                        </el-dropdown-item>
                        
                        <!-- 重新生成（已完成的任务） -->
                        <el-dropdown-item 
                            v-if="task.status_group === 'completed' && task.can_start"
                            command="regenerate"
                            icon="el-icon-refresh"
                        >
                            重新生成
                        </el-dropdown-item>
                        
                        <!-- 重新运行（失败的任务） -->
                        <el-dropdown-item 
                            v-if="task.status_group === 'failed'"
                            command="retry"
                            icon="el-icon-refresh-right"
                        >
                            重新运行
                        </el-dropdown-item>
                        
                        <!-- 删除 -->
                        <el-dropdown-item 
                            v-if="task.can_delete"
                            command="delete"
                            icon="el-icon-delete"
                            divided
                        >
                            删除
                        </el-dropdown-item>
                    </el-dropdown-menu>
                </el-dropdown>
            </div>
        </div>
    </el-card>
    `,
    
    methods: {
        getTaskTypeColor() {
            return this.task.type === 'image' ? '' : 'info';
        },
        
        getStatusTagType() {
            const mapping = {
                'draft': 'info',
                'pending': 'primary',
                'processing': 'success',
                'waiting': 'warning',
                'completed': 'success',
                'failed': 'danger'
            };
            return mapping[this.task.status_group] || 'info';
        },

        cleanStatusText(text) {
            return (text || '')
                .replace(/[✅❌⚙️📝✋🚫]/g, '')
                .replace(/\s+/g, ' ')
                .trim();
        },
        
        getProgressColor() {
            const progress = this.task.completion_percentage || this.task.progress || 0;
            if (progress >= 75) return '#67C23A';
            if (progress >= 50) return '#409EFF';
            if (progress >= 25) return '#E6A23C';
            return '#F56C6C';
        },
        
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
                year: 'numeric',
                month: 'short',
                day: 'numeric'
            });
        },
        
        /**
         * 处理下拉菜单命令
         */
        handleCommand(command) {
            switch (command) {
                case 'edit':
                    this.$emit('edit', this.task);
                    break;
                case 'history':
                    this.$emit('view-history', this.task);
                    break;
                case 'regenerate':
                    this.$emit('start', this.task);
                    break;
                case 'retry':
                    this.$emit('retry', this.task);
                    break;
                case 'delete':
                    this.$emit('delete', this.task);
                    break;
            }
        }
    }
});
