/**
 * 会话模块 — 豆包式多轮对话
 */

Vue.component('chat-session-module', {
    template: `
        <div class="chat-session-module">
            <aside class="chat-session-sidebar">
                <div class="chat-session-sidebar-header">
                    <h3>会话</h3>
                    <el-button
                        type="primary"
                        size="small"
                        icon="el-icon-plus"
                        class="chat-session-new-btn"
                        :loading="creatingSession"
                        @click="createNewSession"
                    >新建对话</el-button>
                </div>
                <div class="chat-session-list" v-loading="sessionsLoading">
                    <div v-if="!sessions.length && !sessionsLoading" class="chat-session-empty-list">
                        暂无会话，点击上方新建
                    </div>
                    <div
                        v-for="item in sessions"
                        :key="item.id"
                        :class="['chat-session-item', { active: currentSessionId === item.id }]"
                        @click="selectSession(item.id)"
                    >
                        <i class="el-icon-chat-dot-round" style="color: var(--ac-primary); flex-shrink: 0;"></i>
                        <span class="chat-session-item-title" :title="item.title">{{ item.title }}</span>
                        <i
                            class="el-icon-delete chat-session-item-delete"
                            @click.stop="deleteSession(item.id)"
                        ></i>
                    </div>
                </div>
            </aside>

            <section class="chat-session-main">
                <header class="chat-session-main-header" v-if="currentSession">
                    <h2>{{ currentSession.title }}</h2>
                    <span style="font-size: 12px; color: var(--ac-text-muted);" v-if="currentSession.model_name">
                        {{ currentSession.model_name }}
                    </span>
                </header>

                <div class="chat-session-messages" ref="messagesContainer">
                    <div v-if="!currentSessionId" class="chat-session-welcome">
                        <div class="chat-session-welcome-icon">💬</div>
                        <h3>AI 智能会话</h3>
                        <p>选择左侧会话或新建对话，与 AI 自由交流测试、需求与用例相关问题。</p>
                        <div class="chat-session-suggestions">
                            <span
                                v-for="tip in quickTips"
                                :key="tip"
                                class="chat-session-suggestion"
                                @click="useQuickTip(tip)"
                            >{{ tip }}</span>
                        </div>
                    </div>

                    <template v-else>
                        <div
                            v-for="msg in messages"
                            :key="msg.id"
                            :class="['chat-msg-row', msg.role]"
                        >
                            <div class="chat-msg-avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
                            <div
                                class="chat-msg-bubble markdown-body"
                                v-if="msg.role === 'assistant'"
                                v-html="renderMarkdown(msg.content)"
                            ></div>
                            <div class="chat-msg-bubble" v-else>{{ msg.content }}</div>
                        </div>
                        <div v-if="sending" class="chat-msg-row assistant">
                            <div class="chat-msg-avatar">AI</div>
                            <div class="chat-msg-bubble">
                                <div class="chat-msg-typing">
                                    <span></span><span></span><span></span>
                                </div>
                            </div>
                        </div>
                    </template>
                </div>

                <footer class="chat-session-input-area">
                    <div class="chat-session-input-wrap">
                        <el-input
                            type="textarea"
                            :rows="3"
                            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
                            v-model="inputText"
                            :disabled="!currentSessionId || sending"
                            @keydown.native="handleKeydown"
                        ></el-input>
                        <el-button
                            type="primary"
                            class="chat-session-send-btn"
                            :loading="sending"
                            :disabled="!currentSessionId || !inputText.trim()"
                            @click="sendMessage"
                        >发送</el-button>
                    </div>
                </footer>
            </section>
        </div>
    `,
    data: function () {
        return {
            sessions: [],
            sessionsLoading: false,
            creatingSession: false,
            currentSessionId: null,
            messages: [],
            messagesLoading: false,
            inputText: '',
            sending: false,
            quickTips: [
                '如何写好测试用例？',
                '帮我梳理 PRD 测试点',
                '边界值分析方法',
                '回归测试策略建议'
            ]
        };
    },
    computed: {
        currentSession: function () {
            var self = this;
            return this.sessions.find(function (s) { return s.id === self.currentSessionId; }) || null;
        }
    },
    mounted: function () {
        this.loadSessions();
    },
    methods: {
        apiOk: function (response) {
            return response && response.data && (response.data.success === true || response.data.code === 0);
        },
        getData: function (response) {
            return (response && response.data && response.data.data) || {};
        },

        loadSessions: function () {
            var self = this;
            self.sessionsLoading = true;
            axios.get(apiBaseUrl + '/chat/sessions')
                .then(function (response) {
                    if (self.apiOk(response)) {
                        var data = self.getData(response);
                        self.sessions = data.sessions || [];
                    }
                })
                .catch(function (err) {
                    self.$message.error('加载会话列表失败');
                    console.error(err);
                })
                .finally(function () {
                    self.sessionsLoading = false;
                });
        },

        createNewSession: function () {
            var self = this;
            self.creatingSession = true;
            axios.post(apiBaseUrl + '/chat/sessions', {})
                .then(function (response) {
                    if (self.apiOk(response)) {
                        var session = self.getData(response);
                        self.sessions.unshift(session);
                        self.selectSession(session.id);
                        self.$message.success('已创建新对话');
                    } else {
                        self.$message.error((response.data && response.data.error) || '创建失败');
                    }
                })
                .catch(function (err) {
                    self.$message.error('创建会话失败');
                    console.error(err);
                })
                .finally(function () {
                    self.creatingSession = false;
                });
        },

        selectSession: function (sessionId) {
            this.currentSessionId = sessionId;
            this.loadMessages(sessionId);
        },

        deleteSession: function (sessionId) {
            var self = this;
            self.$confirm('确定删除该会话？', '提示', {
                confirmButtonText: '删除',
                cancelButtonText: '取消',
                type: 'warning'
            }).then(function () {
                return axios.delete(apiBaseUrl + '/chat/sessions/' + sessionId);
            }).then(function (response) {
                if (self.apiOk(response)) {
                    self.sessions = self.sessions.filter(function (s) { return s.id !== sessionId; });
                    if (self.currentSessionId === sessionId) {
                        self.currentSessionId = null;
                        self.messages = [];
                    }
                    self.$message.success('已删除');
                }
            }).catch(function (err) {
                if (err !== 'cancel') {
                    self.$message.error('删除失败');
                }
            });
        },

        loadMessages: function (sessionId) {
            var self = this;
            self.messagesLoading = true;
            axios.get(apiBaseUrl + '/chat/sessions/' + sessionId + '/messages')
                .then(function (response) {
                    if (self.apiOk(response)) {
                        var data = self.getData(response);
                        self.messages = data.messages || [];
                        self.$nextTick(self.scrollToBottom);
                    }
                })
                .catch(function (err) {
                    self.$message.error('加载消息失败');
                    console.error(err);
                })
                .finally(function () {
                    self.messagesLoading = false;
                });
        },

        sendMessage: function () {
            var text = (this.inputText || '').trim();
            if (!text || !this.currentSessionId || this.sending) return;

            var self = this;
            var sessionId = this.currentSessionId;
            self.sending = true;
            self.inputText = '';

            var tempUser = {
                id: 'temp-' + Date.now(),
                role: 'user',
                content: text,
                created_at: new Date().toISOString()
            };
            self.messages.push(tempUser);
            self.$nextTick(self.scrollToBottom);

            axios.post(apiBaseUrl + '/chat/sessions/' + sessionId + '/messages', { content: text })
                .then(function (response) {
                    if (self.apiOk(response)) {
                        var data = self.getData(response);
                        if (data.session) {
                            var idx = self.sessions.findIndex(function (s) { return s.id === data.session.id; });
                            if (idx >= 0) {
                                self.$set(self.sessions, idx, data.session);
                            }
                        }
                        self.messages = self.messages.filter(function (m) { return m.id !== tempUser.id; });
                        if (data.user_message) self.messages.push(data.user_message);
                        if (data.assistant_message) self.messages.push(data.assistant_message);
                        self.$nextTick(self.scrollToBottom);
                    } else {
                        self.messages = self.messages.filter(function (m) { return m.id !== tempUser.id; });
                        self.inputText = text;
                        self.$message.error((response.data && response.data.error) || '发送失败');
                    }
                })
                .catch(function (err) {
                    self.messages = self.messages.filter(function (m) { return m.id !== tempUser.id; });
                    self.inputText = text;
                    var msg = (err.response && err.response.data && err.response.data.error) || '发送失败，请检查模型配置';
                    self.$message.error(msg);
                    console.error(err);
                })
                .finally(function () {
                    self.sending = false;
                });
        },

        handleKeydown: function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        },

        useQuickTip: function (tip) {
            var self = this;
            if (!this.currentSessionId) {
                this.createNewSession();
                var unwatch = this.$watch('currentSessionId', function (id) {
                    if (id) {
                        unwatch();
                        self.inputText = tip;
                        self.sendMessage();
                    }
                });
            } else {
                this.inputText = tip;
                this.sendMessage();
            }
        },

        renderMarkdown: function (content) {
            if (typeof safeRenderMarkdown === 'function') {
                return safeRenderMarkdown(content);
            }
            return (content || '').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
        },

        scrollToBottom: function () {
            var el = this.$refs.messagesContainer;
            if (el) {
                el.scrollTop = el.scrollHeight;
            }
        }
    }
});
