# 竞赛社团管理平台

> 面向竞赛社团的轻量管理平台：Django 单体应用 + 服务端渲染模板，数据库**固定 PostgreSQL**。
> 含公开门户、成员系统与 Django Admin 后台。界面中英双语——中文是源语言（地址不带前缀），
> 英文走 `/en/` 前缀，**地址即语言**，后台 `/admin/` 不在双语范围内。

---

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt

source env.local.sh          # PostgreSQL 连接配置；不加载会连接失败
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

跑起来就能看到：首页 <http://127.0.0.1:8000/>、成员登录 `/login/`、管理后台 `/admin/`。
数据库固定 PostgreSQL（Django 5.2 要求 ≥14），不再支持 SQLite。

跑不通先看 [`更新维护/开发与部署.md`](docs/更新维护/开发与部署.md) §1 与 §6。

---

## 文档在哪

| 你想要 | 去哪 |
|---|---|
| **改某个模块**：它明确不做什么、必须成立的断言、**已知限制**、由来 | [`<app>/README.md`](accounts/README.md)——就地模块说明，**那个模块的唯一出处**；文件落点与接口签名读代码 |
| 怎么用、业务怎么走（兼**用户手册**） | [`更新维护/业务流.md`](docs/更新维护/业务流.md) |
| 代码怎么组织、模块怎么分、谁依赖谁、跨模块约定 | [`更新维护/模块与关系.md`](docs/更新维护/模块与关系.md) |
| 有哪些地址、门槛是什么、怎么失败；跨 app 该调哪个函数 | [`更新维护/接口.md`](docs/更新维护/接口.md) |
| 「这个功能谁能用」 | [`更新维护/权限.md`](docs/更新维护/权限.md) |
| 怎么构建、测试、部署、回滚、看日志 | [`更新维护/开发与部署.md`](docs/更新维护/开发与部署.md) |
| **为什么当初这么定**（架构级决策） | [`更新维护/ADR.md`](docs/更新维护/ADR.md) |
| 名词、缩写、单位口径 | [`术语表.md`](docs/术语表.md) |
| 用了什么、什么许可、分发义务 | [`更新维护/许可.md`](docs/更新维护/许可.md) |
| AI 的工作约定 | [`CLAUDE.md`](CLAUDE.md) |
| 原型当初怎么设计的（**历史资料，非现状**） | [`原型设计/`](docs/原型设计/README.md) |

部署工件在 [`deploy/`](deploy/)：`install.sh`、`deploy.sh`、`backup.sh`、systemd／Nginx 模板、`env.template`。

> 安全审查报告**不入库**：它含生产标识（IP、实例 ID、未修漏洞清单），按 `.gitignore` 排除在版本库外，
> 只在维护者的工作区，所以上面没有链接。

---

## 目录

十一个 Django app（`config` 加十个业务 app）。**各模块的职责边界、依赖关系与
谁依赖谁，见** [`更新维护/模块与关系.md`](docs/更新维护/模块与关系.md)。

---

## 许可

**MIT**，原文见 [`LICENSE`](LICENSE)。运行时依赖的许可与分发义务（含唯一的传染性许可 psycopg 的
LGPL 处置结论）见 [`更新维护/许可.md`](docs/更新维护/许可.md)，许可原文收在 [`THIRD_PARTY_LICENSES/`](THIRD_PARTY_LICENSES/)。
