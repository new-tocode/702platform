# 8. 安全设计

> 安全设计要点。**完整的威胁模型与审查结论见 [安全检查.md](../../安全检查.md)**，这里只列设计层面的取舍。

---

- **双层权限控制**：模板层按权限隐藏入口（仅影响展示）+ 视图层二次校验（真正的权限边界）。只隐藏不设防是常见漏洞。
- **CSRF**：Django 内置，所有 POST 表单都带 token（`{% csrf_token %}`）。
- **XSS**：模板自动转义；Markdown/富文本渲染使用安全的渲染器（如 `bleach` 白名单过滤）。
- **密码**：Django 默认 PBKDF2 哈希；`AUTH_PASSWORD_VALIDATORS` 开启强度校验。
- **上传校验**：类型白名单（图片 jpg/png/webp/gif，视频 mp4/webm）+ 大小上限（媒体库图片 ≤10MB、头像 ≤2MB、图册单张 ≤5MB 且每人合计 ≤100MB、视频 ≤500MB）；Django 端校验 + Nginx `client_max_body_size` 双重限制；仅允许白名单扩展名，拒绝可执行/脚本类文件。
- **个人图册的对象边界**：所有图册动作都按 `profile=本人` 取对象（`get_object_or_404`），不是先按 id 取出来再判权限——别人的图连存在与否都不告诉他。视图只渲染自己的图册，模板不承担权限判断。
- **媒体服务**：上传落 MEDIA 目录，生产环境由 Nginx 直接静态服务（含 Range 支持便于视频拖动播放），不经过 Python 进程；视频要求 MP4(H.264)/WebM 保证浏览器直放。
- **富文本安全**：Markdown 服务端渲染后用 `bleach` 白名单过滤，禁止内联脚本；图片引用仅允许本平台 MEDIA URL（或显式白名单域名）。
- **配置安全**：`DEBUG=False`、`SECRET_KEY` 走环境变量、安全 Cookie（`SESSION_COOKIE_HTTPONLY`、生产走 HTTPS）。
- **审计**：核心写操作（发布/登记/借还/改密/改资料）通过 `core.audit.record_audit()` 写入 `AuditLog`，只记录非敏感结构化信息，后台只读查询。

---
