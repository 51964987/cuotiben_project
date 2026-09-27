# 工程教训归档（错题本项目）

> 编号体系：沿用规则拆分前的「原 N」编号。原 1-7 为规则迁移时与 `.codebuddy/rules/cuotiben-core/RULE.mdc` 通用工程约束 1-7 条直接对应（无独立触发案例文档）；新教训从原 8 起续号，先写入本文件，再在规则文件加/改一行规则。

---

## 原 8：数据库建表 DDL 必须中文注释（表级 + 列级）

- **日期**：2026-09-27
- **触发场景**：任何新建或修改数据库表结构（`CREATE TABLE` / `ALTER TABLE`）时。
- **强制动作**：
  1. 每张表必须有表级注释，说明表的用途与在业务链路中的位置；
  2. 每一列必须有行内注释，说明含义、取值范围 / 枚举值、默认值语义；
  3. SQLite 不支持 `COMMENT` 语法，统一用 `--` 行注释实现；注释写在 DDL 源码中，即建表语句的权威文档，禁止只在别处口头/文档描述。
- **本项目实例**：2026-09-27 检查发现 `app/db.py` 的 7 张表（questions / papers / paper_items / attempts / settings / variant_batches / variant_items）中仅 variant_batches、variant_items 有表级注释，列注释大部分缺失，读者无法直接从 DDL 理解 `wrong_count` / `consecutive_correct` / `status` 枚举等字段语义。已全部补齐并沉淀为本条规则。
- **验证方式**：检查 `app/db.py` 建表脚本，每张表、每列均有中文注释；`py_compile` 通过且服务启动建表正常（注释不改变 schema，无需迁移）。

---

## 规则本地化记录（2026-09-27）

规则从 txxy_test 迁移时带入多处本项目不存在的场景词汇，经比对确认后移除/改写（规则条目编号不变）：

- **原 2**：删 `vue-tsc --noEmit`（本项目纯原生前端，无 Vue / 无构建）；删「SPA 兜底吞未知路径」（`main.py` 全部路由显式声明，无 catch-all）；删「环境变量清单见归档原 47」（原 47 属 txxy_test 编号，本项目归档无此条）；删「接口验证必须带 `/api` 前缀」（本项目页面路由无 `/api` 前缀，全部为表单提交 + 重定向形态）；「`@router.*` 枚举」改为「`@app.*` 或 `@router.*`」（本项目用 `@app.get/post`）。
- **原 6**：删「令牌与取消分支」「补提交循环条件」「非终态收尾窗口禁止重新入队」（本项目无异步任务 / 令牌 / 取消机制）；状态机词汇本地化为 questions 的 active/mastered、变式批次 pending/all_right/has_wrong、papers 的 graded。
- **原 1**：「共享实现索引」引用原为悬空，已在 `CODEBUDDY.md` 补「共享实现索引」小节落地。


---

## 原 9：basedpyright 下 sqlite3 Row 返回 Any，须集中 cast 收窄

- **日期**：2026-09-27
- **触发场景**：任何直接使用 `conn.execute(...).fetchone()/fetchall()` 且 `row_factory=sqlite3.Row` 的代码做类型检查（basedpyright 开启 reportAny）时。
- **强制动作**：`fetchone()`/`fetchall()`/`Row.__getitem__` 在 typeshed 中返回 Any，给变量加注解（`row: sqlite3.Row | None = ...`）无法消除 reportAny；必须在辅助函数内用 `typing.cast` 集中收窄（本项目为 `app/db.py` 的 `_fetchone`/`_fetchall`/`_s`/`_i` 四个助手），业务代码只经助手取行取列，禁止散落 `str(row[...])`/`int(row[...])`。
- **本项目实例**：2026-09-27 全项目告警清零时，`app/db.py` 首轮仅靠注解仍余 16 条 reportAny，改为四助手集中收窄后清零。
- **验证方式**：`read_lints` 全工作区 0 错误 0 警告；`py_compile` 通过；库层冒烟（get_setting / eligible_questions / answers_equal）真实运行通过。

---

## 原 10：类型分析器报「无法解析导入」先查环境绑定，而非改代码

- **日期**：2026-09-27
- **触发场景**：`pip show` / `python -c "import xxx"` 均正常，但 basedpyright 对第三方库（如 httpx）报 reportMissingImports，并连带派生几十条「类型未知」告警时。
- **强制动作**：先核对三件事——① 依赖是否真的装在运行解释器的 site-packages（`pip show` 看 Location）；② 项目内是否有 venv / `pyrightconfig.json`；③ 分析器绑定解释器与运行解释器是否一致。不一致时在项目根新建 `pyrightconfig.json`，写入 `"pythonPath"` 指向运行解释器，并加 `"extraPaths"` 直接指向 site-packages 目录兜底；禁止为消告警改业务代码或加 `# type: ignore`。
- **本项目实例**：2026-09-27 `app/ai.py` 报 42 条问题，根因是分析器未绑定 `D:/biancheng/python/python3.11.4`（httpx 0.28.1 实际已装且可导入，项目无 venv 无 pyright 配置）；补 `pyrightconfig.json`（pythonPath + extraPaths）后 42 → 2，再修 2 处 `raise_for_status()` 未使用返回值即清零。
- **验证方式**：`read_lints` 全工作区 0 告警；`python -c "import app.main"` 真实导入成功；`_parse_json` / `_extract_content` 用本地构造的 httpx.Response 冒烟通过。

---

## 原 11：静态检查报「N 个问题」按规则码归因分类，真实缺陷同码全项目举一反三

- **日期**：2026-09-27
- **触发场景**：IDE / `read_lints` 对某个 py 文件报「存在 XX 个问题」（错误 + 警告混报）时。总数无意义：同一根因会派生多条、不同严重级；必须看 basedpyright 规则码（`reportXxx`）。
- **强制动作**：
  1. 不看总数看规则码：逐条按 `reportXxx` 码归类统计（码 → 条数 → 行号）；
  2. 逐类判定性质，只分三种：① 真实缺陷（弃用 API、死参数、类型不安全操作）；② 违反项目已有规则（如原 9 类型收窄未走助手）；③ 框架惯用误报（如 FastAPI 的 `Form(...)` 默认值触发 reportCallInDefaultInitializer，属严格模式对框架模式的误报）；
  3. ①② 类按同码全项目举一反三：对同目录其余 py 文件跑 `read_lints` 或 `search_content` 查同源写法，反馈列出「查了哪些文件、结论是什么」；
  4. ③ 类误报禁止在业务代码加 `# type: ignore` 或为消音改写框架惯用代码；若确认整类误报，在归档记录后可在 `pyrightconfig.json` 按码关闭该检查，而不是散落注解。
- **本项目实例**：2026-09-27 `app/main.py` 报 71 条（8 错误 + 63 警告），按码归为 4 类：A. 表单值未收窄（`form.get()` 返回 `UploadFile | str` 直接进 `int()` / `.strip()`）→ 8 条错误全部，根因一个；B. 违反原 9（裸 `conn.execute` + Row Any，未走 `_fetchone`/`_fetchall`/`_s`/`_i`）→ 约 30 条 reportAny/reportUnknown/reportUnusedCallResult；C. FastAPI `Form(...)` 默认值误报 → 17 条 reportCallInDefaultInitializer；D. 零散真实问题（`on_event("startup")` 弃用、`/paper/new` 的 `max_count` 死参数、`_figure_question(q)` 缺注解、SQL 隐式字符串拼接）。举一反三：`read_lints` 全查 `app/db.py`、`app/ai.py`、`run.py` 均 0 条，确认 B 类仅 main.py 一个残留点。
- **验证方式**：归类表与全项目排查结论在会话反馈中列出；修复后 `read_lints` 复查到目标状态（错误 0；警告按 A/B/D 清零、C 类按配置处理），`py_compile` 通过。
- **补充（2026-09-27，配置层事实）**：`pyrightconfig.json` 的 `include` 原为 `["app", "run.py"]`，B 类重构的隔离冒烟脚本写在项目根时发现其不受静态检查覆盖——后续新增 py 文件是否被检查取决于 include 范围。已改为 `["**"]` 全工作区覆盖（工具层自动生效，无需行为规则约束）；「自主检查」流程本身由规则 2（交付前检查 + 端到端实测）与规则 11（按码归因）覆盖，不再新增重复规则。
