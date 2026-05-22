# 部署说明

Spec2Case 是面向 QA、测试开发、产品和研发团队的生产级 AI 测试用例生成平台，可将 PRD、需求文档、产品规格说明、原型图、设计稿和业务截图转换为结构化、可执行、可导出的测试用例。

这不是一个开源 demo 或概念验证项目，而是从真实业务测试交付中迭代出来的 AI 用例生成智能体。项目经过 80+ 小需求、十几个大版本需求验证，生成测试用例可用率达 90%+，适合直接进入测试设计、用例评审和回归测试准备流程。

## Docker Compose

推荐使用 Docker Compose 和快速启动脚本部署。脚本支持 Ubuntu 20.04/22.04/24.04 等主流 Ubuntu 系统和 macOS。

```bash
git clone https://github.com/fengyu9958123-rgb/Asura.git
cd spec2case
bash scripts/quick-start.sh
```

自定义端口和持久化目录：

```bash
SPEC2CASE_PORT=8080 SPEC2CASE_DATA_DIR=/data/spec2case bash scripts/quick-start.sh
```

访问 `http://localhost:5002`。

首次打开页面后，先进入“模型配置”完成三类模型配置。Spec2Case 不是简单调用一次大模型写用例，流程包含需求审查、人工确认、PRD 整合、需求拆分和用例生成，模型能力会直接影响用例覆盖度和可执行性。

| 用途 | 推荐模型 | 作用 | 选型建议 |
| --- | --- | --- | --- |
| 需求拆分模型 | GPT-5.5 或同等级/更强模型 | PRD 分块、LU 拆分、跨模块链路识别 | 优先使用最新一代顶级模型，避免拆分不完整导致漏测 |
| 需求/测试用例模型 | DeepSeek V4 Pro 或同等级/更强模型 | 需求审查、确认整合、最终 PRD、测试用例生成 | 调用量最大，建议选择质量稳定、成本可控的一线模型 |
| 图片分析模型 | Doubao Seed 2.0 Pro 或同等级/更强视觉模型 | 原型图、设计稿、截图、箭头备注和文件名语义提取 | 处理图片需求时必需，模型弱会造成图片事实遗漏或误读 |

费用参考：按当前推荐配置，常见单任务约 1-2 元。实际费用取决于模型、需求长度和图片数量，页面“AI 协作运行”会展示任务估算费用。

查看日志：

```bash
docker compose logs -f --tail=200
```

停止：

```bash
docker compose down
```

## 模型配置

模型配置文件：

```text
runtime/config/OAI_CONFIG_LIST
```

页面也支持在“模型配置”中新增、修改和测试模型。当前支持三类用途：

- 需求拆分模型：推荐 GPT-5.5 或同等级/更强模型，用于需求分块、LU 拆分和链路识别。
- 需求/测试用例模型：推荐 DeepSeek V4 Pro 或同等级/更强模型，用于需求整理、审查、确认整合和测试用例生成。
- 图片分析模型：推荐 Doubao Seed 2.0 Pro 或同等级/更强视觉模型，用于图片需求理解。

每一项保存后都建议点击“测试”。如果某一类模型未配置或连通性失败，相关任务阶段会失败或无法生成稳定结果。

详细使用步骤见 [使用手册](USER_MANUAL.md)。

修改配置后重启容器：

```bash
docker compose restart
```

## 持久化目录

生产环境需要持久化：

- `data/`：SQLite 数据库。
- `uploads/`：上传的需求文件和图片。
- `outputs/`：生成结果。
- `logs/`：运行日志。
- `config/`：模型配置。

## 常见环境变量

```text
SPEC2CASE_PORT=5002
SPEC2CASE_DATA_DIR=/data/spec2case
LOG_LEVEL=INFO
SHOW_AI_COLLABORATION=True
```

页面默认展示 LangGraph 执行过程和模型输入输出，方便理解生成链路。

## 本地开发

环境要求：

- Python 3.11+
- 可访问的 OpenAI-compatible 模型服务

步骤：

```bash
git clone https://github.com/fengyu9958123-rgb/Asura.git
cd spec2case
# 创建 Python 虚拟环境 使用 venv 模块在当前目录下创建一个名为 .venv 的虚拟环境，用于隔离项目依赖，避免污染系统 Python 环境。
python3 -m venv .venv
# 激活虚拟环境 在 macOS / Linux 下激活虚拟环境。激活后，终端提示符前会显示 (.venv)，并且后续的 python、pip 命令都将使用该环境下的版本  pycharm可忽略 windows 使用cmd
source .venv/bin/activate
# 安装项目依赖 根据 requirements.txt 文件中列出的包名和版本，一次性安装项目所需的所有第三方库。
pip install -r requirements.txt
# 复制配置文件模板 将示例配置文件 OAI_CONFIG_LIST.example 复制为正式配置文件 OAI_CONFIG_LIST（通常用于存储大模型 API 的配置信息，如千问、OpenAI 的密钥和端点）。
cp config/OAI_CONFIG_LIST.example config/OAI_CONFIG_LIST
# 初始化数据库 运行 database/init_db.py 脚本，并传入参数 init，用于创建或初始化项目所需的数据库表结构
python database/init_db.py init
# 启动项目
./start.sh
```
