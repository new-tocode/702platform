# 竞赛社团管理平台

面向竞赛社团的轻量管理平台：Django 单体应用，服务端渲染，数据库 PostgreSQL。含公开门户、成员系统与 Django Admin 管理后台。

## 当前状态

- 自定义 `accounts.User`（含 `must_change_password`、`is_reviewer`）与 `Profile`；管理员发放账号/重置密码，不开放注册；成员首次登录强制改密
- 通知：公开 / 内部（按用户组）/ 仅项目组联系人可见，支持置顶
- 公开展示（社团简介、历年获奖、成员风采）与图片/视频媒体库（类型、大小、文件签名校验）
- 项目组与联系人：申请入组与审核、移除成员、联系人转让、改组介绍；联系人身份由 `ProjectGroup.leader` 计算，不建冗余用户组
- 项目书同行评审（期刊式）：联系人上传 doc/docx/pdf 项目书、选择送审类型后送审，类型决定评审人数（竞赛类 3 人 / 大创中期·结题 2 人 / 大创立项 1 人）；评审人可另附批注版项目书，全部通过方为通过，批注版随通过归档；同一项目组同时只能有一个未结束的轮次
- 评审人请假：评审人可在成员中心登记一段不收新评审任务的时间窗，到点自动恢复；管理员在后台查看全部请假并直接调整时间以提前或延后恢复
- 评审待办提醒：评审人登录时若手上有未完成评审会即时提醒，成员中心顶部另有常驻待办卡片，点击直达评审队列
- 评审改派：管理员可在后台把「待评审且该轮尚未判结论」的评审任务改派给其他评审人，用于评审人失联或事后发现利益冲突的补救；已给出结论的记录保持只读
- 超级评审（`User.is_super_reviewer`）：可看到全部进行中的评审并直接通过或打回，一票敲定本轮、等待中的评审人随即被释放，可附批注版项目书；与评审资格相互独立，同时具备时也可被抽为普通评审人
- 竞赛：发布、项目组联系人报名（指定竞赛组长）、修改与放弃
- 设备台账与借用登记（项目组成员门槛、库存事务与行锁）
- 操作入口注册表（成员中心按权限动态生成）与数据库审计日志（后台只读）

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

source env.local.sh          # PostgreSQL 连接配置；不加载会连接失败
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

访问：首页 <http://127.0.0.1:8000/>、成员登录 `/login/`、管理后台 `/admin/`。数据库固定 PostgreSQL（Django 5.2 要求 ≥14），不再支持 SQLite。

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | 架构：模块划分、数据模型、权限设计、路由、关键流程 |
| [`docs/development.md`](docs/development.md) | 开发指南：目录结构、环境配置、常用命令、测试与验收、日志调试、FAQ |
| [`docs/deploy.md`](docs/deploy.md) | 部署手册：快速验证、生产一步脚本、更新回滚、备份恢复、运维 |
| `deploy/` | 部署工件：`install.sh`、`deploy.sh`、`backup.sh`、systemd/Nginx 模板、`env.template` |

## 日志

开发环境日志同时输出到终端并写入 `logs/django.log`（10MB 轮转，保留 5 份）。每个请求带 `X-Request-ID` 响应头，与日志中 `request_id` 对应。认证日志不会记录明文密码。

生产环境至少设置：`DJANGO_SECRET_KEY`、`DJANGO_DEBUG=0`、`DJANGO_ALLOWED_HOSTS`、数据库 `DJANGO_DB_*`，HTTPS 下再开 `DJANGO_SESSION_COOKIE_SECURE`/`DJANGO_CSRF_COOKIE_SECURE`。
