# TASKS：测试分层与文档重构

目标：测试文件按功能分模块（对齐 `reviews/tests/` 已有的做法），文档改成「分层 + 可查 + 不重复」的结构。

约束：**不改变任何被测试的行为**。测试重构只搬运与改归属，用例内容一字不动（除非是重复代码的抽取）。

## 阶段 1：测试文件分层

- [ ] 1.1 `accounts/tests.py`（1651 行）→ `accounts/tests/` 包：按主题拆 13 个类，抽 `factories.py`（建账号 + 头像/图册的上传件制造）
- [ ] 1.2 `discussion/tests.py`（1176 行）→ `discussion/tests/` 包；`DiscussionViewTests`（504 行 / 17 用例）拆成视图几个主题
- [ ] 1.3 `projects/tests.py`（667 行）→ `projects/tests/` 包；`ProjectGroupAcceptanceTests`（407 行 / 23 用例）拆开
- [ ] 1.4 `core/tests.py`（643 行）→ `core/tests/` 包（入口注册表 / 审计 / 翻译兜底 / 上传校验）
- [ ] 每个阶段跑该 app 的测试，最后一个阶段跑全量

## 阶段 2：文档分层

- [ ] 2.1 `docs/architecture.md`（744 行 / 36K 字）拆成 `docs/architecture/` 包：概览、各 app 的数据模型、权限、路由、流程
- [ ] 2.2 `docs/development.md`（418 行）拆成 `docs/development/` 包：上手、分层约定、配置、测试、调试
- [ ] 2.3 拆掉「同一套规则写两遍」：`development.md` 验收要点表里 `reviews` 那一格 1787 字符 → 压到索引级，指向架构文档
- [ ] 2.4 长段落打散：`architecture.md` 里 14 个 ≥800 字符的段落（最长 1485）拆成小段或子标题

## 阶段 3：可查找性

- [ ] 3.1 `docs/README.md` 做文档索引（每篇一句话 + 什么时候看它）
- [ ] 3.2 修掉会失效的引用：`安全检查.md` 里的 `docs/architecture.md:381` 这类**行号引用**改成章节引用；各文档内部 `§N` 引用随拆分更新
- [ ] 3.3 顶层 `README.md` 的文档表指向新路径

## 收尾

- [ ] 全量测试绿、`check`、`makemigrations --check`
- [ ] 删除本清单，单独提交

## 不做

- 不改测试断言、不改用例归属之外的逻辑
- 不动 `安全检查.md` 的结论与风险清单（它是一份有日期的审计报告，只修引用）
- 不合并 `deploy.md` 与 `安全检查.md`（读者与用途不同）
