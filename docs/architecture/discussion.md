# discussion（社团空间）

> 板块、帖子、评论与成员目录。**模块说明（职责、接口、不变量、失败模式、测试与限制）在
> [`discussion/README.md`](../../discussion/README.md)**——表结构、规则与坑都搬去了那里。
>
> 这一篇只留**跨模块口径与由来**。

**什么时候看**：改权限分层、动软删除或消息接线，或想知道「折叠」这类前端约定住在哪。

---

## 跨模块口径

- **成员判据被别的 app 依赖**：`discussion.permissions.is_member` 被 `content.permissions` 在**加载期** import（历年获奖页的可写范围用它）。改它等于同时改获奖页——这是本模块少见的「别人依赖我」。
- **建／删板块只认 `is_superuser`**：全站只有这一处把超级用户当作独立于 `is_staff` 的资格（见 [glossary.md](../glossary.md) 的「超级管理员」）。**页面上的按钮与视图的判定必须同源**：模板控件由 `views._space_context` 的 `can_manage_boards` 直接读 `request.user.is_superuser`，只改 `permissions.py` 会出现「按钮在、提交 403」或反之。
- **@ 提及是跨 app 的**：解析（`discussion/mentions.py`）、定位（`selectors.page_of_post` 算页码拼锚点）在本地，**消息的写入与撤回归 `notices`**（`sync_mention_messages` / `clear_mention_messages`）。`page_of_post` 与 `selectors.posts_for_board` 的排序必须同步改——两边不一致，消息会落到别的页。
- **受保护件与上限归 core**：帖子图落 `protected_media/`、取图走 `discussion.views.post_image`；校验与存储口径在 `core.uploads` / `core.storage`。图片规格（每帖 3 张、单张 3 MB）的常量在本模块。
- **折叠的唯一判据在 CSS**：`.discussion-post-content.is-collapsed` 的 `max-height` 是「多长算长」的唯一定义，`static/js/discussion.js` 不重复这个数字——它先套类、再问浏览器有没有真的溢出。模板不写 `is-collapsed`：没有脚本时页面就是全文展开。

## 由来

- **评论为什么是软删除**：一条有人回过的评论硬删掉，「删过」这件事就无从追查。所以只写 `deleted_at`／`deleted_by`，默认经理 `objects` 挡掉已删的、`all_objects` 看全貌；删帖仍用 `_base_manager` 级联带走软删评论。改回硬删或改经理定义会同时打掉限速计数、重删幂等与消息撤回。
- **为什么限速不加锁**：讨论区的发言限速是防滥用而不是防资损，多一次少一次无所谓——所以它刻意不进事务、不锁行（对比：图片上限与删板块都锁）。
- **渲染与文档的一处漂移（如实记下）**：`Comment` 的模型注释与 `notices.services.clear_mention_messages` 的 docstring 都提到「已删除的评论在界面上让位给一行说明」，但模板遍历的是默认经理、那句话在全库 grep 不到——**按现状读：删除后整条消失，计数与 `#comment-N` 锚点一起没**。改注释还是改模板，得先定哪个是对的。
- **审计的事务边界不统一**：`create_board`／`delete_board`／`delete_post`／`delete_comment` 的审计在事务内，`create_post`／`update_post`／`set_post_pinned`／`create_comment` 在提交之后。代码与文档都没说这是有意还是遗留——新增写操作时**跟着相邻的那一个走**，别自作主张。
