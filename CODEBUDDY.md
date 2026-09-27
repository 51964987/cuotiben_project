# 项目说明（错题本）

面向五年级学生的错题收集与重做打印工具。核心链路：手机拍照录入（智谱 GLM-4V 识别题干与答案）→ 本地题库（SQLite）→ 重新排版生成干净 A4 重做卷（浏览器打印，答案页置后）→ 家长批改驱动「重复出错优先、间隔重出、连续做对移出」。

## 技术栈

Python FastAPI + SQLite + Jinja2 + 原生前端（KaTeX 渲染公式）；单机局域网部署，监听 `0.0.0.0:8000`，数据全部存本地 `data\` 目录。

## 目录结构

- `app\main.py`：全部路由；`app\db.py`：数据库表结构与间隔选题逻辑；`app\ai.py`：GLM-4V 拍照识别
- `app\templates\`：页面（含 A4 打印排版）；`app\static\`：样式与图形框选裁剪脚本
- `data\`：运行时数据——`cuotiben.db`、`photos\`（原照片）、`figures\`（裁剪图形），备份此目录即可

## 常用命令

- 启动服务：`start.bat` 或 `python run.py`（启动前自动清理 8000 端口占用进程）
- 安装依赖：`pip install -r requirements.txt`

## 共享实现索引

- 建表与库连接：`app\db.py` 的 `init_db` / `get_db`（全项目唯一建表点）
- 类型收窄助手：`app\db.py` 的 `_fetchone` / `_fetchall` / `_s` / `_i`（业务代码取行取列唯一入口，路由层禁止裸 `conn.execute`；题库 / 组卷 / 批改的数据访问函数也集中在 `app\db.py`）
- 答案归一化与自动判分：`app\db.py` 的 `normalize_answer` / `answers_equal`（变式练习判分唯一实现，勿另写比对逻辑）
- 间隔选题：`app\db.py` 的 `eligible_questions`（组卷选题唯一实现）
- GLM-4V 拍照识别：`app\ai.py`（全项目唯一 AI 调用点；`recognize_question` 返回 TypedDict `Recognition`）

## 文档与规则

- 行为约束（角色定位 / 核心约束 / 通用工程约束）：`.codebuddy/rules/cuotiben-core/RULE.mdc`（alwaysApply: true，每会话生效）
- 工程教训归档：`docs/lessons-learned.md`（按「原 N」编号体系续号沉淀）
- 使用说明：`README.md`
