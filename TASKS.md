# 安全加固任务清单

依据 `安全检查.md`（基线 `98564c5`）。分支 `security/hardening`，一阶段一提交。

## 用户已拍板的前提

| 决定 | 取值 |
|---|---|
| HTTPS 现状 | 无自有证书，借用**另一个已备案站点的 CA 证书**（该站点与本平台无关，随时可能收回） |
| HSTS | **不启用**。证书随时可能被收回，HSTS 会把域名锁死且用户无法绕过 |
| 80 跳 443 | **不在 Nginx 硬跳**（IP 访问会被打到域名上去）。在 Django 层按 `DJANGO_SECURE_SSL_REDIRECT` 开关，默认关 |
| Cookie Secure | **默认开启**（站点已全量 https，IP 直连亦然） |
| 登录防护 | `django-axes`（按账号 + IP 双维度失败计数与锁定） |
| 文件边界 | 全部上传统一走鉴权视图，含头像与图册 |
| 项目书落盘 | 改为 uuid，已存文件由数据迁移搬迁（上线时执行） |
| 依赖管理 | pip-tools 锁定 + GitHub Actions 跑 check + 测试 + pip-audit |
| 评审意见对组员可见 | **保持现状**，仅记录为已知取舍 |
| 帖子编辑 | **随时可编辑，不保留修改历史**（记录为已知取舍，不改代码） |

## 阶段

### 阶段 1 · 上传校验与公开面（V1、V4、V10）✅
- [x] `core/uploads.py`：捕获 Pillow `DecompressionBombError`，显式设 `Image.MAX_IMAGE_PIXELS`
- [x] 把「先量尺寸再 verify」收进统一校验，避免超大图通过校验后到渲染才炸
- [x] 四条上传通道各补回归用例（断言抛 `ValidationError` 而非未捕获异常）
- [x] Nginx 拒绝 `.` 开头的路径（`.git/`、`.github/`）
- [x] `install.sh` 生成 `env.sh` 后 `chmod 600`；生产配置缺失时拒绝启动

### 阶段 2 · 传输层与会话（V2）✅
- [x] `Cookie Secure` 默认开；`DJANGO_SECURE_SSL_REDIRECT` / `DJANGO_SECURE_HSTS_SECONDS` 开关（默认关）
- [x] 生产环境 `SECRET_KEY` 未改时拒绝启动（DEBUG 交给上线门禁）
- [x] `deploy.sh` 上线流程加 `check --deploy` 门禁（实测拦下 W018/W012/W016）
- [x] Nginx：`limit_req` 限 `/login/`、`/admin/login/`（zone 由 install.sh 幂等追加）
- [x] 文档：拿到自有证书后的四步启用清单

### 阶段 3 · 登录暴力破解防护（V3）✅
- [x] 引入 `django-axes`，账号与 IP 两个维度各算，10 次锁 30 分钟
- [x] 锁定写审计（不记口令）；后台可查看与提前解锁
- [x] 用例：锁定期间正确口令也拒绝、成功登录不清 IP 计数、审计不含口令

### 阶段 4 · 上传文件边界（V5）
- [ ] 新增 `PRIVATE_MEDIA_ROOT` 与 `private_storage`；受保护文件迁出 `mediafiles/`
- [ ] 项目书、批注版、归档版、头像、图册、帖子图全部改走鉴权视图
- [ ] 头像、图册、帖子图、项目书落盘统一 uuid
- [ ] 数据迁移：搬已存文件 + 改库中路径
- [ ] 用例：未登录取不到新路径；越权取他人头像/图册为 404/403

### 阶段 5 · 输入边界与业务一致性（V6、V11）
- [ ] 6 处无上限文本补 `max_length`（含迁移）
- [ ] 显式设置 `DATA_UPLOAD_MAX_MEMORY_SIZE`、`FILE_UPLOAD_MAX_MEMORY_SIZE`
- [ ] 竞赛报名放弃补截止时间校验
- [ ] 对应用例

### 阶段 6 · 依赖、CI 与文档收尾（V7、V8）
- [ ] `requirements.in` + pip-tools 锁定
- [ ] GitHub Actions：`check --deploy` + 全部测试 + pip-audit
- [ ] `backup.sh`：备份移出 `ReadWritePaths`、加 `age`/`gpg` 加密钩子、媒体与库一致性
- [ ] 更新 `docs/deploy.md`、`docs/development.md`、`README.md`
- [ ] 修正 `安全检查.md` 里 V8 关于 `admin.E408` 的错误陈述（实测 `check` 无任何问题）
- [ ] 删除本清单

## 每阶段收尾必做

```bash
source env.local.sh
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test          # 基线 436 个用例
```
