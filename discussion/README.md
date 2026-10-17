# discussion 模块

> 社团空间：板块、帖子（配图、置顶）、软删除的评论、成员目录，以及正文里 `@姓名` 的解析。
> **它不拥有消息**——提及与评论消息的写入、撤回归 `notices`；不存身份与资格；不判「谁算管理员」
> （问 `core.permissions.is_admin`）；不做后台（**本 app 没有 `admin.py`**，Board／Post／Comment
> 都不进 Django Admin）。

**什么时候看**：改板块／帖子／评论的规则或页面、动 `@` 提及、碰发言限速、改帖子图的取件口径，
或者要回答「谁能看到社团空间里的什么」的时候。

---

## 1. 明确不做什么

| 不在这里 | 落在哪 |
|---|---|
| 提及与「有人评论了你的帖子」**消息**的写入与撤回 | `notices.services`——`Message` 归它所有；`Message.post` / `Message.comment` 用字符串外键指回来，加载期不依赖本 app |
| 成员身份、姓名、头像、账号是否被锁 | `accounts`：`is_member` 读的 `is_active` / `must_change_password` 都存在 `User` 上 |
| 「谁算管理员」 | `core.permissions.is_admin`；删帖、删评论、置顶都调它，不写 `user.is_staff` |
| 受保护件的存储、落盘命名与取件响应 | `core.storage`、`core.downloads.serve_file` |
| 图片的扩展名／大小／MIME／真实签名校验 | `core.uploads.validate_image_upload`；本 app 的 `validators.validate_post_image` 只给上限与文案 |
| 帖子正文的 Markdown 渲染与 HTML 白名单 | `content.templatetags.rendering.render_markdown`（模板里用）；**允许哪些标签由 `content` 决定** |
| 成员只读资料页 | `accounts:member_profile`；成员目录只负责链过去 |

## 2. 必须成立的断言

- **成员的门槛只有 `discussion.permissions.is_member` 一个判据**：登录 + `is_active` + 不是
  `must_change_password`。`content.permissions.can_manage_awards` 直接 import 它——**改这里的口径，
  历年获奖页的可写范围会跟着变**。
- **建／删板块只认 `is_superuser`**（不是 `is_admin`）：这是全平台唯一把 `is_superuser` 当独立资格用的
  地方。但判定有两处写法：`permissions` 与服务层是权威，模板上的管理控件由
  `views._space_context` 的 `can_manage_boards = request.user.is_superuser` 控制——
  **改判定时要一起改**，否则会出现「按钮在、提交 403」或「按钮没了、接口还开着」。
- **硬删的是帖子，软删的是评论**：删帖连带评论行、图片行与磁盘文件；删评论只写 `deleted_at` /
  `deleted_by`（一条有人回过的评论硬删掉，「删过」这件事就无从追查）。删帖时软删过的评论照样跟着走
  ——Django 收集待删对象用的是不过滤的 `_base_manager`。**改回硬删或改经理定义会同时打掉限速计数、
  重删幂等与消息撤回。**
- **发言限速是发帖 + 评论共用的一个桶**，计数走 `Post.objects` + `Comment.all_objects`
  ——**已软删的评论也算**，否则「发满、删掉、再发」是免费口子。挡的主要不是帖子本身，而是 `@` 提及：
  它给任意成员写站内消息，是站内唯一能主动投递内容的通道。
- **每帖 ≤3 张、单张 ≤3 MB**，上限在**表单与服务层各判一次**（表单先给友好报错，服务层兜住绕过表单的
  调用），两处读的是 `validators` 里同一份常量。
- **帖子图是受保护件**：页面一律 `{% url 'discussion:post_image' image.pk %}`，
  **不写 `{{ field.url }}`**（`PrivateStorage.url()` 返回空串，写上去只会得到空地址）。
- **板块名的唯一真相源是数据库约束**：`BoardForm.clean_name` 只是先把冲突翻成一句中文，
  服务层再把 `IntegrityError` 翻成 `BoardNameTaken`。绕开两者直接 `Board.objects.create` 仍会被约束挡下。
- **`@` 提及的权威在服务端**：正文里写了 `@姓名` 就算提及，前端补全只是帮忙打字。
- **提及消息按 diff 对齐，不是只增不减**：以 `(kind=mention, post, comment)` 为界——编辑后新增的写消息、
  去掉的删消息；自己 `@` 自己不发。
- **评论会给帖子作者留一条消息，但一条评论最多留一条**：`create_comment` 在 `_sync_mentions` **之后**
  调 `notices.services.notify_comment`——先写提及，帖主才判得出自己是不是已经被 @ 到。两条去重规则都写在
  `notify_comment` 里，**不要把这个判断挪到视图或模板**。
- **长帖折叠只有 CSS 一个出处**：`static/css/app.css` 里 `.discussion-post-content.is-collapsed` 的
  `max-height` 是「多长算长」的唯一定义，`discussion.js` 不重复这个数字，模板里也**不写**
  `is-collapsed`（没有脚本时正文整段照常显示，按钮默认带 `hidden`）。
- **`page_of_post` 的顺序必须与 `posts_for_board` 一致**：消息链接的页码靠它，**改 `posts_for_board`
  的排序时必须同步改它**，否则消息会落到别的页。

## 3. 已知限制 / 当前不支持

- **发言限速不严格**：检查与写入之间没有锁，两个并发请求可能同时通过，多出一两条。这是刻意的选择
  （限速挡的是脚本化刷屏，为此给每条发言串行化得不偿失）；真正要求严格不超的地方（库存、评审席位）
  另有行锁。**限速与「已删评论仍计数」同源**：删掉自己的话不会把配额还回来。
- **软删评论在页面上直接消失，没有占位行**：模板遍历的是默认经理（只含未删的），所以内容、计数与
  `#comment-N` 锚点一起没了——**既没有占位行，也没有「该评论已删除」那句话**。
- **`page_of_post` 要数一遍板块的全部帖子 id**（取全量 `pk` 再 `.index()`）：板块帖子多时是 O(n) 的内存与
  时间。它是「第几页」的唯一实现，`notices` 的消息链接依赖它。
- **本 app 没有后台页面**（无 `admin.py`）：板块改名、删除有帖的板块都只能走前台（先清空帖子）或直接改库。
- **板块名的大小写不敏感唯一只作用于 `name`**：`name_zh` 没有唯一约束，中文可以重名。
- **成员目录与 `@` 补全名单都包含「首改密中」的账号**：两者只过滤 `is_active`。这是有意的（他们改完密码
  就能看帖，消息放着不碍事），**不要在别处再补一次 `must_change_password` 过滤**，否则三处口径分叉。
- **同名会发给所有同名账号**：姓名映射到用户列表，对同名的每个人都算一次提及；前端补全同样只按姓名匹配。
- **帖子图的 `sha256` 存库但不随响应发**：图片类刻意没有 `Content-Digest` / `X-Checksum-SHA256`
  （那套是给项目资料、评审回复与归档件的）。
- **正文渲染的安全边界不在本 app**：帖子正文经 `render_markdown` 处理（去 `script` / `style` +
  bleach 白名单），评论只做 `linebreaksbr`。
- **`validators.post_image_upload_to` 是已被换掉的旧口径**：迁移 `0004` 引它、`0006` 换成
  `core.storage.NeutralUploadTo("discussion")`，只留给历史迁移引用，**新上传不走它**，
  不要把它接回模型。
- **审计的事务边界不统一，且代码与文档都没说这是有意还是遗留**：三条删除
  （`delete_board`／`delete_post`／`delete_comment`）的审计在事务内，五个写入（`create_board`／
  `create_post`／`update_post`／`set_post_pinned`／`create_comment`）在提交之后。后半类若审计写失败，
  数据已经落库而没有留痕。**新增写操作时跟着相邻的那一个走**，别自作主张。

## 4. 由来

- **评论为什么是软删除**：一条有人回过的评论硬删掉，「删过」这件事就无从追查。所以只写 `deleted_at`／
  `deleted_by`，默认经理 `objects` 挡掉已删的、`all_objects` 看全貌；删帖仍用 `_base_manager`
  级联带走软删评论。
- **为什么限速不加锁**：讨论区的发言限速是防滥用而不是防资损，多一次少一次无所谓——所以它刻意不进事务、
  不锁行（对比：图片上限与删板块都锁）。
