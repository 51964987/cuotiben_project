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

