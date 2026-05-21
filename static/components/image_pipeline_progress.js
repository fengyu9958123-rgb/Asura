/**
 * 图片流程进度对话框组件
 * 可在任务管理和需求模块生成中复用
 */
Vue.component('image-pipeline-progress', {
    props: {
        visible: {
            type: Boolean,
            default: false
        },
        moduleId: {
            type: String,
            required: true
        }
    },
    
    template: `
        <div>
            <!-- 进度对话框 -->
            <el-dialog
                title="生成测试用例"
                :visible.sync="dialogVisible"
                width="600px"
                :close-on-click-modal="false"
                :close-on-press-escape="false"
                :show-close="['waiting_confirmation', 'completed', 'failed'].includes(progress.status)"
                @close="handleClose"
            >
                <div v-if="progress.status === 'processing'">
                    <el-progress 
                        :percentage="progress.progress" 
                        :status="progress.progress === 100 ? 'success' : null"
                    ></el-progress>
                    <div style="margin-top: 20px; color: #606266;">
                        <p><strong>当前阶段:</strong> {{ getStageName(progress.processing_stage) }}</p>
                        <p style="margin-top: 10px; font-size: 13px; color: #909399;">
                            {{ getStageDescription(progress.processing_stage) }}
                        </p>
                    </div>
                </div>

                <div v-else-if="progress.status === 'waiting_confirmation'">
                    <el-result
                        icon="warning"
                        title="等待人工确认"
                        subTitle="PRD审核已完成，需要先回答确认问题后继续生成测试用例"
                    >
                    </el-result>
                    <div style="text-align: center; margin-top: 20px;">
                        <el-button type="warning" @click="goToConfirmation">去确认</el-button>
                        <el-button @click="closeDialog">关闭</el-button>
                    </div>
                </div>
                
                <div v-else-if="progress.status === 'completed'">
                    <el-result
                        icon="success"
                        title="生成完成"
                        subTitle="测试用例已成功生成"
                    >
                    </el-result>
                    <div style="text-align: center; margin-top: 20px;">
                        <el-button type="primary" @click="viewResults">查看结果</el-button>
                        <el-button @click="closeDialog">关闭</el-button>
                    </div>
                </div>
                
                <div v-else-if="progress.status === 'failed'">
                    <el-result
                        icon="error"
                        title="生成失败"
                        :subTitle="progress.error_message || '未知错误'"
                    >
                    </el-result>
                    <div style="text-align: center; margin-top: 20px;">
                        <el-button @click="closeDialog">关闭</el-button>
                    </div>
                </div>
            </el-dialog>
            
            <!-- 结果对话框 -->
            <el-dialog
                title="测试用例生成结果"
                :visible.sync="resultsVisible"
                width="90%"
                :append-to-body="true"
                top="5vh"
            >
                <el-tabs v-model="resultsActiveTab">
                    <el-tab-pane label="测试用例" name="testcases">
                        <div v-if="results.test_cases_raw" class="markdown-content">
                            <div v-html="renderMarkdown(results.test_cases_raw)"></div>
                        </div>
                        <el-empty v-else description="暂无测试用例"></el-empty>
                    </el-tab-pane>
                    
                    <el-tab-pane label="最终PRD" name="prd">
                        <div v-if="results.prd_final" class="markdown-content">
                            <div v-html="renderMarkdown(results.prd_final)"></div>
                        </div>
                        <el-empty v-else description="暂无PRD内容"></el-empty>
                    </el-tab-pane>
                    
                    <el-tab-pane label="测试分析" name="analysis">
                        <div v-if="results.test_analysis" class="markdown-content">
                            <div v-html="renderMarkdown(results.test_analysis)"></div>
                        </div>
                        <el-empty v-else description="暂无测试分析"></el-empty>
                    </el-tab-pane>
                    
                    <el-tab-pane label="文件下载" name="files">
                        <el-descriptions :column="1" border>
                            <el-descriptions-item label="PRD文件">
                                <span v-if="results.prd_file_path">
                                    {{ results.prd_file_path }}
                                    <el-button type="text" size="small" @click="downloadFile(results.prd_file_path)">
                                        下载
                                    </el-button>
                                </span>
                                <span v-else>-</span>
                            </el-descriptions-item>
                            <el-descriptions-item label="测试用例文件">
                                <span v-if="results.test_cases_file_path">
                                    {{ results.test_cases_file_path }}
                                    <el-button type="text" size="small" @click="downloadFile(results.test_cases_file_path)">
                                        下载
                                    </el-button>
                                </span>
                                <span v-else>-</span>
                            </el-descriptions-item>
                        </el-descriptions>
                    </el-tab-pane>
                </el-tabs>
            </el-dialog>
        </div>
    `,
    
    data() {
        return {
            dialogVisible: false,
            progress: {
                status: 'processing',
                progress: 0,
                processing_stage: '',
                task_id: null,
                error_message: ''
            },
            progressTimer: null,
            resultsVisible: false,
            resultsActiveTab: 'testcases',
            results: {
                test_cases_raw: '',
                prd_final: '',
                test_analysis: '',
                prd_file_path: '',
                test_cases_file_path: ''
            }
        };
    },
    
    watch: {
        visible(newVal) {
            this.dialogVisible = newVal;
            if (newVal) {
                this.startProgressPolling();
            } else {
                this.stopProgressPolling();
            }
        },
        dialogVisible(newVal) {
            if (!newVal) {
                this.$emit('update:visible', false);
            }
        }
    },
    
    beforeDestroy() {
        this.stopProgressPolling();
    },
    
    methods: {
        startProgressPolling() {
            // 清除已有计时器
            if (this.progressTimer) {
                clearInterval(this.progressTimer);
            }
            
            // 立即查询一次
            this.fetchProgress();
            
            // 每2秒查询一次进度
            this.progressTimer = setInterval(() => {
                this.fetchProgress();
            }, 2000);
        },
        
        async fetchProgress() {
            try {
                const response = await axios.get(`/api/image-pipeline/progress/${this.moduleId}`);
                
                if (response.data.code === 0) {
                    const data = response.data.data;
                    
                    this.progress = {
                        status: data.status,
                        progress: data.progress || 0,
                        processing_stage: data.processing_stage || '',
                        task_id: data.task_id,
                        error_message: data.error_message || ''
                    };
                    
                    // 如果进入人工确认、完成或失败，停止轮询
                    if (['waiting_confirmation', 'completed', 'failed'].includes(data.status)) {
                        this.stopProgressPolling();
                        // 通知父组件刷新
                        this.$emit('progress-complete', data.status);
                    }
                }
            } catch (error) {
                console.error('获取进度失败:', error);
            }
        },
        
        stopProgressPolling() {
            if (this.progressTimer) {
                clearInterval(this.progressTimer);
                this.progressTimer = null;
            }
        },

        goToConfirmation() {
            if (!this.progress.task_id) {
                this.$message.warning('未找到任务ID，请从统一任务列表进入确认页');
                return;
            }
            this.closeDialog();
            this.$root.$emit('view-task-detail', this.progress.task_id);
        },
        
        async viewResults() {
            try {
                const response = await axios.get(`/api/image-pipeline/results/${this.moduleId}`);
                
                if (response.data.code === 0) {
                    const data = response.data.data;
                    
                    this.results = {
                        test_cases_raw: data.test_cases_raw || '',
                        prd_final: data.prd_final || '',
                        test_analysis: data.test_analysis || '',
                        prd_file_path: data.prd_file_path || '',
                        test_cases_file_path: data.test_cases_file_path || ''
                    };
                    
                    // 关闭进度对话框，打开结果对话框
                    this.dialogVisible = false;
                    this.resultsVisible = true;
                    this.resultsActiveTab = 'testcases';
                } else {
                    this.$message.error(response.data.message || '获取结果失败');
                }
            } catch (error) {
                console.error('获取结果失败:', error);
                this.$message.error('获取结果失败: ' + (error.response?.data?.message || error.message));
            }
        },
        
        getStageName(stage) {
            const stageNames = {
                'initializing': '初始化',
                'analyzing_images': '图片分析',
                'generating_prd': 'PRD生成',
                'reviewing_prd': 'PRD审核',
                'auto_confirming': '自动确认',
                'integrating_confirmations': '确认集成',
                'waiting_confirmation': '等待确认',
                'generating_testcases': '测试用例生成',
                'saving_results': '结果保存',
                'completed': '已完成'
            };
            return stageNames[stage] || stage;
        },
        
        getStageDescription(stage) {
            const descriptions = {
                'initializing': '正在准备分析环境...',
                'analyzing_images': '正在使用AI分析上传的图片，识别功能需求...',
                'generating_prd': '正在根据图片分析结果生成产品需求文档...',
                'reviewing_prd': '正在审核PRD文档，提取确认问题...',
                'auto_confirming': '正在自动确认问题...',
                'integrating_confirmations': '正在将确认结果集成到PRD中...',
                'waiting_confirmation': '等待人工确认后继续生成测试用例...',
                'generating_testcases': '正在根据最终PRD生成测试用例...',
                'saving_results': '正在保存生成结果...',
                'completed': '所有步骤已完成！'
            };
            return descriptions[stage] || '处理中...';
        },
        
        downloadFile(filePath) {
            if (!filePath) return;
            window.open('/' + filePath, '_blank');
        },
        
        renderMarkdown(content) {
            if (!content) return '';
            return marked.parse(content);
        },
        
        closeDialog() {
            this.dialogVisible = false;
        },
        
        handleClose() {
            this.stopProgressPolling();
            this.$emit('update:visible', false);
        }
    }
});
