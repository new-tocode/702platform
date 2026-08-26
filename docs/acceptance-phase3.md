# 阶段三验收标准：公开展示与媒体

> 只有所有必选项通过，阶段三才算完成。

## 1. 验收范围

- `content` 应用：社团简介、历年获奖、成员风采
- `media` 应用：图片/视频统一媒体库
- 管理员通过 Django Admin 维护公开内容和上传媒体
- 已发布/启用状态控制公开可见性
- 媒体关联和公开渲染
- Markdown 安全渲染
- 上传类型、MIME、大小和基本文件签名校验

本阶段不实现视频转码、多码率、对象存储、断点续传和前端富文本编辑器；视频要求上传可直接被浏览器播放的 MP4/WebM。

## 2. 公开路由标准

| 编号 | 路径 | 标准 |
|---|---|---|
| C-01 | `/about/` | `/pages/about/` 的社团简介快捷地址，读取 `slug=about` 且 `is_published=True` 的页面 |
| C-02 | `/pages/<slug>/` | 通用公开内容页；任意已发布且合法 slug 的 `ContentPage` 都可以访问 |
| C-03 | `/awards/` | 匿名访客可以浏览历年获奖，按年份倒序 |
| C-04 | `/showcase/` | 只显示 `is_active=True` 的成员风采，按排序字段展示 |
| C-05 | `/media/...` | 开发环境可通过 Django 媒体路由访问已上传文件 |

## 3. 内容模型标准

| 编号 | 标准 | 验证方式 |
|---|---|---|
| C-05 | `ContentPage` 支持 slug、标题、正文、发布状态和媒体附件 | 模型/迁移 |
| C-06 | `Award` 支持奖项、赛事、年份、级别、获奖人和媒体附件 | 模型/迁移 |
| C-07 | `Showcase` 支持成员、简介、排序、启用状态和照片/视频 | 模型/迁移 |
| C-08 | 访客看不到未发布简介 | 自动测试 |
| C-09 | 访客看不到停用的成员风采 | 自动测试 |
| C-10 | 管理员可以在 Admin 创建并发布简介、奖项、成员风采 | 自动测试/人工冒烟 |
| C-11 | 普通成员不能进入 content/media Admin | 自动测试 |

## 4. 媒体上传标准

| 编号 | 标准 | 验证方式 |
|---|---|---|
| M-01 | `MediaFile` 保存文件、媒体类型、说明、上传人、大小和时间 | 模型/迁移 |
| M-02 | 图片允许 jpg/jpeg/png/webp/gif | 自动测试 |
| M-03 | 视频允许 mp4/webm | 自动测试 |
| M-04 | 图片大小不得超过 10 MB | 自动测试 |
| M-05 | 视频大小不得超过 500 MB | 校验逻辑/人工配置检查 |
| M-06 | MIME 类型必须与所选媒体类型匹配 | 自动测试 |
| M-07 | 图片通过 Pillow 解码校验真实图片格式 | 自动测试 |
| M-08 | MP4 检查 `ftyp` 标识，WebM 检查 EBML 文件头 | 自动测试/校验逻辑 |
| M-09 | 不允许 exe 等非白名单扩展名 | 自动测试 |
| M-10 | 管理员上传时自动记录上传人和文件大小 | 自动测试 |
| M-11 | 媒体可关联到简介、奖项、成员风采和通知 | 模型/页面测试 |

## 5. 正文安全标准

| 编号 | 标准 | 验证方式 |
|---|---|---|
| S-01 | Markdown 正文可渲染为基础 HTML | 自动测试 |
| S-02 | `script`、`style` 标签及其内容被移除 | 自动测试 |
| S-03 | HTML 经过 Bleach 白名单过滤后才标记为安全内容 | 代码检查/自动测试 |
| S-04 | 模板不直接使用 `|safe` 输出管理员原文 | 代码检查 |

## 6. 自动验收命令

```bash
# 依赖已更新时重新安装
.venv/bin/python -m pip install -r requirements.txt

# Python 语法和 Django 配置
.venv/bin/python -m compileall -q config accounts notices content media manage.py
.venv/bin/python manage.py check

# 检查迁移完整性并应用迁移
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate

# 阶段三测试
.venv/bin/python manage.py test content media --verbosity 2

# 全量回归
.venv/bin/python manage.py test --verbosity 1
```

预期结果：

```text
System check identified no issues
No changes detected
所有阶段三测试 OK
全量测试 OK
```

## 7. 人工冒烟验收

1. 执行 `createsuperuser` 或使用现有管理员进入 `/admin/`。
2. 在“媒体文件”中上传一张有效 PNG/JPG 图片，确认上传人自动记录。
3. 上传一个符合要求的 MP4/WebM 视频，确认 Admin 保存成功。
4. 尝试上传 exe、伪造 PNG、超过大小限制的文件，确认保存失败并显示错误。
5. 创建 `ContentPage`，slug 填 `about`，先不勾选“已发布”，访问 `/about/` 和 `/pages/about/` 都应返回 404。
6. 勾选发布并关联图片/视频，访问 `/about/` 和 `/pages/about/`，确认两者展示同一页面内容。
7. 再创建一个 slug 为 `rules` 的已发布页面，访问 `/pages/rules/`，确认可以访问；访问不存在或未发布的 slug 应返回 404。
8. 创建两条不同年份的 Award，访问 `/awards/`，确认按年份倒序。
9. 创建一个启用和一个停用的 Showcase，访问 `/showcase/`，确认只展示启用项。
10. 在正文中输入 Markdown 和脚本标签，确认 Markdown 生效、脚本不执行且脚本内容不显示。
11. 使用普通成员访问 `/admin/content/contentpage/` 和 `/admin/media/mediafile/`，确认被拒绝。

## 8. 完成门槛

以下任一项不满足，阶段三保持“未完成”：

- 任意自动测试失败
- 存在未生成的迁移
- Django `check` 报错
- 未发布内容或停用风采被公开展示
- 伪造媒体文件可以保存
- 媒体上传人没有记录
- Markdown 可执行脚本
- 普通成员可以进入内容或媒体 Admin
