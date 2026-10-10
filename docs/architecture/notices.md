# notices（通知与「我的消息」）

> 公告与站内消息。**模块说明（职责、接口、不变量、失败模式、测试与限制）在
> [`notices/README.md`](../../notices/README.md)**——表结构、规则与坑都搬去了那里。
>
> 这一篇只留**跨模块口径与由来**。

**什么时候看**：改可见性口径、给「我的消息」接新来源，或想弄清「用户组」到底管什么。

---

## 跨模块口径

- **三种可见范围**（`public` / `internal` / `contacts`）的判定只有一个函数：`notices/visibility.py` 的 `member_visible_notices`——列表、详情、未读计数、「全部已读」全走它。在视图或 `selectors` 里另拼一段 `Q(...)` 就是开出第二处真相。
- **未授权详情是 404，不是 403**：过滤直接把不该看的从查询集里拿掉，连「存在与否」都不说。这与受保护件取件的 403 是两种口径，别改串（见 [overview.md](overview.md) §4 的说明）。
- **用户组（`auth.Group`）只在这里有意义**：它是内部通知的投递范围，**不是身份**，也不进 `core.roles` 目录。成员想知道自己在哪些组上，看个人信息页「当前身份」末条。
- **事件型消息是别的模块「借」这张表**：@ 提及（解析归 `discussion`，写入归 `notices.services.sync_mention_messages`）、评审任务与结果、入组／建组申请与结果。表格的所有权在 notices，**呈现与去向也在 notices**（`notices.selectors` 的 `_CONTENT_BUILDERS` / `_TYPE_LABELS`）。
- **加一个新 kind 要同时改三处**：`Message.KIND_CHOICES`、`selectors._CONTENT_BUILDERS`、`selectors._TYPE_LABELS`。漏第二处该行被静默跳过（只有 warning），漏第三处装配时整页 500。

## 由来

- **为什么消息只存引用、不存副本**：行里存的是五个可空外键与已读状态，标题／链接／说明由 `notices.selectors` 现取现算——帖子改名、轮次出了新结论，消息里跟着变，不会对不上。**别把显示字段落进表**，那会让这条性质失效。
- **为什么用字符串外键**：notices 因此不在加载期依赖 `discussion` / `reviews` / `projects`；「哪一类消息挂哪个引用」不加库约束，交给写入函数。
- **为什么未读要现算**：可见通知 − 已读回执（`NoticeRead`），不物化副本——发布人删通知，成员侧自然消失，回执随 CASCADE 清掉，不留孤儿。
- **为什么撤回了「登录 flash 与成员中心待办卡片」**：同一个数字不该有两处口径；未读统一由「我的消息」的提醒条报出。任务类消息跟着任务生命周期走（交掉／被释放／被改派即撤），历史归评审页。
- **一个运维缺口（如实记下）**：`config/settings.py` 的 `LOGGING["loggers"]` 里**没有 `notices` 一节**——实测它的生效级别是 `WARNING`、没有 handler，**与 `DEBUG` 无关**。所以 `logger.info`（如 `notice.messages.list`）不会落 `logs/django.log`，只有 `selectors` 的 `logger.warning`（`notice.messages.unknown_kind`）会落。要改需在 settings 补一段 logger；缺 logger 的是 `notices`／`content`／`media`／`discussion` 四个（其余 app 都是显式 DEBUG）。
