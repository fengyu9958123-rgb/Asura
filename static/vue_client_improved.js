// Vue Client Improved JavaScript
// 定义API基础路径
const apiBaseUrl = window.location.origin + '/api';

// 确保marked库可用的函数
function initializeMarked() {
    if (typeof marked !== 'undefined') {
        try {
            const renderer = new marked.Renderer();
            renderer.code = function (code, language) {
                return '<pre><code class="' + (language || '') + '">' +
                    (code || '').replace(/</g, '&lt;').replace(/>/g, '&gt;') +
                    '</code></pre>';
            };

            marked.setOptions({
                renderer: renderer,
                highlight: function (code, lang) {
                    return code;
                },
                breaks: true,
                gfm: true
            });

            console.log('Marked库初始化成功');
            return true;
        } catch (e) {
            console.error('Marked库初始化失败:', e);
            return false;
        }
    } else {
        console.warn('Marked库未加载，将在之后尝试重新初始化');
        return false;
    }
}

// 初始尝试初始化marked
let markedInitialized = initializeMarked();

// 安全的Markdown渲染函数
function safeRenderMarkdown(content) {
    if (!content) return '';

    // 如果marked未初始化，再次尝试
    if (!markedInitialized) {
        markedInitialized = initializeMarked();
    }

    if (markedInitialized && typeof marked !== 'undefined') {
        try {
            // 兼容不同版本的marked API
            if (typeof marked.parse === 'function') {
                return marked.parse(content);
            } else if (typeof marked === 'function') {
                return marked(content);
            } else {
                throw new Error('marked API not available');
            }
        } catch (e) {
            console.error('Markdown渲染错误:', e);
            // 如果marked失败，使用简单的文本格式化
            return simpleMarkdownFallback(content);
        }
    } else {
        // 如果marked不可用，使用简单的文本格式化
        console.warn('Marked库不可用，使用简单格式化');
        return simpleMarkdownFallback(content);
    }
}

// 简单的Markdown格式化fallback
function simpleMarkdownFallback(content) {
    if (!content) return '';
    
    // 转义HTML特殊字符
    let html = content
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    
    // 处理基本的Markdown语法
    html = html
        // 标题处理
        .replace(/^### (.*$)/gm, '<h3>$1</h3>')
        .replace(/^## (.*$)/gm, '<h2>$1</h2>')
        .replace(/^# (.*$)/gm, '<h1>$1</h1>')
        
        // 加粗和斜体
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        
        // 代码块
        .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
        .replace(/`(.*?)`/g, '<code>$1</code>')
        
        // 链接
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
        
        // 列表项（简单处理）
        .replace(/^[\s]*[-*+]\s+(.*)$/gm, '<li>$1</li>')
        
        // 换行处理
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br/>');
    
    // 处理列表包装
    html = html.replace(/(<li>.*?<\/li>(\s*<li>.*?<\/li>)*)/gs, function(match) {
        return '<ul>' + match + '</ul>';
    });
    
    // 包装段落
    if (html && !html.startsWith('<h') && !html.startsWith('<ul') && !html.startsWith('<pre')) {
        html = '<p>' + html + '</p>';
    }
    
    return html;
}

function isTaskTerminalStatus(status) {
    const normalized = normalizeTaskStatus(status);
    return ['completed', 'failed', 'cancelled'].includes(normalized);
}

function isTaskActiveStatus(status) {
    const normalized = normalizeTaskStatus(status);
    return ['running', 'processing', 'analyzing', 'collaborating', 'finalizing_prd'].includes(normalized);
}

function isTaskWaitingConfirmationStatus(status) {
    return normalizeTaskStatus(status) === 'waiting_confirmation';
}

function normalizeTaskStatus(status) {
    if (status === null || status === undefined) return '';
    return String(status).toLowerCase().replace(/^taskstatus\./, '');
}

// Vue应用
new Vue({
    el: '#app',
    data: {
        mainTab: 'testcase', // 主要功能Tab，默认为测试用例生成
        activeTab: 'newTask', // 默认显示新建任务页面
        previousTab: null, // 记录上一个Tab，用于返回导航
        taskDetailTab: 'testcaseGeneration',
        isLoading: false,
        tasks: [],
        selectedTask: null,
        currentTaskRequestId: null,
        prdPreview: null,
        finalPrdPreview: null,
        agentChatHistory: [],
        agentMessages: [],
        langgraphView: {
            enabled: false,
            main_nodes: [],
            testcase_nodes: [],
            main_state: {},
            testcase_state: {},
            usage_summary: {},
            output_dir: '',
            message: ''
        },
        langgraphMessageFilter: 'all',
        selectedLanggraphStageKey: '',
        aiCollaborationEnabled: (window.APP_CONFIG && window.APP_CONFIG.showAICollaboration) !== false,
        confirmationItems: [],
        confirmationResponses: {},
        taskResults: [],
        lastPolledTime: 0,
        pollingInterval: null,
        messagePollingTimer: null,
        hasNewTasks: false,
        taskRunning: false,
        previewContent: null,
        previewFileName: '',
        previewType: 'markdown',
        confirmDialogVisible: false,
        confirmMessage: '',
        humanConfirmDialogVisible: false,
        humanConfirmData: { items: [], answers: [] },
        submittedConfirmationResults: [], // 存储已提交的确认结果
        confirmationSubmitted: false, // 标记确认是否已提交，避免DOM突然变化
        expandedMessages: {}, // 存储消息展开状态
        waitingCount: 0, // Phase 1-3: 等待确认的任务数量
        isAIThinking: false, // AI思考状态指示器
        showCollabDrawer: false, // 协作抽屉是否显示
        collabFullScreen: false, // 协作抽屉全屏
        showCuteTimeline: false, // 是否显示第三方时间线组件
        modelSettings: {
            config_path: '',
            updated_at: '',
            model_types: [],
            models: []
        },
        modelSettingsLoading: false,
        modelSettingsSaving: false
    },
    computed: {
        modelTypeOptions() {
            if (this.modelSettings && this.modelSettings.model_types && this.modelSettings.model_types.length > 0) {
                return this.modelSettings.model_types;
            }
            return [
                { type: 'split', label: '需求拆分模型' },
                { type: 'requirement', label: '需求/测试用例模型' },
                { type: 'vision', label: '图片分析模型' }
            ];
        },

        modelStageGuides() {
            return [
                {
                    type: 'vision',
                    label: '视觉分析',
                    level: '推荐 Doubao Seed 2.0 Pro',
                    description: '用于图片、标注、箭头备注和文件名语义提取。'
                },
                {
                    type: 'requirement',
                    label: '需求/测试用例',
                    level: '推荐 DeepSeek V4 Pro',
                    description: '用于 PRD 审查、确认整合、最终 PRD 和测试用例生成，调用量大，优先控制成本。'
                },
                {
                    type: 'split',
                    label: '需求拆分',
                    level: '推荐 GPT-5.5',
                    description: '用于 PRD 分块、LU 拆分和链路识别，是质量要求最高的阶段。'
                }
            ];
        }
    },
    created() {
        this.fetchTasks();

        // 恢复上次选择的任务ID（页面刷新后）
        const lastTaskId = localStorage.getItem('currentTaskId');
        if (lastTaskId) {
            this.fetchTaskDetails(lastTaskId);
        }

        // 监听浏览器关闭事件，清理轮询
        window.addEventListener('beforeunload', this.cleanupPolling);
    },
    mounted() {
        try {
            const lib = window['vue-cute-timeline'] || window.VueCuteTimeline || window['VueCuteTimeline'];
            if (lib) {
                this.showCuteTimeline = true;
            }
        } catch(e) { /* noop */ }
        
        // 监听从文本PRD组件发来的"查看任务"事件
        this.$root.$on('view-task-detail', (taskId) => {
            this.mainTab = 'testcase';  // 切换到测试用例Tab
            setTimeout(() => {
                this.viewTaskDetail({ id: taskId });
            }, 100);
        });
    },
    beforeDestroy() {
        this.cleanupPolling();
    },
    methods: {
        openModelSettings() {
            this.activeTab = 'modelSettings';
            this.fetchModelSettings();
        },

        fetchModelSettings() {
            this.modelSettingsLoading = true;
            axios.get(`${apiBaseUrl}/settings/models`)
                .then(response => {
                    if (response.data && response.data.success) {
                        const payload = response.data.data || {};
                        this.modelSettings = {
                            config_path: payload.config_path || '',
                            updated_at: payload.updated_at || '',
                            model_types: payload.model_types || [],
                            models: (payload.models || []).map(item => ({
                                enabled: item.enabled !== false,
                                api: item.api || '',
                                api_key: item.api_key || '',
                                cached_input_price_per_million: item.cached_input_price_per_million ?? null,
                                currency: item.currency || 'CNY',
                                ...item
                            }))
                        };
                    } else {
                        this.$message.error((response.data && response.data.error) || '获取模型配置失败');
                    }
                })
                .catch(error => {
                    console.error('获取模型配置失败:', error);
                    this.$message.error('获取模型配置失败');
                })
                .finally(() => {
                    this.modelSettingsLoading = false;
                });
        },

        addModelConfig() {
            const preferredOrder = ['split', 'requirement', 'vision'];
            const existingTypes = new Set((this.modelSettings.models || []).map(item => item.model_type));
            const missingType = preferredOrder.find(type => !existingTypes.has(type));
            const type = this.modelTypeOptions.find(item => item.type === missingType)
                || this.modelTypeOptions.find(item => item.type === 'requirement')
                || this.modelTypeOptions[0]
                || { type: 'requirement', label: '需求/测试用例模型' };
            this.modelSettings.models.push({
                id: `new-${Date.now()}`,
                name: type.label,
                model_type: type.type,
                model: '',
                base_url: '',
                api_key: '',
                api_key_masked: '',
                api: '',
                input_price_per_million: null,
                cached_input_price_per_million: null,
                output_price_per_million: null,
                currency: 'CNY',
                pricing_note: '',
                enabled: true
            });
        },

        removeModelConfig(index) {
            this.modelSettings.models.splice(index, 1);
        },

        getModelTypeLabel(modelType) {
            const type = this.modelTypeOptions.find(item => item.type === modelType);
            return type ? type.label : (modelType || '未分类模型');
        },

        saveModelSettings() {
            this.modelSettingsSaving = true;
            axios.put(`${apiBaseUrl}/settings/models`, {
                models: this.modelSettings.models
            })
                .then(response => {
                    if (response.data && response.data.success) {
                        const payload = response.data.data || {};
                        this.modelSettings = {
                            config_path: payload.config_path || '',
                            updated_at: payload.updated_at || '',
                            model_types: payload.model_types || this.modelSettings.model_types || [],
                            models: (payload.models || []).map(item => ({
                                enabled: item.enabled !== false,
                                api: item.api || '',
                                api_key: item.api_key || '',
                                cached_input_price_per_million: item.cached_input_price_per_million ?? null,
                                currency: item.currency || 'CNY',
                                ...item
                            }))
                        };
                        this.$message.success('模型配置已保存，新启动任务将使用最新配置');
                    } else {
                        this.$message.error((response.data && response.data.error) || '保存模型配置失败');
                    }
                })
                .catch(error => {
                    console.error('保存模型配置失败:', error);
                    const message = error.response && error.response.data && error.response.data.error;
                    this.$message.error(message || '保存模型配置失败');
                })
                .finally(() => {
                    this.modelSettingsSaving = false;
                });
        },

        testModelConfig(row) {
            if (!row) return;
            this.$set(row, 'testing', true);
            axios.post(`${apiBaseUrl}/settings/models/test`, { model: row })
                .then(response => {
                    if (response.data && response.data.success) {
                        const payload = response.data.data || {};
                        this.$message.success(`连接成功，耗时 ${payload.latency_ms || 0} ms`);
                    } else {
                        this.$message.error((response.data && response.data.error) || '模型连接测试失败');
                    }
                })
                .catch(error => {
                    console.error('模型连接测试失败:', error);
                    const message = error.response && error.response.data && error.response.data.error;
                    this.$message.error(message || '模型连接测试失败');
                })
                .finally(() => {
                    this.$set(row, 'testing', false);
                });
        },

        // ========== Phase 1-3: 统一任务管理方法 ==========
        
        /**
         * 处理工作台导航事件
         */
        handleDashboardNavigate(target) {
            this.activeTab = target;
        },
        
        /**
         * 查看图片需求任务详情
         */
        viewImageTaskDetail(taskId) {
            // 记录来源页面（用于返回）
            this.previousTab = this.activeTab;
            
            // 切换到图片需求任务详情（使用现有组件）
            this.activeTab = 'imageRequirementList';
            // 等待视图渲染后触发详情查看
            this.$nextTick(() => {
                // 使用 ref 访问 requirement-module-component
                const component = this.$refs.imageModuleComponent;
                if (component) {
                    // 先加载详情数据，然后切换到详情视图
                    component.loadModuleDetail(taskId).then(() => {
                        component.currentView = 'detail';
                    }).catch(err => {
                        console.error('加载图片需求详情失败:', err);
                    });
                } else {
                    console.error('imageModuleComponent ref not found');
                }
            });
        },
        
        /**
         * 查看文本PRD任务详情
         */
        viewTextTaskDetail(taskId) {
            // 记录来源页面（用于返回）
            this.previousTab = this.activeTab;
            
            // 切换到文本PRD详情（使用现有组件）
            this.activeTab = 'textPRDList';
            // 等待视图渲染后触发详情查看
            this.$nextTick(() => {
                // 使用 ref 访问 text-prd-manager
                const component = this.$refs.textPRDManager;
                if (component && component.viewPRDDetail) {
                    component.viewPRDDetail(taskId);
                } else {
                    console.error('textPRDManager ref not found or viewPRDDetail method not available');
                }
            });
        },
        
        /**
         * 编辑图片需求任务
         */
        editImageTask(taskId) {
            // 记录来源页面（用于返回）
            this.previousTab = this.activeTab;
            
            // 切换到图片需求列表页
            this.activeTab = 'imageRequirementList';
            // 等待视图渲染后触发编辑
            this.$nextTick(() => {
                const component = this.$refs.imageModuleComponent;
                if (component) {
                    // 先加载模块数据
                    component.loadModuleDetail(taskId).then(() => {
                        // 然后触发编辑（将数据加载到表单）
                        if (component.currentModule) {
                            component.editModule(component.currentModule);
                        }
                    }).catch(err => {
                        console.error('加载图片需求失败:', err);
                    });
                } else {
                    console.error('imageModuleComponent ref not found');
                }
            });
        },
        
        /**
         * 编辑文本PRD任务
         */
        editTextTask(taskId) {
            // 文本PRD的编辑就是查看详情页（详情页本身支持编辑）
            this.viewTextTaskDetail(taskId);
        },
        
        /**
         * 查看Task运行详情（直接显示Task详情页）
         */
        viewTaskRunningDetail(taskId) {
            // 记录来源页面（用于返回）
            this.previousTab = this.activeTab;
            
            // 直接调用viewTaskDetail方法显示Task详情
            this.viewTaskDetail({ id: taskId });
        },
        
        /**
         * 处理子组件返回父组件的事件
         */
        handleBackToParent() {
            // 如果有记录的来源页面，则返回到来源页面
            if (this.previousTab) {
                this.activeTab = this.previousTab;
                this.previousTab = null; // 清除记录
            }
            // 否则组件内部会自己处理返回逻辑
        },
        
        // ========== 原有方法 ==========
        
        // 通用数据刷新
        refreshData() {
            this.fetchTasks();
            if (this.selectedTask) {
                this.fetchTaskDetails(this.currentTaskRequestId || this.selectedTask.id || this.selectedTask.task_id);
            }
        },

        // 保存当前任务上下文到localStorage
        saveTaskContext(taskId) {
            localStorage.setItem('currentTaskId', taskId);
            localStorage.setItem('lastActive', Date.now());
        },

        // 清理轮询
        cleanupPolling() {
            if (this.pollingInterval) {
                clearInterval(this.pollingInterval);
                this.pollingInterval = null;
            }
            this.clearMessagePolling();
        },

        clearMessagePolling() {
            if (this.messagePollingTimer) {
                clearTimeout(this.messagePollingTimer);
                this.messagePollingTimer = null;
            }
        },

        getTaskId(task) {
            if (!task) return null;
            return task.id || task.task_id || null;
        },

        getResultFileTaskId(task) {
            if (!task) return null;
            return task.id || task.task_id || this.currentTaskRequestId || null;
        },

        getTaskIdentifiers(task) {
            if (!task) return [];
            return [
                task.id,
                task.task_id,
                task.module_id,
                task.generated_task_id,
                task.prd_id
            ]
                .filter(value => value !== undefined && value !== null && value !== '')
                .map(value => String(value));
        },

        isSelectedTask(taskId) {
            if (!taskId) return false;
            const normalizedTaskId = String(taskId);
            const selectedIdentifiers = this.getTaskIdentifiers(this.selectedTask);
            if (this.currentTaskRequestId) {
                return String(this.currentTaskRequestId) === normalizedTaskId ||
                    selectedIdentifiers.includes(normalizedTaskId);
            }
            return selectedIdentifiers.includes(normalizedTaskId);
        },

        getTaskProgress(task) {
            if (!task) return 0;
            const progress = task.completion_percentage !== undefined
                ? task.completion_percentage
                : task.progress;
            const numericProgress = Number(progress || 0);
            return Number.isFinite(numericProgress) ? numericProgress : 0;
        },

        isSelectedTaskWaitingConfirmation() {
            return this.selectedTask && isTaskWaitingConfirmationStatus(this.selectedTask.status);
        },

        isSelectedTaskActive() {
            return this.selectedTask && isTaskActiveStatus(this.selectedTask.status);
        },

        getSelectedTaskProgress() {
            return this.getTaskProgress(this.selectedTask);
        },

        sanitizeTestCaseForDisplay(testCase) {
            if (!testCase || typeof testCase !== 'object') return testCase;
            const hiddenFields = new Set(['关联需求', '原始用例编号', '测试包ID', '测试包类型', '测试ID']);
            const sanitized = {};
            Object.keys(testCase).forEach(key => {
                if (!hiddenFields.has(key)) {
                    sanitized[key] = testCase[key];
                }
            });
            return sanitized;
        },

        normalizeTaskResults(results) {
            if (!results) return [];
            if (Array.isArray(results)) return results.map(item => this.sanitizeTestCaseForDisplay(item));
            if (typeof results === 'string') {
                try {
                    return this.normalizeTaskResults(JSON.parse(results));
                } catch (error) {
                    console.warn('测试用例结果不是有效JSON字符串:', error);
                    return [];
                }
            }
            if (typeof results === 'object') {
                return this.normalizeTaskResults(
                    results.results ||
                    results.testcases ||
                    results.test_cases ||
                    results.test_cases_json ||
                    []
                );
            }
            return [];
        },

        getTaskCasesFromDetail(task) {
            if (!task) return [];
            return this.normalizeTaskResults(
                task.testcases ||
                task.test_cases ||
                task.test_cases_json ||
                []
            );
        },

        getTaskFlowSteps() {
            const steps = [];
            if (this.aiCollaborationEnabled || this.hasLanggraphData()) {
                steps.push('aiDiscussion');
            }
            steps.push('confirmationItems', 'testcaseGeneration', 'results');
            return steps;
        },

        getFlowStepNumber(stepName) {
            const index = this.getTaskFlowSteps().indexOf(stepName);
            return index >= 0 ? index + 1 : '';
        },

        getDefaultTaskDetailTab(task) {
            if (!task) {
                return this.aiCollaborationEnabled ? 'aiDiscussion' : 'testcaseGeneration';
            }
            if (task.status === 'completed') {
                return 'results';
            }
            if (isTaskWaitingConfirmationStatus(task.status)) {
                return 'confirmationItems';
            }
            const progress = this.getTaskProgress(task);
            const message = task.message || '';
            if (task.final_prd || task.prd_final || progress >= 75 || message.includes('测试用例') || message.includes('最终PRD')) {
                return 'testcaseGeneration';
            }
            return this.aiCollaborationEnabled ? 'aiDiscussion' : 'testcaseGeneration';
        },

        isTaskDetailTabAvailable(tabName) {
            if (tabName === 'aiDiscussion') {
                return this.aiCollaborationEnabled || this.hasLanggraphData();
            }
            return this.getTaskFlowSteps().includes(tabName);
        },

        // 🌟 获取现代化流程步骤的样式类
        getFlowStepClass(stepName) {
            const stepOrder = this.getTaskFlowSteps();
            const currentIndex = stepOrder.indexOf(stepName);
            const activeIndex = stepOrder.indexOf(this.taskDetailTab);
            
            // 智能判断步骤是否已完成（基于业务流程和任务状态）
            let isCompleted = false;
            
            // 如果有测试结果，说明整个流程基本完成，前面的步骤都应该是完成状态
            const hasTestResults = this.taskResults && this.taskResults.length > 0;
            const hasConfirmation = this.submittedConfirmationResults && this.submittedConfirmationResults.length > 0;
            const hasAiMessages = this.getEarlyStageMessages().length > 0;
            const progress = this.getSelectedTaskProgress();
            const status = this.selectedTask ? this.selectedTask.status : '';
            const hasFinalPrd = this.selectedTask && this.selectedTask.final_prd;
            
            switch(stepName) {
                case 'aiDiscussion':
                    isCompleted = hasAiMessages; // 有AI协作消息就算完成
                    break;
                case 'confirmationItems':
                    isCompleted = hasConfirmation || hasFinalPrd || progress >= 75 || status === 'completed' || isTaskWaitingConfirmationStatus(status);
                    break;
                case 'testcaseGeneration':
                    isCompleted = hasTestResults || status === 'completed';
                    break;
                case 'results':
                    isCompleted = hasTestResults; // 有测试结果就算完成
                    break;
            }
            
            if (stepName === this.taskDetailTab) {
                return { active: true }; // 当前激活的步骤：蓝色
            } else if (isCompleted) {
                return { completed: true }; // 已完成的步骤：绿色
            } else {
                return {}; // 未完成的步骤：灰色
            }
        },

        // 获取任务列表
        fetchTasks() {
            axios.get(`${apiBaseUrl}/tasks?limit=20`)
                .then(response => {
                    console.log('获取任务列表响应:', response);
                    if (response.data && response.data.success) {
                        // 确认tasks字段的位置
                        if (Array.isArray(response.data.data.tasks)) {
                            this.tasks = response.data.data.tasks;
                        } else if (Array.isArray(response.data.data)) {
                            this.tasks = response.data.data;
                        } else if (Array.isArray(response.data)) {
                            this.tasks = response.data;
                        } else {
                            console.error('任务列表格式不符合预期:', response.data);
                            this.$message.error('获取任务列表失败，返回格式错误');
                            return;
                        }
                    } else {
                        console.error('获取任务列表失败:', response.data);
                        this.$message.error('获取任务列表失败');
                    }
                })
                .catch(error => {
                    console.error('获取任务列表异常:', error);
                    this.$message.error('获取任务列表失败: ' + error.message);
                });
        },

        // 导航到任务列表
        goToTaskList() {
            // 如果有记录的来源页面（从统一任务管理进入），返回到来源页面
            if (this.previousTab) {
                this.activeTab = this.previousTab;
                this.previousTab = null; // 清除记录
            } else {
                // 否则返回到旧的任务列表页
                this.activeTab = 'taskList';
                this.fetchTasks();
            }
        },

        // 查看任务详情
        viewTaskDetail(task) {
            console.log('查看任务详情:', task);
            const taskId = task.id || task.task_id;

            this.fetchTaskDetails(taskId);

            // 切换到任务详情标签页
            this.activeTab = 'taskDetail';
        },

        // 获取任务完整详情
        fetchTaskDetails(taskId, silent = false) {
            if (!taskId) return;
            this.currentTaskRequestId = taskId;

            // 保存任务上下文到localStorage
            this.saveTaskContext(taskId);

            // 静默刷新时不显示 loading
            if (!silent) {
                this.isLoading = true;
            }

            axios.get(`${apiBaseUrl}/tasks/${taskId}`)
                .then(response => {
                    if (String(this.currentTaskRequestId || '') !== String(taskId || '')) {
                        return;
                    }

                    if (response.data && response.data.success) {
                        // 选中任务 - 数据包装在 response.data.data 中
                        const previousTaskId = this.getTaskId(this.selectedTask);
                        this.selectedTask = this.normalizeTaskDetail(response.data.data);
                        const selectedTaskId = this.getTaskId(this.selectedTask);
                        const effectiveTaskId = selectedTaskId || taskId;
                        if (String(effectiveTaskId || '') !== String(this.currentTaskRequestId || '')) {
                            this.currentTaskRequestId = effectiveTaskId;
                            this.saveTaskContext(effectiveTaskId);
                        }
                        
                        // 只有切换到不同任务时才重置已提交的确认结果
                        if (previousTaskId !== selectedTaskId) {
                            this.submittedConfirmationResults = [];
                            this.confirmationSubmitted = false;
                            this.taskDetailTab = this.getDefaultTaskDetailTab(this.selectedTask);
                        } else if (!this.isTaskDetailTabAvailable(this.taskDetailTab)) {
                            this.taskDetailTab = this.getDefaultTaskDetailTab(this.selectedTask);
                        }

                        if (previousTaskId !== selectedTaskId) {
                            this.agentMessages = [];
                            this.agentChatHistory = [];
                            this.langgraphView = {
                                enabled: false,
                                main_nodes: [],
                                testcase_nodes: [],
                                main_state: {},
                                testcase_state: {},
                                usage_summary: {},
                                output_dir: '',
                                message: ''
                            };
                            this.confirmationItems = [];
                            this.finalPrdPreview = null;
                        }

                        this.taskResults = this.getTaskCasesFromDetail(this.selectedTask);
                        
                        console.log("查看任务详情:", response.data);
                        
                        // 开始轮询任务状态（仅在非静默刷新时启动轮询）
                        if (!silent) {
                            this.startTaskPolling(effectiveTaskId);
                        }
                        
                        this.fetchLanggraphView(effectiveTaskId);
                        
                        // 获取消息和日志
                        this.fetchTaskMessages(effectiveTaskId);
                        
                        // 获取确认项
                        this.fetchConfirmationItems(effectiveTaskId);
                        
                        // 如果是已完成状态，获取结果
                        if (this.selectedTask.status === 'completed') {
                            this.fetchTaskResults(effectiveTaskId);
                        }
                        
                        // 预览PRD文件（仅在使用旧版Timeline设计时需要）
                        if (this.showCuteTimeline) {
                            this.previewPrdFile(effectiveTaskId);
                        }
                        
                        // 自动设置需求定稿预览
                        if (this.selectedTask.final_prd) {
                            this.finalPrdPreview = safeRenderMarkdown(this.selectedTask.final_prd);
                            console.log('自动设置需求定稿预览');
                        }

                        if (!silent && previousTaskId === selectedTaskId) {
                            this.taskDetailTab = this.getDefaultTaskDetailTab(this.selectedTask);
                        }
                    } else {
                        this.$message.error('获取任务详情失败: ' + (response.data.message || '未知错误'));
                    }
                    // 静默刷新时不隐藏 loading（因为本来就没显示）
                    if (!silent) {
                        this.isLoading = false;
                    }
                })
                .catch(error => {
                    console.error('获取任务详情失败:', error);

                    // 如果是404错误（任务不存在），清理localStorage中的缓存
                    if (error.response && error.response.status === 404) {
                        console.warn('任务不存在，清理localStorage缓存:', taskId);
                        localStorage.removeItem('currentTaskId');
                        localStorage.removeItem('lastActive');
                        // 静默失败，不显示错误消息（避免首页加载时的干扰）
                        if (!silent) {
                            this.$message.warning('上次查看的任务已不存在');
                        }
                    } else {
                        // 其他错误正常显示
                        this.$message.error('获取任务详情失败: ' + (error.message || '未知网络错误'));
                    }

                    // 静默刷新时不隐藏 loading（因为本来就没显示）
                    if (!silent) {
                        this.isLoading = false;
                    }
                });
        },

        // 开始轮询任务状态
        startTaskPolling(taskId) {
            // 清除之前的轮询
            this.cleanupPolling();

            if (this.selectedTask && isTaskTerminalStatus(this.selectedTask.status)) {
                return;
            }

            // 设置轮询间隔
            this.pollingInterval = setInterval(() => {
                this.pollTaskStatus(taskId);
            }, 8000); // 每8秒轮询一次

            // 立即执行一次
            this.pollTaskStatus(taskId);
        },

        // 轮询任务状态
        pollTaskStatus(taskId) {
            axios.get(`${apiBaseUrl}/tasks/${taskId}/brief_status`)
                .then(response => {
                    if (response.data && response.data.success) {
                        const status = response.data.data
                            ? (response.data.data.status || response.data.data)
                            : response.data.status;
                        if (!status) {
                            return;
                        }
                        if (!this.isSelectedTask(taskId)) {
                            return;
                        }

                        const oldStatus = this.selectedTask ? this.selectedTask.status : null;
                        const oldProgress = this.getSelectedTaskProgress();
                        const nextProgress = this.getTaskProgress(status);

                        // 更新任务状态
                        if (this.selectedTask) {
                            this.selectedTask.status = normalizeTaskStatus(status.status);
                            this.selectedTask.completion_percentage = nextProgress;
                            this.selectedTask.progress = nextProgress;
                            if (status.message) {
                                this.selectedTask.message = status.message;
                            }
                            if (status.processing_stage) {
                                this.selectedTask.processing_stage = status.processing_stage;
                            }
                        }

                        // 🆕 检测进度变化：如果进度有显著变化（>5%），重新获取完整任务详情
                        // 这样可以及时获取最终用例和生成摘要等结果
                        const progressChanged = Math.abs(nextProgress - oldProgress) >= 5;
                        if (progressChanged && isTaskActiveStatus(status.status)) {
                            console.log(`任务进度更新: ${oldProgress}% -> ${nextProgress}%，刷新详情`);
                            // 重新获取完整任务详情
                            this.fetchTaskDetails(taskId, true); // true 表示静默刷新，不重新启动轮询
                            this.fetchLanggraphView(taskId);
                        }

                        if (
                            isTaskActiveStatus(status.status) &&
                            nextProgress >= 75 &&
                            (!this.aiCollaborationEnabled || this.taskDetailTab !== 'aiDiscussion')
                        ) {
                            this.taskDetailTab = 'testcaseGeneration';
                        }

                        if (isTaskTerminalStatus(status.status) || isTaskWaitingConfirmationStatus(status.status)) {
                            if (this.pollingInterval) {
                                clearInterval(this.pollingInterval);
                                this.pollingInterval = null;
                            }
                        }

                        // 状态发生变化
                        if (oldStatus !== status.status) {
                            console.log(`任务状态变更: ${oldStatus} -> ${status.status}`);

                            // 如果任务状态为waiting_confirmation，获取确认项
                            if (isTaskWaitingConfirmationStatus(status.status)) {
                                this.fetchConfirmationItems(taskId);
                                this.taskDetailTab = 'confirmationItems';

                                this.$notify({
                                    title: '⚠️ 需要您的确认',
                                    message: '测试架构师已完成分析，发现问题需要您的确认才能继续生成测试用例。',
                                    type: 'warning',
                                    duration: 0,
                                    showClose: true
                                });
                            }

                            // 如果任务完成，获取结果
                            if (status.status === 'completed') {
                                this.fetchTaskDetails(taskId, true);
                                this.fetchTaskResults(taskId);
                                this.taskDetailTab = 'results';

                                this.$notify({
                                    title: '🎉 任务完成',
                                    message: '测试用例生成完成！您可以下载Excel或JSON格式的文件。',
                                    type: 'success',
                                    duration: 8000,
                                    showClose: true
                                });

                                // 任务完成后停止轮询
                                this.clearMessagePolling();
                            }

                            // 获取最新消息和日志
                            this.fetchTaskMessages(taskId);
                            this.fetchLanggraphView(taskId);
                        }
                    }
                })
                .catch(error => {
                    console.error('轮询任务状态失败:', error);
                });
        },

        // 获取任务消息
        fetchTaskMessages(taskId) {
            this.clearMessagePolling();
            
            console.log(`正在获取任务 ${taskId} 的聊天记录...`);
            axios.get(`${apiBaseUrl}/tasks/${taskId}/messages`)
                .then(response => {
                    if (!this.isSelectedTask(taskId)) {
                        return;
                    }

                    console.log('聊天记录API响应:', response.data);
                    
                    let messages = [];
                    if (response.data && response.data.success === true) {
                        const responsePayload = response.data.data || response.data;
                        if (Array.isArray(responsePayload.messages)) {
                            messages = responsePayload.messages;
                        } else if (Array.isArray(response.data)) {
                            messages = response.data;
                        }
                    }

                    if (messages.length > 0) {
                        console.log(`获取到 ${messages.length} 条聊天记录`);
                        // 将消息格式化并按时间戳排序（确保正序显示）
                        this.agentMessages = messages.map(msg => {
                            return {
                                role: msg.role || msg.sender || msg.agent || msg.agent_name || msg.name || '',
                                content: msg.content || msg.message || msg.text || '',
                                timestamp: msg.timestamp || msg.created_at || msg.time || msg.ts || '',
                                sequence: Number.isFinite(Number(msg.sequence)) ? Number(msg.sequence) : null,
                                source: msg.source || '',
                                unit_id: msg.unit_id || msg.unitId || '',
                                agent_type: msg.agent_type || msg.agentType || '',
                                stage_key: msg.stage_key || msg.stageKey || '',
                                stage_name: msg.stage_name || msg.stageName || '',
                                io_type: msg.io_type || msg.ioType || '',
                                title: msg.title || ''
                            };
                        });
                        
                        // 按照时间戳排序，确保从旧到新显示
                        this.agentMessages.sort((a, b) => {
                            const timeA = new Date(a.timestamp || 0).getTime();
                            const timeB = new Date(b.timestamp || 0).getTime();
                            if (timeA !== timeB) {
                                return timeA - timeB; // 从小到大排序，即从早到晚
                            }
                            const seqA = a.sequence === null ? Number.MAX_SAFE_INTEGER : a.sequence;
                            const seqB = b.sequence === null ? Number.MAX_SAFE_INTEGER : b.sequence;
                            return seqA - seqB;
                        });
                        
                        // 保持向后兼容
                        this.agentChatHistory = this.agentMessages;
                    } else {
                        this.agentMessages = [];
                        this.agentChatHistory = [];
                        console.log('没有获取到聊天记录，可能是API返回格式不符合预期或尚无记录');
                    }

                    // 每5秒自动刷新聊天记录
                    if (
                        this.selectedTask &&
                        this.isSelectedTask(taskId) &&
                        isTaskActiveStatus(this.selectedTask.status)
                    ) {
                        this.messagePollingTimer = setTimeout(() => {
                            if (
                                this.selectedTask &&
                                this.isSelectedTask(taskId) &&
                                isTaskActiveStatus(this.selectedTask.status)
                            ) {
                                this.fetchTaskMessages(taskId);
                            }
                        }, 5000);
                    }
                })
                .catch(error => {
                    console.error('获取聊天记录失败:', error);
                    // 不显示错误消息，因为可能是接口尚未实现
                });
        },

        fetchLanggraphView(taskId) {
            axios.get(`${apiBaseUrl}/tasks/${taskId}/langgraph`)
                .then(response => {
                    if (!this.isSelectedTask(taskId)) {
                        return;
                    }
                    if (response.data && response.data.success) {
                        const payload = response.data.data || {};
                        this.langgraphView = {
                            enabled: !!payload.enabled,
                            main_nodes: payload.main_nodes || [],
                            testcase_nodes: payload.testcase_nodes || [],
                            main_state: payload.main_state || {},
                            testcase_state: payload.testcase_state || {},
                            usage_summary: payload.usage_summary || {},
                            output_dir: payload.output_dir || '',
                            message: payload.message || ''
                        };
                    }
                })
                .catch(error => {
                    console.error('获取LangGraph运行图失败:', error);
                });
        },

        hasLanggraphData() {
            return !!(
                this.langgraphView &&
                this.langgraphView.enabled &&
                (
                    (this.langgraphView.main_nodes && this.langgraphView.main_nodes.length > 0) ||
                    (this.langgraphView.testcase_nodes && this.langgraphView.testcase_nodes.length > 0)
                )
            );
        },

        getLanggraphNodeStatusType(status) {
            const normalized = normalizeTaskStatus(status);
            const mapping = {
                success: 'success',
                completed: 'success',
                running: 'warning',
                failed: 'danger',
                waiting_confirmation: 'warning',
                pending: 'info'
            };
            return mapping[normalized || status] || 'info';
        },

        getLanggraphNodeStatusText(status) {
            const normalized = normalizeTaskStatus(status);
            const mapping = {
                success: '成功',
                completed: '完成',
                running: '运行中',
                failed: '失败',
                waiting_confirmation: '等待确认',
                pending: '待执行'
            };
            return mapping[normalized || status] || status || '未知';
        },

        getLanggraphNodeName(nodeId) {
            const mapping = {
                '01_load_module': '加载模块',
                '01_load_prd': '加载PRD',
                '02_clean_prd': '整理PRD',
                '03_prd_logic_review': 'PRD逻辑审查',
                '04_waiting_confirmation': '等待确认',
                '05_final_prd_integrate': '最终PRD整合',
                '06_testcase_pipeline': '生成测试用例',
                '02_image_analysis': '图片分析',
                '03_prd_generation': 'PRD生成',
                '04_prd_review': 'PRD审核',
                '05_waiting_confirmation': '等待确认',
                '06_confirmation_integrate': '确认整合',
                '07_testcase_pipeline': '生成测试用例',
                '08_save_result': '保存结果',
                '01_prepare_agents': '准备智能体',
                '02_block_prd': 'PRD分块',
                '03_build_knowledge': '知识构建',
                '04_build_context_units': '上下文组装',
                '05_generate_unit_cases': '生成测试用例',
                '06_merge_cases': '合并用例',
                '07_save_result': '保存中间结果'
            };
            return mapping[nodeId] || nodeId;
        },

        getLanggraphStageKey(node) {
            if (!node) return '';
            return node.display_id || node.current_node || node.id || '';
        },

        getLanggraphDisplayNodes() {
            const mainNodes = (this.langgraphView && this.langgraphView.main_nodes) || [];
            const testcaseNodes = (this.langgraphView && this.langgraphView.testcase_nodes) || [];
            const mainNodeMap = {};
            mainNodes.forEach(node => {
                mainNodeMap[node.id] = node;
            });
            const mainFlow = this.getLanggraphMainFlowDefinition(mainNodes);
            const normalizedMainNodes = mainFlow.map((nodeId, index) => {
                const existing = mainNodeMap[nodeId];
                if (existing) {
                    return existing;
                }
                return {
                    id: nodeId,
                    status: 'pending',
                    duration_ms: null,
                    pending_order: index
                };
            });
            if (testcaseNodes.length === 0) {
                return normalizedMainNodes;
            }
            const merged = [];
            normalizedMainNodes.forEach(node => {
                if (node.id === '07_testcase_pipeline' || node.id === '06_testcase_pipeline') {
                    testcaseNodes.forEach(childNode => {
                        merged.push({
                            ...childNode,
                            id: `testcase_${childNode.id}`,
                            display_id: childNode.id
                        });
                    });
                } else {
                    merged.push(node);
                }
            });
            return merged;
        },

        getLanggraphMainFlowDefinition(mainNodes) {
            const ids = (mainNodes || []).map(node => node.id);
            if (ids.includes('01_load_prd') || ids.includes('03_prd_logic_review')) {
                return [
                    '01_load_prd',
                    '02_clean_prd',
                    '03_prd_logic_review',
                    '04_waiting_confirmation',
                    '05_final_prd_integrate',
                    '06_testcase_pipeline',
                    '07_save_result'
                ];
            }
            return [
                '01_load_module',
                '02_image_analysis',
                '03_prd_generation',
                '04_prd_review',
                '05_waiting_confirmation',
                '06_confirmation_integrate',
                '07_testcase_pipeline',
                '08_save_result'
            ];
        },

        normalizeTaskDetail(task) {
            if (!task || typeof task !== 'object') return task;
            return {
                ...task,
                status: normalizeTaskStatus(task.status)
            };
        },

        getSelectedLanggraphNode() {
            const nodes = this.getLanggraphDisplayNodes();
            if (!nodes.length) return null;
            const selected = nodes.find(node => this.getLanggraphStageKey(node) === this.selectedLanggraphStageKey);
            return selected || nodes[0];
        },

        selectLanggraphNode(node) {
            this.selectedLanggraphStageKey = this.getLanggraphStageKey(node);
        },

        isLanggraphNodeSelected(node) {
            const selected = this.getSelectedLanggraphNode();
            return !!selected && this.getLanggraphStageKey(selected) === this.getLanggraphStageKey(node);
        },

        getLanggraphDurationText(durationMs) {
            if (durationMs === null || durationMs === undefined || durationMs === '') {
                return '-';
            }
            const value = Number(durationMs);
            if (!Number.isFinite(value)) {
                return String(durationMs);
            }
            if (value < 1000) {
                return `${Math.round(value)} ms`;
            }
            if (value < 60000) {
                return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)} s`;
            }
            const minutes = Math.floor(value / 60000);
            const seconds = Math.round((value % 60000) / 1000);
            return `${minutes} min ${seconds} s`;
        },

        getLanggraphTotalDuration(nodes) {
            const total = (nodes || []).reduce((sum, node) => {
                const value = Number(node.duration_ms);
                return Number.isFinite(value) ? sum + value : sum;
            }, 0);
            return this.getLanggraphDurationText(total);
        },

        getLanggraphSuccessCount(nodes) {
            return (nodes || []).filter(node => {
                const status = node.status || '';
                return status === 'success' || status === 'completed';
            }).length;
        },

        getLanggraphFailedCount(nodes) {
            return (nodes || []).filter(node => (node.status || '') === 'failed').length;
        },

        getLanggraphSummaryStats() {
            const allNodes = this.getLanggraphDisplayNodes();
            return {
                totalNodes: allNodes.length,
                successNodes: this.getLanggraphSuccessCount(allNodes),
                failedNodes: this.getLanggraphFailedCount(allNodes),
                totalDuration: this.getLanggraphTotalDuration(allNodes),
                roughCost: this.getLanggraphRoughCostText(),
                messageCount: this.getLanggraphDebugMessages().length
            };
        },

        getLanggraphRoughCostText() {
            const summary = (this.langgraphView && this.langgraphView.usage_summary) || {};
            const costs = summary.costs_by_currency || {};
            const entries = Object.keys(costs)
                .map(currency => ({
                    currency,
                    value: Number(costs[currency])
                }))
                .filter(item => Number.isFinite(item.value));
            if (entries.length === 0) {
                if ((summary.calls || 0) > 0 || (summary.total_tokens || 0) > 0) {
                    return '未配置价格';
                }
                return '-';
            }
            return entries
                .map(item => `${this.getCurrencySymbol(item.currency)}${this.formatCostValue(item.value)}${this.getCurrencySuffix(item.currency)}`)
                .join(' + ');
        },

        getCurrencySymbol(currency) {
            const normalized = String(currency || '').toUpperCase();
            if (normalized === 'CNY') return '¥';
            if (normalized === 'USD') return '$';
            return '';
        },

        getCurrencySuffix(currency) {
            const normalized = String(currency || '').toUpperCase();
            if (normalized === 'CNY' || normalized === 'USD') return '';
            return normalized ? ` ${normalized}` : '';
        },

        formatCostValue(value) {
            const number = Number(value);
            if (!Number.isFinite(number)) return '-';
            if (number === 0) return '0';
            if (number < 0.0001) return number.toExponential(2);
            if (number < 0.01) return number.toFixed(5).replace(/0+$/, '').replace(/\.$/, '');
            if (number < 1) return number.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
            return number.toFixed(2);
        },

        getLanggraphDebugMessages() {
            if (!this.agentMessages || this.agentMessages.length === 0) {
                return [];
            }
            return this.agentMessages
                .map((message, index) => ({
                    ...message,
                    debugIndex: index
                }))
                .filter(message => {
                    const source = (message.source || '').toLowerCase();
                    const role = (message.role || '').toLowerCase();
                    return source.includes('langgraph') ||
                           role.includes('prompt') ||
                           role.includes('prd block') ||
                           role.includes('prd knowledge') ||
                           role.includes('moduletestcasewriter') ||
                           role.includes('integrationtestcasewriter');
                });
        },

        getLanggraphMessagesForNode(node) {
            const stageKey = this.getLanggraphStageKey(node);
            if (!stageKey) return [];
            return this.getLanggraphDebugMessages().filter(message => {
                return (message.stage_key || '') === stageKey;
            });
        },

        getSelectedLanggraphMessages() {
            const selected = this.getSelectedLanggraphNode();
            return selected ? this.getLanggraphMessagesForNode(selected) : [];
        },

        getSelectedLanggraphMessagesByType(type) {
            return this.getSelectedLanggraphMessages().filter(message => {
                const ioType = message.io_type || (this.isLanggraphPromptMessage(message) ? 'input' : 'output');
                return ioType === type;
            });
        },

        getFilteredLanggraphDebugMessages() {
            const messages = this.getLanggraphDebugMessages();
            if (this.langgraphMessageFilter === 'prompt') {
                return messages.filter(message => this.isLanggraphPromptMessage(message));
            }
            if (this.langgraphMessageFilter === 'response') {
                return messages.filter(message => !this.isLanggraphPromptMessage(message));
            }
            return messages;
        },

        isLanggraphPromptMessage(message) {
            const role = (message.role || '').toLowerCase();
            const source = (message.source || '').toLowerCase();
            return role.includes('prompt') || source.includes('prompt');
        },

        getLanggraphMessageTitle(message) {
            const role = message.title || this.getMessageRoleName(message);
            const unit = this.getLanggraphUnitLabel(message.unit_id);
            return `${role}${unit}`;
        },

        getLanggraphUnitLabel(unitId) {
            if (!unitId) return '';
            const match = String(unitId).match(/^(INT|LU)-(\d+)$/i);
            if (!match) return '';
            const number = String(Number(match[2]));
            return match[1].toUpperCase() === 'INT' ? ` · 链路 ${number}` : ` · 模块 ${number}`;
        },

        getLanggraphMessageType(message) {
            return this.isLanggraphPromptMessage(message) ? 'info' : 'success';
        },

        getLanggraphMessageDisplayContent(message) {
            if (!message) return '';
            const content = message.content || '';
            if ((message.io_type || '') !== 'input') {
                return content;
            }
            return this.extractBusinessInputContent(content, message);
        },

        extractBusinessInputContent(content, message) {
            let text = this.cleanPrdMarkers(content || '').trim();
            const stageKey = message.stage_key || '';

            if (stageKey === '02_image_analysis') {
                return this.extractMarkedSection(text, '【当前模块】', '【分析任务】') ||
                       this.removeLeadingAgentInstruction(text);
            }
            if (stageKey === '03_prd_generation') {
                return this.extractFromMarker(text, '各图片分析结果:') ||
                       this.extractFromMarker(text, '各图片分析结果：') ||
                       this.removeLeadingAgentInstruction(text);
            }
            if (stageKey === '04_prd_review') {
                return this.extractMarkedSection(text, '【PRD文档】') || text;
            }
            if (stageKey === '06_confirmation_integrate') {
                return this.extractMarkedSection(text, '【原始PRD】') || this.removeLeadingAgentInstruction(text);
            }
            if (stageKey === '03_prd_logic_review') {
                return this.extractMarkedSection(text, '【原始 PRD】') ||
                       this.extractMarkedSection(text, '【原始PRD】') ||
                       this.removeLeadingAgentInstruction(text);
            }
            if (stageKey === '05_final_prd_integrate') {
                return this.extractMarkedSection(text, '【原始 PRD】') ||
                       this.extractMarkedSection(text, '【原始PRD】') ||
                       this.removeLeadingAgentInstruction(text);
            }
            if (stageKey === '02_block_prd') {
                return this.extractMarkedSection(text, '【任务名称】') || text;
            }
            if (stageKey === '03_build_knowledge') {
                return this.extractMarkedSection(text, '【带 BLOCK 标记的原文 PRD】') || text;
            }
            if (stageKey === '05_generate_unit_cases') {
                const start = text.indexOf('【用例生成上下文】');
                if (start >= 0) {
                    text = text.substring(start);
                }
                text = text
                    .replace(/【当前 LU 生成边界】[\s\S]*?(?=【|$)/g, '')
                    .replace(/【关联需求填写约束】[\s\S]*?(?=【|$)/g, '')
                    .replace(/【测试补充备注】\s*无\s*/g, '');
                return text.trim();
            }
            return this.removeLeadingAgentInstruction(text);
        },

        extractMarkedSection(content, startMarker, endMarker) {
            const start = content.indexOf(startMarker);
            if (start < 0) return '';
            if (!endMarker) {
                return content.substring(start).trim();
            }
            const end = content.indexOf(endMarker, start + startMarker.length);
            return content.substring(start, end >= 0 ? end : undefined).trim();
        },

        extractFromMarker(content, marker) {
            const index = content.indexOf(marker);
            if (index < 0) return '';
            return content.substring(index + marker.length).trim();
        },

        removeLeadingAgentInstruction(content) {
            return (content || '')
                .replace(/^你是[^\n。]*[。.\n]\s*/m, '')
                .replace(/^请[^。\n]*[。.\n]\s*/m, '')
                .trim();
        },

        getLanggraphMessagePreview(message) {
            let cleanContent = this.stripMarkdown(this.getLanggraphMessageDisplayContent(message))
                .replace(/\s+/g, ' ')
                .trim();
            cleanContent = cleanContent
                .replace(/当前\s*LU\s*ID\s*:\s*INT-\d+\s*/gi, '')
                .replace(/当前\s*LU\s*ID\s*:\s*LU-\d+\s*/gi, '')
                .replace(/类型\s*:\s*integration_lu\s*/gi, '')
                .replace(/类型\s*:\s*normal_lu\s*/gi, '');
            return cleanContent.length > 220 ? `${cleanContent.substring(0, 220)}...` : cleanContent;
        },

        // 获取确认项 - 增强错误处理和重试机制
        fetchConfirmationItems(taskId, retryCount = 0) {
            console.log(`正在获取任务 ${taskId} 的确认项... (第${retryCount + 1}次尝试)`);

            // 实际API调用
            axios.get(`${apiBaseUrl}/tasks/${taskId}/confirmation_items`)
                .then(response => {
                    if (!this.isSelectedTask(taskId)) {
                        return;
                    }

                    console.log('确认项API响应:', response.data);
                    let items = [];

                    if (response.data && response.data.success === true) {
                        const responsePayload = response.data.data || response.data;
                        if (Array.isArray(responsePayload.items)) {
                            items = responsePayload.items;
                        } else if (Array.isArray(response.data)) {
                            items = response.data;
                        }
                    }

                    if (items && items.length > 0) {
                        console.log(`获取到 ${items.length} 个确认项`);
                        
                        // 检查是否为已提交的确认结果
                        const hasSubmittedItems = items.some(item => 
                            item.is_submitted || 
                            item.user_answer || 
                            item.confirmed ||
                            item.submitted_at
                        );
                        
                        // 如果任务已完成或包含已提交的确认结果，显示已提交的结果
                        if ((this.selectedTask && this.selectedTask.status === 'completed') || hasSubmittedItems) {
                            // 将确认项转换为submittedConfirmationResults格式
                            this.submittedConfirmationResults = items.map(item => {
                                // 处理已提交的确认结果格式
                                if (item.user_answer || item.confirmed || item.is_submitted) {
                                    return {
                                        question: item.question || item.question_details || `问题 ${item.confirmation_id || item.id || ''}`,
                                        description: item.description || item.question_details || '',
                                        confirm_points: item.confirm_points || [],
                                        reference_examples: item.reference_examples || [],
                                        answer: item.user_answer || item.answer || '(未提供回答)'
                                    };
                                }
                                
                                // 处理新格式
                                return {
                                    question: item.question || item.title || `问题 ${item.id || ''}`,
                                    description: item.description || item.question_details || '',
                                    confirm_points: item.confirm_points || [],
                                    reference_examples: item.reference_examples || [],
                                    answer: item.answer || '(未提供回答)'
                                };
                            });
                            
                            // 标记确认已提交，避免DOM突然变化
                            this.confirmationSubmitted = true;
                            
                            console.log('检测到已提交的确认结果，显示已提交状态');
                            
                            // 自动切换到确认项标签页
                            this.taskDetailTab = 'confirmationItems';
                        } else {
                            // 正常处理待确认的项目
                            this.confirmationItems = items;
                            this.confirmationSubmitted = false; // 重置提交状态

                            // 初始化响应对象，使用数字索引作为键
                            this.confirmationItems.forEach((item, index) => {
                                const key = `answer_${index}`;
                                this.$set(this.confirmationResponses, key, '');
                                // 注意：不再创建 answer_${item.id} 格式的键
                                // 因为表单绑定的是 answer_${index}，创建额外的键会导致后端解析错误
                            });

                            console.log('检测到待确认的项目，显示确认表单');

                            // 自动切换到确认项标签页
                            this.taskDetailTab = 'confirmationItems';
                        }
                    } else {
                        console.log('未找到确认项，检查任务状态...');

                        // 如果任务状态是等待确认，但没有获取到确认项，进行重试
                        if (this.isSelectedTaskWaitingConfirmation() && retryCount < 3) {
                            console.log(`任务状态为等待确认，但未找到确认项，将在${3 + retryCount * 2}秒后重试`);
                            setTimeout(() => {
                                if (this.isSelectedTask(taskId)) {
                                    this.fetchConfirmationItems(taskId, retryCount + 1);
                                }
                            }, (3 + retryCount * 2) * 1000);
                        } else if (retryCount >= 3) {
                            // 重试次数超限，显示错误信息
                            this.$message({
                                message: '获取确认项失败，请刷新页面重试',
                                type: 'error',
                                duration: 5000
                            });
                        } else {
                            // 正常情况下没有确认项，检查是否有已提交的确认结果
                            if (this.isSelectedTaskActive() && this.submittedConfirmationResults.length === 0) {
                                // 无确认项时保持在当前产出物视图
                                // 同时可通过抽屉查看协作过程
                            }
                        }
                    }
                })
                .catch(error => {
                    if (!this.isSelectedTask(taskId)) {
                        return;
                    }

                    console.error('获取确认项失败:', error);
                    
                    // 网络错误或API错误，进行重试
                    if (retryCount < 3) {
                        console.log(`API调用失败，将在${5 + retryCount * 3}秒后重试`);
                        setTimeout(() => {
                            if (this.isSelectedTask(taskId)) {
                                this.fetchConfirmationItems(taskId, retryCount + 1);
                            }
                        }, (5 + retryCount * 3) * 1000);
                    } else {
                        // 重试次数超限
                        this.$message({
                            message: '获取确认项失败，请检查网络连接或刷新页面重试',
                            type: 'error',
                            duration: 8000
                        });
                        
                        // 如果确实是等待确认状态，显示友好提示
                        if (this.isSelectedTaskWaitingConfirmation()) {
                            this.$notify({
                                title: '无法获取确认项',
                                message: '请尝试刷新页面或联系技术支持',
                                type: 'error',
                                duration: 0
                            });
                        }
                    }
                });
        },

        // 打开协作抽屉
        openCollaboration() {
            this.showCollabDrawer = true;
            // 确保最新消息
            if (this.selectedTask) {
                const taskId = this.currentTaskRequestId || this.getTaskId(this.selectedTask);
                this.fetchTaskMessages(taskId);
            }
        },

        // 关闭协作抽屉
        closeCollaboration() {
            this.showCollabDrawer = false;
        },

        // 切换协作抽屉全屏
        toggleCollabFullScreen() {
            this.collabFullScreen = !this.collabFullScreen;
        },

        // 获取任务结果
        fetchTaskResults(taskId) {
            axios.get(`${apiBaseUrl}/tasks/${taskId}/results`)
                .then(response => {
                    if (!this.isSelectedTask(taskId)) {
                        return;
                    }

                    if (response.data && response.data.success) {
                        const responsePayload = response.data.data || response.data;
                        const remoteResults = this.normalizeTaskResults(responsePayload.results);
                        this.taskResults = remoteResults.length > 0
                            ? remoteResults
                            : this.getTaskCasesFromDetail(this.selectedTask);
                    } else {
                        console.error('获取任务结果失败:', response.data);
                        this.taskResults = this.getTaskCasesFromDetail(this.selectedTask);
                    }
                })
                .catch(error => {
                    console.error('获取任务结果异常:', error);
                    if (this.isSelectedTask(taskId)) {
                        this.taskResults = this.getTaskCasesFromDetail(this.selectedTask);
                    }
                });
        },

        getGenerationStatusText() {
            if (!this.selectedTask) return '正在生成测试用例';
            return this.selectedTask.message || '正在生成测试用例';
        },

        getGenerationStatusHint() {
            if (!this.selectedTask) {
                return '系统正在基于最终需求文档生成测试用例，请稍候';
            }
            const progress = this.getSelectedTaskProgress();
            if (this.selectedTask.status === 'completed') {
                return '测试用例已生成完成，可查看结果或下载Excel文件';
            }
            if (progress >= 96) {
                return '系统正在整理测试结果并生成可下载文件';
            }
            if (progress >= 88) {
                return '系统正在生成测试用例，请稍候';
            }
            if (progress >= 80) {
                return '系统正在准备需求上下文与覆盖范围';
            }
            return '系统正在基于最终需求文档生成测试用例，请稍候';
        },

        // 下载结果文件
        downloadResults(fileType) {
            if (!this.selectedTask) return;

            const taskId = this.getResultFileTaskId(this.selectedTask);
            const downloadUrl = `${apiBaseUrl}/download/${taskId}/${fileType}`;

            // 创建一个隐藏的a标签并模拟点击下载
            const link = document.createElement('a');
            link.href = downloadUrl;
            link.target = '_blank';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        },

        // 预览PRD文件
        previewPrdFile(taskId) {
            console.log('预览PRD文件:', taskId);

            // 如果任务对象中有prd_id，优先使用prd_id
            let fileId = taskId;
            let originalTaskId = taskId;
            this.retryAttempted = false;

            if (this.selectedTask && this.selectedTask.prd_id) {
                fileId = this.selectedTask.prd_id;
                console.log('使用任务中的prd_id:', fileId);
            } else if (taskId && taskId.includes('_')) {
                // 如果是复合ID，提取原始文件ID
                fileId = taskId.split('_')[0];
                console.log('从任务ID提取原始文件ID:', fileId);
            }

            // 清除之前的错误
            this.clearErrorMessages();

            // 先尝试直接获取文件内容
            this.loadPrdContent(fileId)
                .catch(error => {
                    console.error('直接获取PRD内容失败:', error);

                    // 尝试使用原始任务ID
                    if (fileId !== originalTaskId) {
                        return this.loadPrdContent(originalTaskId);
                    }
                    throw error;
                })
                .catch(error => {
                    console.error('使用原始任务ID获取PRD内容失败:', error);

                    // 最后尝试直接使用文件名
                    if (this.selectedTask && this.selectedTask.name) {
                        return this.loadPrdContent(this.selectedTask.name);
                    }
                    throw error;
                })
                .catch(error => {
                    console.error('所有尝试均失败:', error);
                    this.$message({
                        message: '无法加载PRD内容，请刷新页面重试',
                        type: 'error',
                        duration: 5000
                    });
                });
        },

        // 加载PRD内容的辅助方法
        loadPrdContent(fileId) {
            return new Promise((resolve, reject) => {
                axios.get(`${apiBaseUrl}/files/${fileId}/content`)
                    .then(response => {
                        console.log('PRD内容响应:', response.data);
                        if (response.data && response.data.success) {
                            const content = response.data.data.content || '';
                            console.log('成功获取PRD内容，长度:', content.length);

                            // 渲染Markdown
                            this.prdPreview = safeRenderMarkdown(content);
                            resolve(content);
                        } else {
                            console.error('获取PRD内容失败:', response.data);
                            reject(new Error(response.data.message || '未知错误'));
                        }
                    })
                    .catch(reject);
            });
        },

        // 清除错误消息
        clearErrorMessages() {
            const existingErrors = document.querySelectorAll('.el-message.el-message--error');
            existingErrors.forEach(el => {
                el.parentNode.removeChild(el);
            });
        },

        // 渲染Markdown内容
        renderMarkdown(content) {
            // 先清理PRD标记，再渲染Markdown
            const cleanContent = this.cleanPrdMarkers(content);
            return safeRenderMarkdown(cleanContent);
        },

        // 直接生成HTML表格，确保正确显示
        renderTestCasesAsHtmlTable(taskResults) {
            if (!taskResults || taskResults.length === 0) {
                return '<p>暂无测试用例数据</p>';
            }

            let htmlTable = `
                <table class="test-cases-table" style="width: 100%; border-collapse: collapse; margin-top: 15px;">
                    <thead>
                        <tr style="background-color: #f5f7fa;">
                            <th style="border: 1px solid #e4e7ed; padding: 8px; text-align: left;">功能模块</th>
                            <th style="border: 1px solid #e4e7ed; padding: 8px; text-align: left;">测试场景分类</th>
                            <th style="border: 1px solid #e4e7ed; padding: 8px; text-align: left;">用例编号</th>
                            <th style="border: 1px solid #e4e7ed; padding: 8px; text-align: left;">用例名称</th>
                            <th style="border: 1px solid #e4e7ed; padding: 8px; text-align: left;">前置条件</th>
                            <th style="border: 1px solid #e4e7ed; padding: 8px; text-align: left;">测试步骤</th>
                            <th style="border: 1px solid #e4e7ed; padding: 8px; text-align: left;">预期结果</th>
                            <th style="border: 1px solid #e4e7ed; padding: 8px; text-align: left;">优先级</th>
                            <th style="border: 1px solid #e4e7ed; padding: 8px; text-align: left;">用例类型</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            taskResults.forEach((testCase, index) => {
                const module = testCase.功能模块 || testCase.id || testCase.module || '通用模块';
                const scenario = testCase.测试场景分类 || testCase.module || testCase.submodule || testCase.scenario || '功能测试';
                const caseNumber = testCase.用例编号 || testCase.scenario || testCase.case_number || `${String(index + 1).padStart(3, '0')}`;
                const caseName = testCase.用例名称 || testCase.case_name || testCase.title || '未命名测试用例';
                const precondition = testCase.前置条件 || testCase.preconditions || testCase.precondition || '无';
                const steps = testCase.测试步骤 || testCase.steps || testCase.test_steps || '无';
                const expected = testCase.预期结果 || testCase.expected || testCase.expected_result || '无';
                const priority = testCase.优先级 || testCase.priority || 'P1';
                const type = testCase.用例类型 || testCase.test_type || testCase.testType || testCase.type || '功能测试';

                // 清理和格式化文本，保留<br>标签
                const formatText = (text) => {
                    if (!text) return '无';
                    return String(text)
                        .replace(/&/g, '&amp;')
                        .replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;')
                        .replace(/&lt;br\s*\/?&gt;/gi, '<br>')  // 恢复<br>标签
                        .replace(/\n/g, '<br>');  // 将换行符转为<br>
                };

                htmlTable += `
                    <tr style="border-bottom: 1px solid #e4e7ed;">
                        <td style="border: 1px solid #e4e7ed; padding: 8px; vertical-align: top;">${formatText(module)}</td>
                        <td style="border: 1px solid #e4e7ed; padding: 8px; vertical-align: top;">${formatText(scenario)}</td>
                        <td style="border: 1px solid #e4e7ed; padding: 8px; vertical-align: top;">${formatText(caseNumber)}</td>
                        <td style="border: 1px solid #e4e7ed; padding: 8px; vertical-align: top;">${formatText(caseName)}</td>
                        <td style="border: 1px solid #e4e7ed; padding: 8px; vertical-align: top;">${formatText(precondition)}</td>
                        <td style="border: 1px solid #e4e7ed; padding: 8px; vertical-align: top;">${formatText(steps)}</td>
                        <td style="border: 1px solid #e4e7ed; padding: 8px; vertical-align: top;">${formatText(expected)}</td>
                        <td style="border: 1px solid #e4e7ed; padding: 8px; vertical-align: top; text-align: center;">${formatText(priority)}</td>
                        <td style="border: 1px solid #e4e7ed; padding: 8px; vertical-align: top;">${formatText(type)}</td>
                    </tr>
                `;
            });

            htmlTable += `
                    </tbody>
                </table>
            `;

            return htmlTable;
        },

        // 获取状态类型样式
        getStatusType(status) {
            const normalized = normalizeTaskStatus(status);
            const statusMap = {
                'created': 'info',
                'running': 'primary',
                'analyzing': 'primary',
                'collaborating': 'primary',
                'processing': 'primary',
                'finalizing_prd': 'primary',
                'waiting_confirmation': 'warning',
                'completed': 'success',
                'failed': 'danger'
            };
            return statusMap[normalized] || 'info';
        },

        // 获取状态文本
        getStatusText(status) {
            const normalized = normalizeTaskStatus(status);
            const statusTextMap = {
                'created': '🎯 待启动',
                'running': '⚙️ 运行中',
                'analyzing': '🔍 分析中',
                'collaborating': '🤝 协作中',
                'processing': '⚙️ 运行中',
                'finalizing_prd': '📝 整理最终PRD',
                'waiting_confirmation': '✋ 等待确认',
                'completed': '✅ 已完成',
                'failed': '❌ 失败',
                'cancelled': '🚫 已取消'
            };
            return statusTextMap[normalized] || status;
        },



        // 获取进度条颜色
        getProgressColor(percentage) {
            if (percentage < 30) {
                return '#f56c6c';
            } else if (percentage < 70) {
                return '#e6a23c';
            } else {
                return '#67c23a';
            }
        },

        // 加载最终PRD
        loadFinalPrd(taskId) {
            console.log('加载最终PRD:', taskId);
            
            if (!this.selectedTask || !this.selectedTask.final_prd) {
                this.$message.warning('最终PRD尚未生成');
                return;
            }
            
            // 直接从任务数据中渲染最终PRD
            try {
                this.finalPrdPreview = safeRenderMarkdown(this.selectedTask.final_prd);
                console.log('最终PRD加载成功');
            } catch (error) {
                console.error('渲染最终PRD失败:', error);
                this.$message.error('渲染最终PRD失败');
            }
        },

        // 格式化时间
        formatTime(timestamp) {
            if (!timestamp) return '';
            
            try {
                // 处理ISO格式的字符串
                if (typeof timestamp === 'string' && timestamp.includes('T')) {
                    const date = new Date(timestamp);
                    if (!isNaN(date.getTime())) {
                        return date.toLocaleString('zh-CN', {
                            year: 'numeric',
                            month: '2-digit',
                            day: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit'
                        });
                    }
                }
                
                // 处理数字时间戳
                const date = new Date(timestamp);
                return date.toLocaleString('zh-CN');
            } catch (error) {
                console.error('时间格式化错误:', error);
                return timestamp; // 返回原始值
            }
        },

        // AI对话模块增强方法
        getMessageRoleColor(message) {
            const sender = message.sender || message.role || 'unknown';
            const colorMap = {
                'system': '#909399',
                'user': '#409EFF', 
                'assistant': '#67C23A',
                'ai': '#67C23A',
                'productmanager': '#E6A23C',
                'product_manager': '#E6A23C',
                'testarchitect': '#F56C6C',
                'test_architect': '#F56C6C',
                'testwriter': '#9C27B0',
                'test_writer': '#9C27B0',
                'test_case_writer': '#9C27B0',
                'module_test_case_writer': '#9C27B0',
                'human': '#FF6B6B',
                'user': '#FF6B6B',
                'unknown': '#999999'
            };
            
            // 支持更具体的agent类型
            if (message.agent_type) {
                const agentType = message.agent_type.toLowerCase();
                if (agentType.includes('product') || agentType.includes('pm')) {
                    return '#E6A23C';
                } else if (agentType.includes('architect')) {
                    return '#F56C6C';
                } else if (agentType.includes('writer') || agentType.includes('tester')) {
                    return '#9C27B0';
                }
            }
            
            return colorMap[sender.toLowerCase()] || colorMap['unknown'];
        },

        getMessageRoleIcon(message) {
            // 现在使用背景图片作为头像，返回空字符串或者备用emoji
            const sender = message.sender || message.role || 'unknown';
            const senderLower = sender.toLowerCase();
            
            // 如果头像图片加载失败，显示备用emoji
            if (senderLower.includes('productmanager') || senderLower.includes('product_manager')) {
                return '';  // 使用背景图片
            } else if (senderLower.includes('testarchitect') || senderLower.includes('test_architect')) {
                return '';  // 使用背景图片
            } else if (senderLower.includes('testwriter') || senderLower.includes('test_writer') || senderLower.includes('test_case_writer') || senderLower.includes('moduletestcasewriter') || senderLower.includes('module_test_case_writer')) {
                return '';  // 使用背景图片
            } else if (senderLower.includes('human') || senderLower.includes('user')) {
                return '';  // 使用背景图片
            } else {
                return '🤖';  // AI思考时显示机器人emoji
            }
        },

        getMessageRoleDescription(message) {
            const sender = (message.sender || message.role || '').toLowerCase();
            const content = message.content || '';
            
            // 根据角色和内容特征返回简单描述
            if (sender.includes('productmanager') || sender.includes('product_manager')) {
                if (content.includes('回答') || content.includes('问题') || content.includes('TestArchitect')) {
                    return '📝 回答测试架构师提出的问题';
                } else if (content.includes('整理') || content.includes('最终') || content.includes('完善')) {
                    return '📋 整理最终PRD文档';
                } else {
                    return '🔍 分析PRD文档需求';
                }
            } else if (sender.includes('testarchitect') || sender.includes('test_architect')) {
                return '🏗️ 针对PRD提出测试相关问题';
            } else if (sender.includes('testwriter') || sender.includes('test_writer') || sender.includes('test_case_writer') || sender.includes('moduletestcasewriter') || sender.includes('module_test_case_writer')) {
                if (content.includes('分析报告') || content.includes('功能模块识别')) {
                    return '📊 分析PRD并识别测试模块';
                } else {
                    return '✍️ 编写测试用例';
                }
            } else if (sender.includes('user') || sender.includes('human')) {
                return '✋ 用户确认关键问题';
            } else if (sender.includes('system')) {
                return '⚙️ 系统初始化';
            }
            return '🤖 AI协作中';
        },

        getMessageRoleName(message) {
            const sender = message.sender || message.role || 'unknown';
            const nameMap = {
                'system': '系统',
                'user': '用户',
                'assistant': 'AI助手',
                'ai': 'AI助手',
                'productmanager': '产品经理',
                'product_manager': '产品经理',
                'testarchitect': '测试架构师',
                'test_architect': '测试架构师',
                'testwriter': '测试编写师',
                'test_writer': '测试编写师',
                'test_case_writer': '测试编写师',
                'module_test_case_writer': '模块用例编写师',
                'moduletestcasewriter': '模块用例编写师',
                'moduletestcasewriter prompt': '模块用例编写输入',
                'module_test_case_writer prompt': '模块用例编写输入',
                'integrationtestcasewriter': '链路用例编写师',
                'integrationtestcasewriter prompt': '链路用例编写输入',
                'prd block builder': 'PRD分块',
                'prd block builder prompt': 'PRD分块输入',
                'prd knowledge builder': '知识构建',
                'prd knowledge builder prompt': '知识构建输入',
                'prd knowledge context': '知识上下文',
                'prd knowledge context prompt': '知识上下文输入',
                'imageanalyst': '图片分析',
                'imageanalyst prompt': '图片分析输入',
                'imageintegrationanalyst': 'PRD整合',
                'imageintegrationanalyst prompt': 'PRD整合输入',
                'imageprdreviewer': 'PRD审核',
                'imageprdreviewer prompt': 'PRD审核输入',
                'confirmationintegrator': '确认整合',
                'confirmationintegrator prompt': '确认整合输入',
                'human': '用户',
                'user': '用户',
                'unknown': '未知角色'
            };
            
            // 如果有具体的agent_type，优先使用
            if (message.agent_type) {
                return message.agent_type;
            }
            
            return nameMap[sender.toLowerCase()] || nameMap['unknown'];
        },

        getMessageAction(message) {
            const sender = message.sender || message.role || 'unknown';
            const senderLower = sender.toLowerCase();
            const content = message.content || '';
            
            // 根据固定流程顺序确定角色行为
            if (senderLower === 'system') {
                return '系统消息推送';
            } else if (senderLower.includes('productmanager') || senderLower.includes('product_manager')) {
                // 产品经理有三个阶段，通过内容特征判断
                if (content.includes('PRD文档') && content.includes('版本') && content.includes('2.0')) {
                    // 最终PRD文档通常包含版本2.0
                    return '输出最终PRD文档';
                } else if ((content.includes('回答') || content.includes('针对TestArchitect') || content.includes('针对测试架构师')) && content.includes('问题')) {
                    // 回答通常包含针对测试架构师的问题
                    return '回答测试架构师问题';
                } else if (content.includes('优化') || content.includes('版本') && content.includes('1.0')) {
                    // 初始分析通常包含版本1.0
                    return '进行需求分析和优化';
                }
                return '提供产品需求分析';
            } else if (senderLower.includes('testarchitect') || senderLower.includes('test_architect')) {
                return '提出测试相关问题';
            } else if (senderLower.includes('testwriter') || senderLower.includes('test_writer') || senderLower.includes('test_case_writer') || senderLower.includes('moduletestcasewriter') || senderLower.includes('module_test_case_writer')) {
                return '编写测试用例';
            } else if (senderLower.includes('human') || senderLower.includes('user')) {
                return '提供需求确认和补充';
            }
            
            return '参与协作流程';
        },

        // 新增的炫酷聊天界面方法
        getMessageAlignment(message) {
            const sender = message.sender || message.role || '';
            const senderLower = sender.toLowerCase();
            
            // 左侧：产品经理和用户
            // 右侧：测试架构师、测试编写师
            if (senderLower.includes('productmanager') || senderLower.includes('product_manager') || 
                senderLower.includes('human') || senderLower.includes('user')) {
                return 'left';
            } else {
                return 'right';
            }
        },

        getBubbleClass(message) {
            return this.getMessageAlignment(message);
        },

        getAvatarClass(message) {
            const sender = message.sender || message.role || 'unknown';
            const senderLower = sender.toLowerCase();
            
            if (senderLower.includes('productmanager') || senderLower.includes('product_manager')) {
                return 'product-manager';
            } else if (senderLower.includes('testarchitect') || senderLower.includes('test_architect')) {
                return 'test-architect';
            } else if (senderLower.includes('testwriter') || senderLower.includes('test_writer') || senderLower.includes('test_case_writer') || senderLower.includes('moduletestcasewriter') || senderLower.includes('module_test_case_writer')) {
                return 'test-writer';
            } else if (senderLower.includes('human') || senderLower.includes('user')) {
                return 'user';
            }
            
            return 'ai-thinking';
        },

        getAvatarStyle(message) {
            // CSS类已经处理了样式，这里返回空对象
            return {};
        },

        // 显示AI思考指示器
        showAIThinking() {
            this.isAIThinking = true;
            setTimeout(() => {
                this.isAIThinking = false;
            }, 3000);
        },

        // 自动滚动到聊天底部
        scrollChatToBottom() {
            this.$nextTick(() => {
                const chatContainer = document.querySelector('.chat-messages-enhanced');
                if (chatContainer) {
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                }
            });
        },

        // 组织消息为不同阶段
        getConversationPhases() {
            if (!this.agentMessages || this.agentMessages.length === 0) {
                return [];
            }

            const phases = [
                {
                    id: 'initialization',
                    title: '第一阶段：系统初始化',
                    description: '系统启动并准备AI智能体协作流程',
                    icon: '⚙️',
                    messages: []
                },
                {
                    id: 'prd_analysis',
                    title: '第二阶段：产品经理PRD分析',
                    description: '产品经理对PRD文档进行深入分析和理解',
                    icon: '👔',
                    messages: []
                },
                {
                    id: 'architect_review',
                    title: '第三阶段：测试架构师审查',
                    description: '测试架构师审查PRD并提出测试相关问题',
                    icon: '🏗️',
                    messages: []
                },
                {
                    id: 'pm_response',
                    title: '第四阶段：产品经理回答',
                    description: '产品经理针对测试架构师的问题提供详细回答',
                    icon: '💬',
                    messages: []
                },
                {
                    id: 'human_confirmation',
                    title: '第五阶段：人工确认补充',
                    description: '用户对关键问题进行确认和补充说明',
                    icon: '✋',
                    messages: []
                },
                {
                    id: 'final_prd',
                    title: '第六阶段：最终PRD整理',
                    description: '产品经理基于所有信息整理最终完善的PRD文档',
                    icon: '📋',
                    messages: []
                },
                {
                    id: 'test_generation',
                    title: '第七阶段：测试用例生成',
                    description: '测试编写师根据最终PRD生成全面的测试用例',
                    icon: '✍️',
                    messages: []
                }
            ];

            // 按阶段分组消息
            this.agentMessages.forEach(message => {
                const sender = (message.role || '').toLowerCase();
                const content = message.content || '';
                
                if (sender === 'system') {
                    phases[0].messages.push(message);
                } else if (sender.includes('productmanager')) {
                    // 更智能的产品经理消息分组逻辑
                    if (content.includes('回答') || content.includes('问题') || content.includes('TestArchitect') || phases[2].messages.length > 0) {
                        // 如果包含确认相关内容，且人工确认阶段有消息，则归入最终PRD阶段
                        if ((content.includes('确认') || content.includes('整理') || content.includes('最终') || content.includes('完善')) && phases[4].messages.length > 0) {
                            phases[5].messages.push(message);
                        } else {
                            // 否则归入回答问题阶段
                            phases[3].messages.push(message);
                        }
                    } else {
                        // 初始的产品经理分析
                        phases[1].messages.push(message);
                    }
                } else if (sender.includes('testarchitect')) {
                    phases[2].messages.push(message);
                } else if (sender.includes('testwriter') || sender.includes('test_writer') || sender.includes('test_case_writer') || sender.includes('moduletestcasewriter') || sender.includes('module_test_case_writer')) {
                    phases[6].messages.push(message);
                } else if (sender.includes('user') || sender.includes('human')) {
                    // 人工确认阶段
                    phases[4].messages.push(message);
                } else {
                    // 未知消息类型，根据内容判断
                    if (content.includes('确认') || content.includes('human')) {
                        phases[4].messages.push(message);
                    } else {
                        phases[0].messages.push(message);
                    }
                }
            });
            
            // 如果有确认项数据，为人工确认阶段添加虚拟消息
            if (this.confirmationItems && this.confirmationItems.length > 0) {
                phases[4].messages.push({
                    sender: 'Human',
                    content: `用户需要确认${this.confirmationItems.length}个关键问题，以帮助AI生成更精准的测试用例。`,
                    timestamp: new Date().toISOString()
                });
            }

            // 过滤掉没有消息的阶段
            return phases.filter(phase => phase.messages.length > 0);
        },

        // 清理内容中的PRD文档标记
        cleanPrdMarkers(content) {
            if (!content) return '';
            return content
                .replace(/<PRD_DOCUMENT_START>/g, '')
                .replace(/<PRD_DOCUMENT_END>/g, '')
                .replace(/<\/PRD_DOCUMENT_END>/g, '')
                .trim();
        },

        getChatPreview(content) {
            if (!content) return '';
            // 清理PRD标记后返回前50个字符作为聊天预览
            const cleanContent = this.cleanPrdMarkers(content);
            return cleanContent.substring(0, 50);
        },

        // 获取AI协作讨论阶段的消息（包含产品经理、测试架构师的完整协作过程）
        getEarlyStageMessages() {
            if (!this.agentMessages || this.agentMessages.length === 0) {
                return [];
            }
            
            // 找到测试用例编写师开始工作的分界点（排除测试分析和用例生成阶段）
            let cutOffIndex = this.agentMessages.length;
            
            for (let i = 0; i < this.agentMessages.length; i++) {
                const message = this.agentMessages[i];
                const sender = (message.role || '').toLowerCase();
                const content = message.content || '';
                
                // 如果遇到测试用例编写师的消息，说明协作讨论阶段结束
                if (this.isTestWriter(sender)) {
                    cutOffIndex = i;
                    break;
                }
            }
            
            // 返回测试用例编写师之前的所有消息（包含完整的产品经理和测试架构师协作过程）
            return this.agentMessages.slice(0, cutOffIndex);
        },

        // 获取测试分析阶段的消息（测试工程师的PRD智能分析报告）
        getTestAnalysisMessages() {
            if (!this.agentMessages || this.agentMessages.length === 0) {
                return [];
            }
            
            // 优先取包含分析关键词的消息，否则退化为所有测试工程师消息
            const isWriter = (m) => this.isTestWriter((m.role || '').toLowerCase());
            const hasKeyword = (c) => {
                if (!c) return false;
                const s = c.toLowerCase();
                return s.includes('prd智能分析报告') || s.includes('分析报告') || s.includes('智能分析') || s.includes('测试分析');
            };

            let base = this.agentMessages.filter(m => isWriter(m) && hasKeyword(m.content));
            if (base.length === 0) base = this.agentMessages.filter(m => isWriter(m));
            
            // 清理内容后返回
            return base.map(message => {
                return {
                    ...message,
                    content: this.cleanTableContent(message.content)
                };
            });
        },

        // 清理表格内容的辅助方法
        cleanTableContent(content) {
            if (!content) return '';
            
            let cleanContent = content;
            
            // 找到表格开始的位置
            const tableMarkers = [
                '\n| 功能模块',
                '\n|功能模块',
                '| 功能模块',
                '|功能模块'
            ];
            
            let tableStartIndex = -1;
            for (const marker of tableMarkers) {
                const index = cleanContent.indexOf(marker);
                if (index !== -1) {
                    tableStartIndex = index;
                    break;
                }
            }
            
            // 如果找到表格，只保留表格之前的内容
            if (tableStartIndex !== -1) {
                cleanContent = cleanContent.substring(0, tableStartIndex).trim();
            }
            
            // 如果清理后内容太短，返回原始内容的前半部分
            if (cleanContent.length < 100) {
                const lines = content.split('\n');
                const nonTableLines = [];
                
                for (const line of lines) {
                    // 跳过明显的表格行
                    if (line.includes('|') && 
                        (line.includes('功能模块') || line.includes('测试场景') || 
                         line.includes('用例名称') || line.includes('---'))) {
                        break;
                    }
                    nonTableLines.push(line);
                }
                
                cleanContent = nonTableLines.join('\n').trim();
            }
            
            return cleanContent || content; // 如果清理失败，返回原内容
        },

        // 角色识别辅助方法
        isTestArchitect(sender) {
            if (!sender) return false;
            return sender.includes('testarchitect') || 
                   sender.includes('test_architect') ||
                   sender.includes('架构师');
        },

        isProductManager(sender) {
            if (!sender) return false;
            return sender.includes('productmanager') || 
                   sender.includes('product_manager') ||
                   sender.includes('产品经理');
        },

        isTestWriter(sender) {
            if (!sender) return false;
            return sender.includes('testwriter') || 
                   sender.includes('test_writer') ||
                   sender.includes('test_case_writer') ||
                   sender.includes('moduletestcasewriter') ||
                   sender.includes('module_test_case_writer') ||
                   sender.includes('测试工程师');
        },

        // 3D卡片内容提取方法
        getMergedAnalysisText() {
            const msgs = this.getTestAnalysisMessages();
            if (!msgs || msgs.length === 0) {
                // 如果没有分析消息，尝试从所有测试工程师消息中获取
                const testWriterMsgs = this.agentMessages.filter(m => this.isTestWriter((m.role || '').toLowerCase()));
                if (testWriterMsgs.length > 0) {
                    const merged = testWriterMsgs.map(m => m.content || '').join('\n\n');
                    return this.stripMarkdown(this.cleanTableContent(merged));
                }
                return '';
            }
            const merged = msgs.map(m => m.content || '').join('\n\n');
            return this.stripMarkdown(this.cleanTableContent(merged));
        },

        getPlainModulesContent() {
            const sections = this.splitAnalysisContent(this.getMergedAnalysisText());
            return sections.modules || '暂无测试模块评估内容';
        },

        getPlainCoverageContent() {
            const sections = this.splitAnalysisContent(this.getMergedAnalysisText());
            return sections.coverage || '暂无测试覆盖策略内容';
        },

        getPlainScaleContent() {
            const sections = this.splitAnalysisContent(this.getMergedAnalysisText());
            return sections.scale || '暂无预估用例规模内容';
        },

        // 新增格式化方法，保留markdown结构
        getFormattedModulesContent() {
            const msgs = this.getTestAnalysisMessages();
            if (!msgs || msgs.length === 0) return '暂无测试模块评估内容';
            
            const merged = msgs.map(m => m.content || '').join('\n\n');
            const cleanedContent = this.cleanTableContent(merged);
            const sections = this.splitFormattedAnalysisContent(cleanedContent);
            return sections.modules || '暂无测试模块评估内容';
        },

        getFormattedCoverageContent() {
            const msgs = this.getTestAnalysisMessages();
            if (!msgs || msgs.length === 0) return '暂无测试覆盖策略内容';
            
            const merged = msgs.map(m => m.content || '').join('\n\n');
            const cleanedContent = this.cleanTableContent(merged);
            const sections = this.splitFormattedAnalysisContent(cleanedContent);
            return sections.coverage || '暂无测试覆盖策略内容';
        },

        getFormattedScaleContent() {
            const msgs = this.getTestAnalysisMessages();
            if (!msgs || msgs.length === 0) return '暂无用例生成策略内容';
            
            const merged = msgs.map(m => m.content || '').join('\n\n');
            const cleanedContent = this.cleanTableContent(merged);
            const sections = this.splitFormattedAnalysisContent(cleanedContent);
            
            // 如果找到相关内容就返回，否则返回暂无内容提示
            return sections.scale || '暂无用例生成策略内容';
        },

        splitAnalysisContent(text) {
            if (!text) return { modules: '', coverage: '', scale: '' };
            
            // 清理文本，移除多余空行
            const cleanText = text.replace(/\n{3,}/g, '\n\n').trim();
            
            // 查找关键分割点
            const moduleStartPattern = /功能模块识别[:：]/i;
            const coverageStartPattern = /测试覆盖策略[:：]/i;
            const scaleStartPattern = /预估用例规模[:：]/i;
            
            let moduleStart = -1;
            let coverageStart = -1;
            let scaleStart = -1;
            
            // 按行查找分割点
            const lines = cleanText.split('\n');
            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];
                
                if (moduleStartPattern.test(line) && moduleStart === -1) {
                    moduleStart = i;
                } else if (coverageStartPattern.test(line) && coverageStart === -1) {
                    coverageStart = i;
                } else if (scaleStartPattern.test(line) && scaleStart === -1) {
                    scaleStart = i;
                }
            }
            
            // 如果没有找到明确的分割点，尝试包含模式匹配
            if (moduleStart === -1 || coverageStart === -1 || scaleStart === -1) {
                for (let i = 0; i < lines.length; i++) {
                    const line = lines[i].toLowerCase();
                    
                    if ((line.includes('功能模块') || line.includes('模块识别')) && moduleStart === -1) {
                        moduleStart = i;
                    } else if ((line.includes('测试覆盖') || line.includes('覆盖策略')) && coverageStart === -1) {
                        coverageStart = i;
                    } else if ((line.includes('预估用例') || line.includes('用例规模')) && scaleStart === -1) {
                        scaleStart = i;
                    }
                }
            }
            
            let result = { modules: '', coverage: '', scale: '' };
            
            if (moduleStart >= 0 && coverageStart >= 0 && scaleStart >= 0) {
                // 所有分割点都找到了
                result.modules = lines.slice(moduleStart, coverageStart).join('\n').trim();
                result.coverage = lines.slice(coverageStart, scaleStart).join('\n').trim();
                result.scale = lines.slice(scaleStart).join('\n').trim();
            } else if (moduleStart >= 0 && coverageStart >= 0) {
                // 找到前两个分割点
                result.modules = lines.slice(moduleStart, coverageStart).join('\n').trim();
                const remaining = lines.slice(coverageStart);
                const midPoint = Math.floor(remaining.length / 2);
                result.coverage = remaining.slice(0, midPoint).join('\n').trim();
                result.scale = remaining.slice(midPoint).join('\n').trim();
            } else if (moduleStart >= 0) {
                // 只找到第一个分割点
                result.modules = lines.slice(moduleStart, Math.floor(lines.length / 3)).join('\n').trim();
                result.coverage = lines.slice(Math.floor(lines.length / 3), Math.floor(lines.length * 2 / 3)).join('\n').trim();
                result.scale = lines.slice(Math.floor(lines.length * 2 / 3)).join('\n').trim();
            } else {
                // 没有找到分割点，按三等分处理
                const thirdLength = Math.floor(lines.length / 3);
                result.modules = lines.slice(0, thirdLength).join('\n').trim();
                result.coverage = lines.slice(thirdLength, thirdLength * 2).join('\n').trim();
                result.scale = lines.slice(thirdLength * 2).join('\n').trim();
            }
            
            // 确保每个部分都有内容
            if (!result.modules && cleanText.length > 0) {
                result.modules = '功能模块识别和模块复杂度评估内容';
            }
            if (!result.coverage && cleanText.length > 0) {
                result.coverage = '测试覆盖策略内容';
            }
            if (!result.scale && cleanText.length > 0) {
                result.scale = '预估用例规模内容';
            }
            
            return result;
        },

        // 新增保留格式的分割方法
        splitFormattedAnalysisContent(text) {
            if (!text) return { modules: '', coverage: '', scale: '' };
            
            // 移除```标记，但保留内容
            const cleanText = text.replace(/```/g, '').trim();
            
            // 更加精确的分割点匹配，支持多种格式
            const modulePatterns = [
                /[-\s]*功能模块识别[:：]/i,
                /[-\s]*模块识别[:：]/i,
                /[\d\.\s]*功能模块识别/i,
                /^功能模块识别/im
            ];
            
            const coveragePatterns = [
                /[-\s]*测试覆盖策略[:：]/i,
                /[-\s]*覆盖策略[:：]/i,
                /[\d\.\s]*测试覆盖策略/i,
                /^测试覆盖策略/im
            ];
            
            const scalePatterns = [
                /[-\s]*预估用例规模[:：]/i,
                /[-\s]*用例规模[:：]/i,
                /[-\s]*生成策略[:：]/i,
                /[\d\.\s]*预估用例规模/i,
                /^预估用例规模/im
            ];
            
            let moduleStart = -1;
            let coverageStart = -1;
            let scaleStart = -1;
            
            // 按行查找分割点
            const lines = cleanText.split('\n');
            for (let i = 0; i < lines.length; i++) {
                const line = lines[i].trim();
                
                // 检查功能模块识别
                if (moduleStart === -1) {
                    for (const pattern of modulePatterns) {
                        if (pattern.test(line)) {
                            moduleStart = i;
                            break;
                        }
                    }
                }
                
                // 检查测试覆盖策略（必须在找到模块识别之后）
                if (coverageStart === -1 && moduleStart >= 0 && i > moduleStart) {
                    for (const pattern of coveragePatterns) {
                        if (pattern.test(line)) {
                            coverageStart = i;
                            break;
                        }
                    }
                }
                
                // 检查预估用例规模（必须在找到覆盖策略之后）
                if (scaleStart === -1 && coverageStart >= 0 && i > coverageStart) {
                    for (const pattern of scalePatterns) {
                        if (pattern.test(line)) {
                            scaleStart = i;
                            break;
                        }
                    }
                }
            }
            
            let result = { 
                modules: '', 
                coverage: '', 
                scale: '', 
                scaleFound: false,
                moduleFound: false,
                coverageFound: false 
            };
            
            // 基于找到的分割点进行内容分割
            if (moduleStart >= 0 && coverageStart >= 0 && scaleStart >= 0) {
                // 所有分割点都找到了
                result.modules = this.formatAnalysisSection(lines.slice(moduleStart, coverageStart));
                result.coverage = this.formatAnalysisSection(lines.slice(coverageStart, scaleStart));
                result.scale = this.formatAnalysisSection(lines.slice(scaleStart));
                result.moduleFound = true;
                result.coverageFound = true;
                result.scaleFound = true;
            } else {
                // 如果没有找到完整的分割点，使用智能推断
                console.log('Content split debug:', { moduleStart, coverageStart, scaleStart, totalLines: lines.length });
                
                // 尝试按内容特征分割
                let moduleEnd = -1;
                let coverageEnd = -1;
                
                // 查找模块复杂度评估结束位置
                for (let i = moduleStart >= 0 ? moduleStart : 0; i < lines.length; i++) {
                    const line = lines[i].toLowerCase();
                    if (line.includes('复杂度评估') || line.includes('模块复杂度')) {
                        // 向前查找下一个主要章节
                        for (let j = i + 1; j < lines.length; j++) {
                            const nextLine = lines[j].toLowerCase();
                            if (nextLine.includes('测试覆盖') || nextLine.includes('覆盖策略') || 
                                nextLine.includes('核心测试') || nextLine.includes('扩展测试')) {
                                moduleEnd = j;
                                coverageStart = j;
                                break;
                            }
                        }
                        break;
                    }
                }
                
                // 查找覆盖策略结束位置
                if (coverageStart >= 0) {
                    for (let i = coverageStart + 1; i < lines.length; i++) {
                        const line = lines[i].toLowerCase();
                        if (line.includes('预估用例') || line.includes('用例规模') || 
                            line.includes('生成策略') || line.includes('策略依据')) {
                            coverageEnd = i;
                            scaleStart = i;
                            break;
                        }
                    }
                }
                
                // 使用推断的分割点
                if (moduleEnd > 0 && coverageEnd > 0) {
                    result.modules = this.formatAnalysisSection(lines.slice(moduleStart >= 0 ? moduleStart : 0, moduleEnd));
                    result.coverage = this.formatAnalysisSection(lines.slice(coverageStart, coverageEnd));
                    result.scale = this.formatAnalysisSection(lines.slice(scaleStart));
                    result.moduleFound = moduleStart >= 0;
                    result.coverageFound = coverageStart >= 0;
                    result.scaleFound = scaleStart >= 0;
                } else {
                    // 最后的备选方案：只有在明确找到分割点时才标记为找到
                    if (moduleStart >= 0) {
                        const third = Math.floor(lines.length / 3);
                        result.modules = this.formatAnalysisSection(lines.slice(moduleStart, Math.min(coverageStart > 0 ? coverageStart : third, lines.length)));
                        result.moduleFound = true;
                    }
                    if (coverageStart >= 0) {
                        const startIdx = coverageStart;
                        const endIdx = scaleStart > 0 ? scaleStart : Math.floor(lines.length * 2 / 3);
                        result.coverage = this.formatAnalysisSection(lines.slice(startIdx, endIdx));
                        result.coverageFound = true;
                    }
                    if (scaleStart >= 0) {
                        result.scale = this.formatAnalysisSection(lines.slice(scaleStart));
                        result.scaleFound = true;
                    }
                }
            }
            
            // 只有当真正找到分割点时才设置默认内容
            if (!result.modules && result.moduleFound) {
                result.modules = '## 功能模块识别\n\n暂无相关内容';
            }
            if (!result.coverage && result.coverageFound) {
                result.coverage = '## 测试覆盖策略\n\n暂无相关内容';
            }
            if (!result.scale && result.scaleFound) {
                result.scale = '## 用例生成策略\n\n暂无相关内容';
            }
            
            return result;
        },

        // 格式化分析章节
        formatAnalysisSection(lines) {
            if (!lines || lines.length === 0) return '';
            
            let formattedLines = [];
            let currentSection = '';
            
            for (let i = 0; i < lines.length; i++) {
                let line = lines[i].trim();
                if (!line) continue;
                
                // 识别主要标题
                if (line.match(/^[-\s]*功能模块识别[:：]/i)) {
                    formattedLines.push('### 功能模块识别');
                    currentSection = 'modules';
                    // 检查是否有紧跟的内容
                    const nextContent = line.replace(/^[-\s]*功能模块识别[:：]\s*/i, '');
                    if (nextContent) {
                        formattedLines.push(nextContent);
                    }
                } else if (line.match(/^[-\s]*模块复杂度评估[:：]/i)) {
                    formattedLines.push('\n### 模块复杂度评估');
                    currentSection = 'complexity';
                    // 检查是否有紧跟的内容
                    const nextContent = line.replace(/^[-\s]*模块复杂度评估[:：]\s*/i, '');
                    if (nextContent) {
                        formattedLines.push(nextContent);
                    }
                } else if (line.match(/^[-\s]*测试覆盖策略[:：]/i)) {
                    formattedLines.push('### 测试覆盖策略');
                    currentSection = 'coverage';
                    // 检查是否有紧跟的内容
                    const nextContent = line.replace(/^[-\s]*测试覆盖策略[:：]\s*/i, '');
                    if (nextContent) {
                        formattedLines.push(nextContent);
                    }
                } else if (line.match(/^[-\s]*预估用例规模[:：]/i)) {
                    formattedLines.push('### 预估用例规模');
                    currentSection = 'scale';
                    // 检查是否有紧跟的内容
                    const nextContent = line.replace(/^[-\s]*预估用例规模[:：]\s*/i, '');
                    if (nextContent) {
                        formattedLines.push(nextContent);
                    }
                } else if (line.match(/^[-\s]*生成策略[:：]/i)) {
                    formattedLines.push('\n### 生成策略');
                    currentSection = 'strategy';
                    // 检查是否有紧跟的内容
                    const nextContent = line.replace(/^[-\s]*生成策略[:：]\s*/i, '');
                    if (nextContent) {
                        formattedLines.push(nextContent);
                    }
                } else if (line.match(/^[-\s]*策略依据[:：]/i)) {
                    formattedLines.push('\n### 策略依据');
                    currentSection = 'reason';
                    // 检查是否有紧跟的内容
                    const nextContent = line.replace(/^[-\s]*策略依据[:：]\s*/i, '');
                    if (nextContent) {
                        formattedLines.push(nextContent);
                    }
                } else if (line.match(/^[-\s]*批次规划[:：]/i)) {
                    formattedLines.push('\n### 批次规划');
                    currentSection = 'planning';
                    // 检查是否有紧跟的内容
                    const nextContent = line.replace(/^[-\s]*批次规划[:：]\s*/i, '');
                    if (nextContent) {
                        formattedLines.push(nextContent);
                    }
                } else if (line.match(/^[-\s]*核心测试[:：]/i)) {
                    formattedLines.push('\n#### 核心测试');
                    // 检查是否有紧跟的内容
                    const nextContent = line.replace(/^[-\s]*核心测试[:：]\s*/i, '');
                    if (nextContent) {
                        formattedLines.push(nextContent);
                    }
                } else if (line.match(/^[-\s]*扩展测试[:：]/i)) {
                    formattedLines.push('\n#### 扩展测试');
                    // 检查是否有紧跟的内容
                    const nextContent = line.replace(/^[-\s]*扩展测试[:：]\s*/i, '');
                    if (nextContent) {
                        formattedLines.push(nextContent);
                    }
                } else if (line.match(/^[-\s]*策略说明[:：]/i)) {
                    formattedLines.push('\n#### 策略说明');
                    // 检查是否有紧跟的内容
                    const nextContent = line.replace(/^[-\s]*策略说明[:：]\s*/i, '');
                    if (nextContent) {
                        formattedLines.push(nextContent);
                    }
                } else {
                    // 普通内容行
                    // 移除开头的-符号
                    line = line.replace(/^[-\s]+/, '');
                    
                    if (line.length > 0) {
                        formattedLines.push(line);
                    }
                }
            }
            
            return formattedLines.join('\n');
        },

        stripMarkdown(text) {
            if (!text) return '';
            
            return text
                // 移除标题标记
                .replace(/^#{1,6}\s+/gm, '')
                // 移除加粗
                .replace(/\*\*(.*?)\*\*/g, '$1')
                .replace(/__(.*?)__/g, '$1')
                // 移除斜体  
                .replace(/\*(.*?)\*/g, '$1')
                .replace(/_(.*?)_/g, '$1')
                // 移除代码标记，但保留内容
                .replace(/```/g, '')
                .replace(/`(.*?)`/g, '$1')
                // 移除链接格式，保留文本
                .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
                // 移除列表标记
                .replace(/^[\s]*[-*+]\s+/gm, '')
                .replace(/^\d+\.\s+/gm, '')
                // 移除引用标记
                .replace(/^>\s+/gm, '')
                // 清理多余空行
                .replace(/\n{3,}/g, '\n\n')
                .trim();
        },

        // 内容模式识别辅助方法
        containsQuestionPatterns(content) {
            if (!content) return false;
            const patterns = [
                '问题标题', '确认点', '需要确认', '请确认',
                '问题列表', '确认项', '以下问题', '？',
                '请回答', '确认以下', '需要澄清'
            ];
            return patterns.some(pattern => content.includes(pattern));
        },

        containsAnalysisPatterns(content) {
            if (!content) return false;
            const patterns = [
                'PRD智能分析报告', '智能分析', '分析报告', '测试分析',
                '分析结果', '综合分析', '深度分析', '专业分析',
                '测试覆盖度', '风险评估', '测试策略'
            ];
            return patterns.some(pattern => content.includes(pattern));
        },

        containsTestingTerms(content) {
            if (!content) return false;
            const terms = [
                '测试用例', '测试场景', '边界测试', '异常测试',
                '性能测试', '功能测试', '集成测试', '单元测试',
                '测试覆盖率', '测试方案', '测试计划', '质量保证',
                '缺陷', 'bug', '验证', '校验'
            ];
            return terms.some(term => content.includes(term));
        },

        // 获取人工确认完成时间
        getConfirmationCompleteTime() {
            // 如果有提交的确认结果，尝试获取提交时间
            if (this.submittedConfirmationResults && this.submittedConfirmationResults.length > 0) {
                // 可以基于确认结果的时间戳或其他标志来确定
                return new Date(); // 简化处理，假设是当前时间前
            }
            
            // 如果有人工确认的消息，找到最后一个确认消息的时间
            for (let i = this.agentMessages.length - 1; i >= 0; i--) {
                const message = this.agentMessages[i];
                const sender = (message.role || '').toLowerCase();
                const content = message.content || '';
                
                if (sender.includes('human') || sender.includes('user') ||
                    content.includes('确认') || content.includes('回答')) {
                    return new Date(message.timestamp || 0);
                }
            }
            
            return null;
        },

        isLongMessage(content) {
            if (!content) return false;
            const cleanContent = this.cleanPrdMarkers(content);
            return cleanContent.length > 500;
        },

        getMessagePreview(content) {
            if (!content) return '';
            // 清理PRD标记后返回前200个字符作为预览
            const cleanContent = this.cleanPrdMarkers(content);
            return cleanContent.substring(0, 200) + (cleanContent.length > 200 ? '...' : '');
        },

        isMessageExpanded(key) {
            return this.expandedMessages[key] || false;
        },

        toggleMessageExpansion(key) {
            this.$set(this.expandedMessages, key, !this.expandedMessages[key]);
        },

        // 人工确认项相关方法
        getPriorityType(priority) {
            if (!priority) return 'info';
            const p = priority.toString().toLowerCase();
            if (p.includes('high') || p.includes('urgent') || p.includes('critical')) {
                return 'danger';
            } else if (p.includes('medium') || p.includes('normal')) {
                return 'warning';
            } else if (p.includes('low')) {
                return 'info';
            }
            return 'info';
        },

        getPriorityText(priority) {
            if (!priority) return '一般';
            const p = priority.toString().toLowerCase();
            if (p.includes('high') || p.includes('urgent') || p.includes('critical')) {
                return '高优先级';
            } else if (p.includes('medium') || p.includes('normal')) {
                return '中等优先级';
            } else if (p.includes('low')) {
                return '低优先级';
            }
            return priority;
        },

        getAnswerPlaceholder(item) {
            if (item.placeholder) {
                return item.placeholder;
            }
            if (item.answer_requirement) {
                return item.answer_requirement;
            }
            
            if (item.type) {
                const type = item.type.toLowerCase();
                if (type.includes('functional')) {
                    return '请详细描述功能需求、使用场景和预期行为...';
                } else if (type.includes('performance')) {
                    return '请描述性能要求、响应时间、并发量等...';
                } else if (type.includes('security')) {
                    return '请说明安全要求、权限控制、数据保护等...';
                } else if (type.includes('interface') || type.includes('ui')) {
                    return '请描述界面要求、交互方式、用户体验等...';
                }
            }
            
            return '请详细描述您的回答，这将帮助AI更好地理解您的需求和生成准确的测试用例...';
        },

        // 提交确认回答
        submitConfirmation(event) {
            // 阻止默认行为和事件冒泡
            if (event) {
                event.preventDefault();
                event.stopPropagation();
            }
            
            if (!this.selectedTask) return;

            // 验证必填项
            const unansweredItems = [];
            this.confirmationItems.forEach((item, index) => {
                const answer = this.confirmationResponses[`answer_${index}`];
                if (!answer || answer.trim() === '') {
                    unansweredItems.push(index + 1);
                }
            });

            if (unansweredItems.length > 0) {
                this.$message.warning(`请回答第 ${unansweredItems.join(', ')} 个问题`);
                return;
            }

            const taskId = this.currentTaskRequestId || this.getTaskId(this.selectedTask);
            this.isLoading = true;

            // 保存提交的确认结果用于显示
            const submittedResults = [];
            this.confirmationItems.forEach((item, index) => {
                submittedResults.push({
                    question: item.question || item.title,
                    description: item.description,
                    confirm_points: item.confirm_points || [],
                    reference_examples: item.reference_examples || [],
                    answer: this.confirmationResponses[`answer_${index}`]
                });
            });

            axios.post(`${apiBaseUrl}/tasks/${taskId}/confirm`, this.confirmationResponses)
                .then(response => {
                    this.isLoading = false;
                    if (response.data && response.data.success) {
                        this.$message.success('确认提交成功，AI将继续处理您的任务');
                        
                        // 保存已提交的确认结果用于显示
                        this.submittedConfirmationResults = submittedResults;
                        
                        // 保存当前滚动位置
                        const currentScrollTop = window.pageYOffset || document.documentElement.scrollTop;
                        
                        // 标记确认已提交，但不清空确认项，避免DOM突然变化
                        this.confirmationSubmitted = true;
                        
                        // 在DOM更新后恢复滚动位置
                        this.$nextTick(() => {
                            window.scrollTo(0, currentScrollTop);
                        });
                        
                        // 刷新任务状态以获取最新数据
                        setTimeout(() => {
                            // 只获取消息列表，不重新获取确认项
                            this.fetchTaskMessages(taskId);
                            
                            // 轻量级更新任务状态
                            this.pollTaskStatus(taskId);
                        }, 500);
                        
                        // 更新任务状态
                        this.selectedTask.status = 'processing';
                        
                        // 开始轮询
                        this.startTaskPolling(taskId);
                        
                        // 保持在确认项标签页，显示已提交的结果
                        this.taskDetailTab = 'confirmationItems';
                    } else {
                        this.$message.error('确认提交失败: ' + (response.data.message || '未知错误'));
                    }
                })
                .catch(error => {
                    this.isLoading = false;
                    console.error('提交确认时发生错误:', error);
                    this.$message.error('提交确认时发生错误: ' + (error.message || '未知网络错误'));
                });
        }
    }
});
