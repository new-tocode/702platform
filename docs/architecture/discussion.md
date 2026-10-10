# 6.10 discussion（社团空间）

> 社团空间：板块、帖子、评论（软删除）与成员目录。

**什么时候看**：改帖子／评论的权限分层或图片上限。

---

```
Board（社团空间板块）
  - name_zh       中文名称（1–80 字符，必须包含中文）
  - name          英文名称（1–80 个 ASCII 英文字符，大小写不敏感唯一）
  - created_by    FK(User)
  - created_at

Post（帖子）
  - board         FK(Board, PROTECT；必须先清空帖子才可删板块)
  - author        FK(User)
  - title / content
  - is_pinned     是否置顶
  - created_at / updated_at
  - 默认排序：置顶优先，再按发布时间倒序

PostImage（帖子图片）
  - post          FK(Post, CASCADE)
  - image         图片（JPG/JPEG/PNG/WebP/GIF，单张 ≤3 MB，每帖最多 3 张）
  - sha256        image 的 SHA-256 指纹（上传时自动算，见 [core.md](core.md)）
  - file_size / created_at

Comment（评论）
  - post          FK(Post, CASCADE；删帖同时删除评论)
  - author        FK(User)
  - content
  - created_at
  - deleted_at / deleted_by    软删除：删除时间与删除人（被删账号置空）
```

- 空间和成员目录只对活跃、已完成首次改密的登录账号开放。板块选择器在内容区顶部横向滚动；帖子列表分页，评论按时间展示。
- **过长的帖子先折到一屏内**，正文下缘给一个「展开全文」；点开后整段展开，不再折回去。折叠高度是 `.discussion-post-content.is-collapsed` 的 `max-height`（`static/css/app.css`），也是「多长算长」的唯一判据——`static/js/discussion.js` 不重复这个数字，它先套上这个类，再问浏览器有没有真的溢出，溢出了才放出按钮（短帖因此既不折也没有按钮）。模板里不写 `is-collapsed`：折叠归脚本，没有脚本时页面就是全文直接展开，这也是那按钮默认带 `hidden` 的原因。
- 帖子作者可编辑/删除自己的帖子并增删图片；管理员由 `core.permissions.is_admin()` 判定，可删除任意帖子、置顶/取消置顶；仅 Django 超级管理员可创建/删除板块。权限与图片上限在 `discussion.permissions`、服务层与视图分别校验。
- **评论是软删除**：作者可删自己的评论、管理员可删任意评论（`can_delete_comment`，与删帖口径对称）。删除只写 `deleted_at`/`deleted_by`，行与内容都留着——一条有人回过的评论硬删掉，「删过」这件事就无从追查；删除动作另有 `discussion.comment.delete` 审计。
  - 已删除的评论由 `Comment.objects` 这个默认经理统一挡掉（反向关系 `post.comments` 走的也是它），要看全貌走 `Comment.all_objects`。
  - 级联删除不受影响：收集待删对象用的是不过滤的 `_base_manager`，删帖时软删过的评论照样跟着走。评论上没有文件，所以不像删帖那样还要清理磁盘上的图片。
- **@ 提及**：帖子正文与评论里的 `@姓名` 会变成收件人的「我的消息」（见 [notices](notices.md#我的消息)）。
  - 解析归 `discussion/mentions.py`：拿「有姓名的活跃账号」做最长匹配（`@张三丰` 不会被拆成 `@张三` 再搭一个字），`@` 前不能是字母数字（邮箱里的 @ 不算）；账号名不算人名，同名时给所有同名者发。
  - 写入与撤回归 `notices.services.sync_mention_messages`（它拥有 `Message`）：发帖/评论时写、编辑后按 diff 增删（新增的写消息、移除的删消息）、评论软删除时一并撤回；自己 @ 自己不发。接线在 `discussion.services` 的三处写入口，都在事务里。
  - 补全是渐进增强：页面嵌姓名名单（`json_script`），`static/js/mentions.js` 在标了 `data-mentions` 的输入框里弹列表（↑↓ 选、Enter/Tab 补、Esc 收，输入法合成期间不弹）；没脚本时手打 `@姓名` 一样有效——服务端才是权威。
  - 定位：帖子的 `article` 与评论块带 `post-N`／`comment-N` 锚点；消息链接由 `discussion.selectors.page_of_post` 现算页码后拼 `#锚点`，`:target` 让落地处亮一下。
- 创建帖子与删除板块均锁定板块行，避免并发操作绕过“删除前必须清空”的规则；编辑帖子锁定帖子行并核对图片数量，避免并发超出上限。关键写操作通过 `core.audit.record_audit()` 留痕。
- 成员目录显示头像、姓名（为空时回退账号名），按姓名搜索。只读他人资料页不复用本人可编辑的 Profile 表单，仅展示头像、姓名/账号名、学院、专业、特长、简介、身份、图册与公开的手机号/其他联系方式；学号与邮箱不展示。
- 只有界面字符串进入英文 `.po`；板块名、帖子、评论与个人资料均为用户内容，不翻译。

- **格式白名单**：图片 jpg/jpeg/png/webp/gif；视频 mp4（要求包含 `ftyp` 标识）/ webm（要求 EBML 文件头）。仅允许白名单扩展名，拒绝可执行/脚本类文件；图片还通过 Pillow 解码校验。
- **大小上限（默认建议值，可按服务器带宽/磁盘调整）**：图片 ≤10MB、视频 ≤500MB；Django 端校验，生产需同步配置 Nginx `client_max_body_size`。
- **图片那一套校验只有一份实现**：`core/uploads.validate_image_upload`（扩展名、大小、MIME 家族、真实图片签名）。媒体库的图片分支与个人信息页的头像（≤2 MB）、图册单张（≤5 MB）都调它，差别只是上限与文案；视频是媒体库独有的口径，仍留在 `media/validators.py`。图册另有合计上限，见 [accounts.md](accounts.md)。
- 统一媒体库的好处：公开页、通知、风采均引用同一文件；后续切换对象存储只需改一处存储配置。
- 本期**不做视频转码/多码率**：要求上传即 MP4（浏览器直放），由 Nginx 静态直出并支持 Range 拖动播放；视频量大后再引入 ffmpeg 转码或 OSS 处理。

---
