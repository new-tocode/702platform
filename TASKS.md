# TASKS：文件 SHA-256 校验

上传即算指纹、下载时随文件附上，供下载人比对。

范围是平台**全部 7 个上传字段**：项目书、批注版项目书、归档批注版、头像、
个人图册、帖子图、媒体库。页面上折叠展示（原生 `<details>`，不引脚本），
下载响应同时带 `Content-Digest`（RFC 9530）与 `X-Checksum-SHA256` 两个头。

## 阶段 1：core 的指纹基础设施

- [x] `core/hashing.py`：`sha256_of()` 流式分块计算
- [x] `FileDigestMixin`：抽象模型，`sha256` 字段 + `save()` 自动计算
  - [x] 新上传（`_committed=False`）读的正是上传流，算完拨回开头再落盘
  - [x] 已落盘且已有指纹：沿用，不重算（改简介不该重读 20 MB 项目书）
  - [x] 已落盘但指纹为空（历史数据）：从存储补算一次
  - [x] `save(update_fields=[…])` 带了文件列时，把 `sha256` 并进写入列表
  - [x] 文件列**不在**写入列表时不动指纹——文件不落盘，指纹就不该跟着内存里的
        新内容走，否则与库里的文件对不上
- [x] 测试：与 `hashlib` 对拍、空文件、跨分块边界的大文件、上传流复位、
      三种重算分支、`update_fields` 的两种走法

## 阶段 2：7 个上传字段接入 + 历史文件回填

- [ ] 文档类：`ProjectGroup.proposal`、`ReviewTask.annotated_file`、`ArchivedProposal.file`
- [ ] 图片类：`Profile.avatar`、`GalleryImage.image`、`PostImage.image`、`MediaFile.file`
- [ ] 各自的 AddField 迁移，并在迁移里回填已有文件的指纹
- [ ] 测试：每条上传通道落库后，指纹等于 `hashlib.sha256(内容)`

## 阶段 3：下载时附上指纹

- [ ] `core/downloads.py`：`serve_file()` 收口六处 `FileResponse`
  - [ ] 顺带补上 `projects`／`reviews` 三处缺失的「文件不在盘上」→ 404
  - [ ] 带 `Content-Digest: sha-256=:…:` 与 `X-Checksum-SHA256: <hex>`
- [ ] 六个取件视图改用 `serve_file()`
- [ ] 测试：响应头与文件内容对得上；文件缺失时 404 而非 500

## 阶段 4：页面上折叠展示

- [ ] `group_detail.html`（6 处下载入口）、`group_manage.html`（1 处）
- [ ] `app.css` 的 `.checksum` 样式（等宽、可断行、小字）
- [ ] 英文译文补进 `locale/en/LC_MESSAGES/django.po`
- [ ] 测试：渲染出完整 64 位、默认收起

## 阶段 5：文档与收尾

- [ ] 同步 `docs/architecture/`：security.md、core.md 与各 app 篇
- [ ] 删掉本清单，单独提交
