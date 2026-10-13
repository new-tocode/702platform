# content 模块

> 公开展示内容：通用公开页 `ContentPage`（含顶栏固定的 `/about/`）、历年获奖 `Award`
> （判重、成员前台录入、证书打包下载）、成员风采 `Showcase`、首页轮播 `HomeSlide`，
> 以及全站共用的 Markdown 渲染过滤器 `render_markdown`。
> **不碰媒体文件本身**——`MediaFile` 归 `media`；**不定义「谁能做什么」**——`permissions.py`
> 只有一条委托；**不负责首页**——轮播由 `accounts.views.home` 查、在 `templates/home.html` 里渲染。

**什么时候看**：改公开栏目或 `/about/`、动获奖判重与层级口径、改前台添加获奖表单与图片上限、
改证书打包下载、调 `render_markdown` 的白名单时。

---

## 1. 明确不做什么

| 不在这里 | 落在哪 |
|---|---|
| 媒体文件本身：存储、`kind` / `caption` / `uploader` / `file_size` / `sha256`、上传校验实现、取件 | `media`（`MediaFile`）、`core.uploads.validate_image_upload`；本模块只 `MediaFile.objects.create(...)` 并把它挂上 M2M／FK |
| 受保护件的取件与指纹响应头 | 本模块没有受保护件：配图一律进**公开**媒体库，页面直接用 `media.file.url`，没有取件视图 |
| 「谁能添加／下载」的判据 | `discussion.permissions.is_member`（登录 + 账号启用 + 已过首次改密）；`can_manage_awards` 只是它的业务别名 |
| 首页轮播的查询与渲染 | `accounts.views.home` 与 `templates/home.html`；本模块只建模与后台维护 |
| 「我的获奖」入口 | `accounts`：个人信息页链到 `content:awards?q=<姓名>`，匹配的是 `Award.winners` 的自由文本 |
| 顶部导航的高亮 | `core/context_processors.py` 把 `content:*` 的 URL 名映射成 `nav_section` |
| 后台删除的审计 | 不做：四个 `ModelAdmin` 只覆写 `save_model`，删行不留痕 |

## 2. 必须成立的断言

- **判重身份串（改动时最不能碰的一处）**：`similarity.identity_key(competition, tier, year, winners)`
  同时是**判重比较的对象**与**写入时咨询锁的键**（`create_award` 里
  `pg_advisory_xact_lock(hashtext(identity_key(...)))`）。改 `_COMPARED_FIELDS`、`normalize`、
  `fold_tier_terms` 里的任何一项，都会同时改变「锁的是谁」与「比的是谁」——**两处必须一起动**，
  否则锁住的不是正在比的那个东西。
- **判重口径**：同一年份 + 同一层级 + 同一批获奖人，只允许一条；层级比的是 `Award.tier` 枚举，
  不是证书措辞。**任何一侧为空就不比这一项**——「没填」不等于「不一样」，两边都要照顾：新记录空着时
  按「不一样」处理等于给重复开门，老记录空着时按「不一样」处理则永远拦不住重复。新记录的两个字段都为空时，
  第二关直接放弃（没有可算相似度的东西）。
- **两道关，先便宜后贵**：先比归一化折叠后的整串是否完全相同（多数重复在这关就拦下），
  再交给 `pg_trgm` 逐字段比相似度。逐字段而不是给整串打分，是因为整串相似度会被长字段稀释，
  短字段上的差别会被盖过去。**`FIELD_THRESHOLDS` 的 0.55 是按实测定的**（一字之差约 0.6，换人约 0.5），
  不是拍出来的。
- **年份是硬判据，也是预筛**：年份不等就不是同一条，先按年份筛一刀（走已有索引，**永远不会漏掉真正的
  重复**），剩下的候选再算相似度。**不建 GIN 索引**是刻意的：那种索引只在拿相似度当检索条件时才有用，
  这里年份已经把候选收到很小。
- **后台不判重是刻意留的后门**：`AwardAdmin` 不调用 `find_similar_award`，也不引 `similarity`。
  「同一层级只允许一条」的例外（换个赛道之类）正是从这里放行。任何「顺手给后台也加上判重」的改动
  都会关掉这条唯一的例外通道。
- **判重只有代码一条路，数据库没有唯一约束**：身份串不落库、没有 `UniqueConstraint`；
  `create_award` 之外（后台保存、脚本、`QuerySet.update`）都能造出重复记录。
- **层级规则的唯一真相源是 `Award.tier`；改 `tier_rules` 要连带检查的调用点**：
  判重比较前的折叠（`similarity.fold_tier_terms` / `normalize`）、迁移 `0006` 从自由文本回填 `tier`
  （`derive_tier`），以及只读命令 `report_duplicate_awards`（`drop_tier_terms` / `normalize`）
  ——改了折叠规则，那条命令报出的重复组会跟着变。回填只跑一次：规则日后调整，**已跑过迁移的库不受影响**。
  `tier_rules` 不 import 模型，正是为了让迁移能在历史状态上引它。
- **`tier` / `level` / `winners` 必填只是校验层**：两列本来就是 NOT NULL（允许空串），历史行里空着的仍在。
  模板里的 `{% if award.tier %}` / `{% if award.level %}` 与判重的空值规矩因此都要保留。
- **图片是公开件**：本模块建的 `MediaFile` 落 `MEDIA_ROOT`，页面直接用 `media.file.url`；
  与项目书、批注版那类受保护件不是一回事。`|file_url` 那道护栏针对的是「受保护件取不到地址」与
  「字段为空」，这两条在媒体库上都不成立（公开存储、`file` 必填），所以直接写 `.url` 是对的，
  **不要顺手改成空值兜底的写法**。单张上限复用 `media.validators` 那一份（两边不一致会出现
  后台能传、前台不能传）。
- **删媒体文件时两处行为不同**：挂在 `Showcase.photo` / `HomeSlide.image` 上的会被 `PROTECT` 挡下；
  挂在 `Award.certificates` / `photos` / `ContentPage.attachments` 上的不会——M2M 中间行跟着删，
  证书会**静默**从获奖页消失。

## 3. 已知限制 / 当前不支持

- **判重没有数据库约束**：不变量全靠 `create_award` 一条路把守。发现历史重复用
  `manage.py report_duplicate_awards`（只读，按比判重更严的口径分组——靠相似度才拦下的错别字那一档
  不报），合并要人判断，命令不替人做决定。
- **判重不带编辑场景**：`find_similar_award` 有 `exclude_pk`，但生产代码里没有调用方（只有测试用）；
  平台也没有前台编辑入口——成员加错了要管理员在后台处理。
- **后台删除不写审计**：`admin.py` 只覆写 `save_model`，删一条获奖或页面不留审计行。
- **日志没有监控与告警**：logger 已经配好、`logger.warning` 落 `logs/django.log`，
  但没人盯着这个文件——出问题仍然要有人主动去翻。
- **`certificates` 限图片只在校验层**：`limit_choices_to` 只约束后台表单的可选项；用 ORM 直接
  `award.certificates.add(<视频>)` 能加进去，打包时那段视频会被**分块抄进**临时文件再写进 zip
  ——真正的代价是临时文件长大（占磁盘），不是内存。这条限制的意义是「压缩包里不该出现大视频」。
- **`HomeSlide` 的图片类型只有 `clean()` 把关**：没有 `save()` 覆写，也没有数据库约束，
  `objects.create()` 可以塞一段视频进去。
- **前台只收图片**：`AwardForm` 两个字段都是 `MultipleImageField`，视频只能从后台挂。
- **打包的几条硬上限**：一次最多 `MAX_ARCHIVE_AWARDS` 条（`award` 是请求参数，条数由请求方说了算，
  不设上限一次请求就能把磁盘塞满）；条目名截断到固定长度，因为整条路径太长在 Windows 上解不开；
  同名条目靠序号而不是覆盖。
- **搜索是 `icontains`**：用不上索引；`year__icontains` 还要把整数列转成文本。这是为了「一个框搜全部」
  与「24 也命中 2024」付的代价。
- **`per_page` 非法值静默回落**，页面上不提示——参数来自地址栏，不为此打断浏览。
- **历史空值与历史重复都在**：必填只作用于校验层，迁移 `0005` 之前录进来的空行不会被改写；
  判重对它们「不比这一项」，也就拦不住。
- **`pg_trgm` 是硬依赖**：迁移 `0004_pg_trgm` 建扩展，只装 PostgreSQL server、没装 contrib 的机器上
  这一步会失败（`deploy/` 的脚本在 migrate 前会先探一次并给出安装命令）。
- **打包的临时文件与磁盘**：`archives.py` 是流式的（不攒内存）、用 `ZIP_STORED`（证书是 JPEG/PNG，
  再压一遍几乎不减小体积）、坏 id 静默丢弃（一串 `abc` 会让 `filter(pk__in=...)` 抛 `ValueError`
  ——一个「下载」按钮不该有本事把页面点成 500）；`next` 只认本站（否则这是一个任意跳转的开口）。

## 4. 由来

- **附件为什么按「用途」而不是「类型」分**（`certificates` / `photos`）：证书要能勾选打包下载，
  参赛图只在页面上看。所以证书限定只收图片（一段 500 MB 的视频不该混进压缩包），视频待在参赛图那边。
  迁移 `0003` 按类型分派了历史附件。
- **`tier` 与 `winners` 为什么必填**：两者各撑着一件事——层级是判重身份与浏览时的分辨依据，
  获奖人是「我的获奖」按姓名搜索所依附的那一项。`level`（证书上的写法，如「东北赛区一等奖」）
  与 `tier` 分开存：「省一等奖」与「东北赛区一等奖」是同一层，措辞差别不算差别。
- **已录入的重复不会自己消失**：命令按比判重更严的口径列出重复组，人工在后台留下一条、删掉其余。
