# content 模块

> 公开展示内容：通用公开页 `ContentPage`（含顶栏固定的 `/about/`）、历年获奖 `Award`
> （判重、成员前台录入、证书打包下载）、成员风采 `Showcase`、首页轮播 `HomeSlide`，
> 以及全站共用的 Markdown 渲染过滤器 `render_markdown`。
> **不碰媒体文件本身**——`MediaFile` 归 `media`，本模块只创建与引用它；
> **不定义「谁能做什么」**——`permissions.py` 只有一条委托；
> **不负责首页**——轮播由 `accounts.views.home` 查、在 `templates/home.html` 里渲染。
> 依赖它的有：`accounts`（首页读 `HomeSlide`、个人信息页链到获奖页）、`discussion` 与
> `notices`（详情模板用 `render_markdown`）、`core/context_processors.py`（导航高亮）。

**什么时候看**：改公开栏目或 `/about/`、动获奖判重与层级口径、改前台添加获奖表单与图片上限、
改证书打包下载、调 `render_markdown` 的白名单时。

---

## 1. 职责与边界

**负责**（都在 `content/` 下）：

| 东西 | 代码坐标 |
|---|---|
| 四张表：`ContentPage` / `Award` / `Showcase` / `HomeSlide`（含 `AWARD_TIER_CHOICES`） | `models.py` |
| 获奖判重：归一化、层级措辞折叠、pg_trgm 逐字段相似度、判重身份串 | `similarity.py` |
| 层级措辞的折叠与推断（纯文本、**不 import 模型**，数据迁移直接引） | `tier_rules.py` |
| 唯一一条判定：成员能否添加／打包下载 | `permissions.py`（委托 `discussion.permissions.is_member`） |
| 写操作：`create_award`（事务 + 咨询锁 + 判重 + 收图进媒体库 + 审计） | `services.py` |
| 只读查询：`search_awards`（单关键字 OR 多字段） | `selectors.py` |
| 证书打包：`build_certificate_archive`、`MAX_ARCHIVE_AWARDS` | `archives.py` |
| 表单与上传校验：张数上限、单张上限复用媒体库那一份 | `forms.py`、`validators.py` |
| 七个页面与路由：`about` / `page_index` / `page_detail` / `awards` / `award_create` / `award_certificates` / `showcase` | `views.py`、`urls.py`（挂 `config/urls.py` 的**根路径**，中文地址不带前缀） |
| 后台四个 `ModelAdmin`（都只覆写 `save_model` 记审计） | `admin.py` |
| 只读命令：列出疑似重复的获奖记录 | `management/commands/report_duplicate_awards.py` |
| 模板过滤器 `render_markdown`（**别的 app 也在用**） | `templatetags/rendering.py` |

**明确不做**——划出去的事，各自落在哪：

| 不在这里 | 落在哪 |
|---|---|
| 媒体文件本身：存储、`kind` / `caption` / `uploader` / `file_size` / `sha256`、上传校验实现、取件 | `media`（`MediaFile`）、`core.uploads.validate_image_upload`；本模块只 `MediaFile.objects.create(...)` 并把它挂上 M2M／FK |
| 受保护件的取件与指纹响应头 | 本模块没有受保护件：配图一律进**公开**媒体库（`/media/` 由 Nginx 直出），页面直接用 `media.file.url`，没有取件视图 |
| 「谁能添加／下载」的判据 | `discussion.permissions.is_member`（登录 + 账号启用 + 已过首次改密）；`can_manage_awards` 只是它的业务别名，不另写一份 |
| 首页轮播的查询与渲染 | `accounts.views.home`（函数内局部 import `HomeSlide`）与 `templates/home.html`；本模块只建模与后台维护 |
| 「我的获奖」入口 | `accounts`：个人信息页链到 `content:awards?q=<姓名>`，匹配的是 `Award.winners` 的自由文本 |
| 顶部导航的高亮 | `core/context_processors.py` 把 `content:*` 的 URL 名映射成 `nav_section` |
| 后台删除的审计 | 不做：四个 `ModelAdmin` 只覆写 `save_model`，删行不留痕（见 §6） |
| 跨模块的口径与由来（谁能用、地址总表） | `docs/architecture/permissions.md`、`docs/architecture/interfaces.md`；本文件只讲本模块 |

**依赖方向**

- 上游：`media`（`MediaFile` 的 M2M／FK，加载期 import——模型外键是分层约定的例外）、
  `core.uploads` / `core.audit` / `core.permissions.require` / `core.forms`、
  `discussion.permissions`（`permissions.py` 顶部 import），以及 PostgreSQL 的
  `pg_trgm`（迁移 `0004_pg_trgm` 装扩展，判重的相似度用它）。
- 下游：`accounts.views.home` 读 `HomeSlide`；`accounts` 的模板链到 `content:awards`；
  `templates/base.html` 与 `templates/home.html` 各有四个入口；
  `templates/discussion/space.html` 与 `templates/notices/detail.html` 用 `render_markdown`。
- **本 app 不向 `core.registry` 登记任何操作入口**（没有 `apps.ready()`），成员中心也不列它。

---

## 2. 关键接口与失败模式

权限函数只返回布尔，**从不抛异常**；403 全部产生在视图层。

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `views.about`（`/about/`） | 渲染 `slug="about"` 且已发布的 `ContentPage` | 无（公开页） | **永不 404**：内容没录或仍是草稿 → 空态；草稿正文不进响应 |
| `views.page_detail`（`/pages/<slug>/`） | 按 slug 渲染任意已发布页 | slug 命中且 `is_published=True` | 其余一律 404（`get_object_or_404`） |
| `views.page_index`（`/pages/`） | 已发布页清单，**排除 `slug="about"`**（它有固定入口，再列一次会指向两个地址） | 无 | 无异常；空清单给空态 |
| `views.awards`（`/awards/`） | 单关键字搜索 + 分页 | 无 | `per_page` 不在 `PER_PAGE_OPTIONS`（10／20／40）→ **静默回落** `DEFAULT_PER_PAGE`；`page` 越界由 `paginator.get_page` 收敛；无命中给「没有匹配」而不是空态 |
| `views.award_create`（`/awards/new/`） | 成员在前台添加一条获奖记录 | `@login_required` + `require(..., "content.awards.create.denied", action="create")` | 匿名 → **302** 到登录页；`must_change_password=True` → **302** 回改密页（中间件比视图更早）；已登录但 `can_manage_awards` 为假 → **403**（当前只有服务层/测试能构造出这种账号，见 §6）；判重命中 → **页面重渲染**并把已有那条写进 non-field error（不是 4xx）；年份越界 / 必填缺失 / 图片不合格 → 表单错误 |
| `views.award_certificates`（`/awards/certificates.zip`） | 把勾选记录的证书打成一个 zip 发回 | `@login_required` + `@require_POST` + `require(..., "content.awards.certificates.denied", action="download")` | GET → **405**；匿名 → 302；未勾选 / 一条证书都没有 / 超过 `MAX_ARCHIVE_AWARDS` → `messages.error` + 302 回列表；非数字与伪造 id 静默丢弃；盘上缺文件跳过并计入 `archive.missing` |
| `services.create_award` | 前台写获奖记录的**唯一**入口（后台走 `admin.py`，两条路平行） | 调用方已过权限门槛；`year` 非空 | 判重命中 → `DuplicateAward(existing)`；并发提交同一身份时 `pg_advisory_xact_lock` 把两者排成队，后一个在锁后重跑判重、因此看得见前一个刚写的行；锁随事务结束自动释放 |
| `similarity.find_similar_award` | 在同一年份（同层级）里找出与新记录重复的那一条 | `year` 必须非空 | `year` 为空 → `None`（没有可筛范围，也就没有「同一条」）；只读，不抛异常；`exclude_pk` 给编辑场景留的 |
| `selectors.search_awards` | 一个关键字在多字段间 OR（年份按整数列文本匹配，整词命中层级词时连 `tier` 一起找） | 只读 | 不抛异常；空关键字返回全部 |
| `archives.build_certificate_archive` | 打包证书，返回 `CertificateArchive(file, filename, packed, missing)` | `awards` 是**已取好的序列**，不是 QuerySet（打包过程中不再碰库） | 盘上缺文件 → 跳过并计入 `missing`；`packed == 0` 由调用方判成空包、不发空响应 |
| `permissions.can_manage_awards(user)` | 「能否添加记录、能否打包下载」 | — | 只返回布尔；为假时视图记警告并 **403** |
| `templatetags.rendering.render_markdown` | Markdown → 白名单清洗后的安全 HTML | 模板里 `{% load rendering %}` | 空值 → `""`；`<script>` / `<style>` 整块先删，再走 bleach（越界的标签被剥掉、文字保留） |

---

## 3. 状态与不变量

### 表与决定行为的字段

| `ContentPage` | 决定什么 |
|---|---|
| `slug` | `unique=True`；`/pages/<slug>/` 按它取页；后台 `prepopulated_fields` 从标题生成 |
| `is_published` | 唯一决定「外界看不看得到」的开关；未发布只有后台能看 |
| `content` | Markdown 源文（≤20000），渲染走 `render_markdown` |
| `attachments` | M2M `MediaFile`，可含视频；渲染在 `includes/media.html` |
| `updated_at` | `auto_now`，页面上「更新于」用它 |

| `Award` | 决定什么 |
|---|---|
| `year` / `tier` / `competition` / `winners` | **四者合起来就是判重身份**（见下）；`year` 还是预筛条件，吃 `Meta.indexes` 里的 `(-year, -created_at)` |
| `tier` | 三选一枚举，存储码定义在 `tier_rules`（`NATIONAL` / `PROVINCIAL` / `SCHOOL`）。`AWARD_TIER_CHOICES` 与折叠记号**必须是同一套**，否则「折出来相等」与「存下来相等」会变成两件事 |
| `level` | 证书上的原话（如「东北赛区一等奖」），只作展示与搜索，**不参与判重** |
| `title` | 同样不参与判重；页面标题与打包时的条目名用它 |
| `winners` | 「我的获奖」按姓名搜索依附的那一项；自由文本，页面经 `render_markdown` 渲染 |
| `certificates` | M2M `MediaFile`，`limit_choices_to={"kind": "image"}`；**打包下载只读它** |
| `photos` | M2M `MediaFile`，不限类型——视频待在参赛图这边 |
| `Meta.ordering` | `("-year", "-created_at", "-id")`，列表与打包取数都按它 |

| `Showcase` / `HomeSlide` | 决定什么 |
|---|---|
| `member`（`Showcase`） | FK `User`，`on_delete=PROTECT`：有人挂在风采里就删不掉账号 |
| `photo` / `image` | FK `MediaFile`，同样 `PROTECT`：这两处还在用的图删不掉 |
| `is_active` | 前台只列启用的；未启用只有后台可见 |
| `sort_order` | 页面顺序；并列时 `Showcase` 落到 `member__username`、`HomeSlide` 落到 `pk` |
| `HomeSlide.clean()` | 图片类型再查一次（`limit_choices_to` 只管表单选项，`clean` 管校验层） |
| 图片来自共享媒体库 | 两处都只挑已有的 `MediaFile`，**不复制文件** |

### 必须成立的断言

- **判重身份串（改动时最不能碰的一处）**：

  ```text
  identity_key(competition, tier, year, winners)
    = f"{year}\x1f{tier}\x1f" + field_shape(competition, winners)
  field_shape(...) = "\x1f".join(fold_tier_terms(normalize(字段)))
                     对 _COMPARED_FIELDS = ("competition", "winners") 依次求值
  ```

  它同时是**判重比较的对象**与**写入时咨询锁的键**（`create_award` 里
  `pg_advisory_xact_lock(hashtext(identity_key(...)))`）。改 `_COMPARED_FIELDS`、
  `normalize`、`fold_tier_terms` 里的任何一项，都会同时改变「锁的是谁」与「比的是谁」
  ——两处必须一起动，否则锁住的不是正在比的那个东西。
- **判重口径**：同一年份 + 同一层级 + 同一批获奖人，只允许一条；层级比的是
  `Award.tier` 枚举，不是证书措辞。**任何一侧为空就不比这一项**——「没填」不等于
  「不一样」，两边都要照顾：新记录空着时按「不一样」处理等于给重复开门，老记录空着时
  按「不一样」处理则永远拦不住重复。新记录的两个字段都为空时，第二关直接放弃（没有可算
  相似度的东西），因为第一关已经比过一遍了。
- **两道关，先便宜后贵**：先比归一化折叠后的整串是否完全相同（多数重复在这关就拦下），
  再交给 `pg_trgm` 逐字段比相似度；阈值 `FIELD_THRESHOLDS = {"competition": 0.55,
  "winners": 0.55}` 是按实测定的（一字之差约 0.6，换人约 0.5）。逐字段而不是给整串打分，
  是因为整串相似度会被长字段稀释，短字段上的差别会被盖过去。
- **年份是硬判据，也是预筛**：年份不等就不是同一条，先按年份筛一刀（走已有索引，**永远
  不会漏掉真正的重复**），剩下的候选再算相似度。**不建 GIN 索引**是刻意的：那种索引只在
  拿相似度当检索条件时才有用，这里年份已经把候选收到很小。
- **后台不判重是刻意留的后门**：`AwardAdmin` 不调用 `find_similar_award`，也不引
  `similarity`。「同一层级只允许一条」的例外（换个赛道之类）正是从这里放行。任何
  「顺手给后台也加上判重」的改动都会关掉这条唯一的例外通道。
- **判重只有代码一条路，数据库没有唯一约束**：身份串不落库、没有 `UniqueConstraint`；
  `create_award` 之外（后台保存、脚本、`QuerySet.update`）都能造出重复记录。
- **层级规则的唯一真相源是 `Award.tier`；改 `tier_rules` 要连带检查的调用点**：
  判重比较前的折叠（`similarity.fold_tier_terms` / `normalize`）、迁移 `0006` 从自由文本回填
  `tier`（`derive_tier`），以及只读命令 `report_duplicate_awards`（`drop_tier_terms` / `normalize`）
  ——改了折叠规则，那条命令报出的重复组会跟着变。回填只跑一次：规则日后调整，
  **已跑过迁移的库不受影响**，只有新建库的回填结果会变。
  `tier_rules` 不 import 模型，正是为了让迁移能在历史状态上引它。
- **`tier` / `level` / `winners` 必填只是校验层**：迁移 `0005` 改的是 `blank`（表单校验），
  两列本来就是 NOT NULL（允许空串），历史行里空着的仍在。模板里的
  `{% if award.tier %}` / `{% if award.level %}` 与判重的空值规矩因此都要保留。
- **图片是公开件**：本模块建的 `MediaFile` 落 `uploads/%Y/%m/`（`MEDIA_ROOT`，Nginx 直出），
  页面直接用 `media.file.url`；与项目书、批注版那类受保护件不是一回事。
  `|file_url` 那道护栏针对的是「受保护件取不到地址」与「字段为空」，这两条在媒体库上都不
  成立（公开存储、`file` 必填），所以 `includes/media.html` / `award_media.html` 直接写
  `.url` 是对的，不要顺手改成空值兜底的写法。
  单张上限 `MAX_IMAGE_BYTES = media.validators.IMAGE_MAX_BYTES`（**复用媒体库那一份**），
  每类图片张数 `IMAGE_LIMIT`，一次打包记录数 `MAX_ARCHIVE_AWARDS`。
- **删媒体文件时两处行为不同**：挂在 `Showcase.photo` / `HomeSlide.image` 上的会被
  `PROTECT` 挡下；挂在 `Award.certificates` / `photos` / `ContentPage.attachments` 上的
  不会——M2M 中间行跟着删，证书会**静默**从获奖页消失。

---

## 4. 数据流与时序

### 前台添加获奖记录（`views.award_create` → `services.create_award`）

1. 视图先过 `require(can_manage_awards)`（403 见 §2），GET 渲染 `AwardForm`，年份默认今年
   （`AwardForm.__init__`），年份只接受 `EARLIEST_YEAR` 到「今年 + 1」。
2. POST 校验通过后，`form.award_kwargs()` 把字段一一映射成服务参数——这份名单写在表单里，
   视图不抄第二遍。
3. 服务层在 `@transaction.atomic` 里：先按 `identity_key` 取
   `pg_advisory_xact_lock`（要锁的那一行此刻还不存在，`select_for_update` 锁不住不存在的
   东西），再 `find_similar_award` 判重。
4. 命中 → `DuplicateAward(existing)`；视图用 `_duplicate_message` 把「已有的是哪一条、
   哪个层级、谁拿的」写进 non-field error（判重不看奖项名，被拦下的那条奖名可能跟刚填的
   不一样，所以必须点名）。页面重渲染，仍停在表单上。
5. 未命中 → 建 `Award`；两类图片各经 `_store_images` 变成 `MediaFile`（**统一记成
   `kind=IMAGE`、`uploader=提交者`**），再 `certificates.set(...)` / `photos.set(...)`；
   同事务写 `content.award.create` 审计。
6. 成功 → `messages.success` + 302 到 `content:awards?q=<奖项名>`：新记录不一定在头一页，
   直接按奖项名搜给它看，省得人怀疑没提交上。

### 勾选打包下载证书（`views.award_certificates` → `archives.build_certificate_archive`）

1. 列表页的下载表单把整张列表包起来（勾选框与提交是同一件事）；**只有**
   `can_contribute and page_has_certificates` 时才渲染表单与全选框，单条还要自己有证书
   才有勾选框。表单带一个隐藏的 `next = request.get_full_path()`。
2. POST 进来先 `require`（403）→ `_selected_ids` 把 `award` 多值里**非纯数字的一律丢掉**
   （不丢的话，一串 `abc` 会让 `filter(pk__in=...)` 抛 `ValueError`——一个「下载」按钮
   不该有本事把页面点成 500）。
3. 按 `Meta.ordering` 取 `MAX_ARCHIVE_AWARDS + 1` 条：只取到 +1 是为了分辨「正好在上限」
   与「超了」，超了就 `messages.error` 回列表，不在磁盘上冒险。
4. `_back_to_awards` 只认本站的 `next`（`url_has_allowed_host_and_scheme`，`allowed_hosts`
   限本机），否则退回 `content:awards`——不校验的话这就是一个任意跳转的开口。
5. 打包：写 `tempfile.TemporaryFile`（不攒内存）、`ZIP_STORED`（证书是 JPEG/PNG，再压一遍
   几乎不减小体积）、条目名 `年份-奖项名[-序号].后缀`（一个奖多张才补序号；重名顺延
   `(2)`、`(3)`；奖项名先滤掉路径分隔符与 Windows 保留字符并截断）、盘上缺的文件跳过并计数。
6. 空包 → 关掉临时文件 + `messages.error`；否则 `FileResponse(as_attachment=True)`。
   缺文件的警告要等**下一次翻页**才显示得出来（响应本身是文件），所以那句话写得能独立成句。

### Markdown 渲染（`templatetags/rendering.py`）

1. 空值直接返回 `""`；否则先用正则删掉成对的 `<script>` / `<style>` 整块。
2. `markdown.markdown(value, extensions=["extra", "sane_lists"])`——表格、围栏代码块靠 `extra`。
3. `bleach.clean(..., strip=True)`：`ALLOWED_TAGS` 是 bleach 默认标签加一组块级标签
   （标题、列表、表格、`pre`/`code`、`blockquote` 等）；`ALLOWED_ATTRIBUTES` 只放
   `a[href,title,rel]`、`code[class]`、`th/td[align]`；`ALLOWED_PROTOCOLS` 只有
   `http` / `https` / `mailto`。最后 `mark_safe`。
4. 消费者不止本模块：`content` 的公开页、获奖人、风采简介，以及 `discussion` 的帖子正文、
   `notices` 的公告详情。**改白名单等于同时改这几处的安全面**。

---

## 5. 错误处理与诊断

**领域异常只有一个**：`services.DuplicateAward`（带着 `existing`），视图把它翻成表单错误。
`archives.py` 与 `tier_rules.py` 不抛领域异常；地址栏来的参数（`per_page`、`award` id）
一律**静默过滤**，不报错也不 4xx。

**拒绝形态**（页面上的实际表现）：

| 情形 | 表现 |
|---|---|
| 匿名访问 `/awards/new/`、`/awards/certificates.zip` | 302 到登录页（带 `next`） |
| 已登录但首次改密未完成，访问这两个入口 | **302** 回改密页——`ForcePasswordChangeMiddleware` 比视图里的门槛更早 |
| 已登录但 `can_manage_awards` 为假（如已停用或被撤销资格） | **403**，`core.permissions.require` 先记一条 WARNING |
| 对 `/awards/certificates.zip` 发 GET | 405（`@require_POST`） |
| 未发布或不存在的内容页 | 404 |
| 不存在或未发布的 `/about/` | **空态，不是 404**——顶栏固定入口不该在内容没录时直接报错 |
| 判重命中 | 200 重渲染表单 + non-field error（不是 409、不是 302） |
| 未勾选 / 勾了但没有证书 / 超过 `MAX_ARCHIVE_AWARDS` | 302 回列表 + `messages.error` |
| 勾选里混了伪造 id | 静默丢弃，其余照打包 |
| 证书文件不在盘上 | 跳过，`messages.warning` 在下一次页面请求时出现 |
| `?per_page=100000` | 静默按 10 条渲染（`_per_page` 白名单） |

**审计 action**（`core.audit.record_audit`，**发过的字符串不再改**）：

| action | 触发点 |
|---|---|
| `content.award.create` | `services.create_award`（前台）与 `AwardAdmin.save_model`（后台新建）**共用同一个字符串** |
| `content.award.update` | 后台改一条获奖记录 |
| `content.page.create` / `content.page.update` | `ContentPageAdmin.save_model` |
| `content.home_slide.create` / `.update` | `HomeSlideAdmin.save_model` |
| `content.showcase.create` / `.update` | `ShowcaseAdmin.save_model` |

**日志**：`logging.getLogger(__name__)`，带 `extra={"request_id": ...}`——**一处例外**：`archives.py` 的 `content.awards.archive.missing` 那条 warning 在视图之外（拿不到 request），没有 `extra`。
事件名分两类——`content.*`（`content.page.view`、`content.page_index.view`、`content.about.view`、
`content.awards.view`、`content.showcase.view`、`content.awards.create.success` / `.failure`、
`content.award.create.duplicate` / `.success`、`content.awards.certificates.download`、
`content.awards.archive.missing`）与 `admin.*`（`admin.content_page.save`、`admin.award.save`、
`admin.home_slide.save`、`admin.showcase.save`）。

**级别**：`config/settings.py` 的 `LOGGING["loggers"]` 里有 `content` 这一节，`DEBUG` 级、
`console` + `file` 两个 handler，上面这些事件都落 `logs/django.log`（`config/tests.py` 的
`AppLoggerTests` 盯着这条）。早先这一节是缺的（root 也没有 handler），这些 `logger.info`
连级别检查都过不去——那时排查 content 只能看数据库里的审计行与页面表现。

**刻意不报错**：

- **后台不判重**（见 §3）：后台保存一条与既有记录同身份的奖，静默成功——那是给
  「确实是另一条」留的放行口。
- `/about/` 没有内容、`page_index` 没有页面 → 空态，不是错误。
- 搜索无命中 → 「没有匹配…」，与「暂时没有获奖记录」分开说。
- 重复提交、坏 id、缺文件 → 见上表，都不响。
- `HomeSlide.clean()` 只在**校验层**拦视频：后台表单会拦，`objects.create()` 不会。

---

## 6. 测试要点与已知限制

### 测试

测试全在 `content/tests.py`（单文件、按类分主题），夹具用临时媒体根，不在仓库里留孤儿文件。

| 测试类 | 钉住什么 |
|---|---|
| `PublicContentAcceptanceTests` | `/about/` 与 `/pages/about/` 同一页；任意已发布 slug 公开、未发布 404、缺页 404；`page_index` 排除 about；首页轮播按序渲染且只列启用项；`HomeSlide` 拒视频；Markdown 清洗；视频在公开页能渲染；后台能建页而成员不能；获奖的证书与参赛图分栏 |
| `AwardSearchAndPagingTests` | 关键字命中姓名／指导老师／赛事／奖名／级别，年份按前缀（「24」命中 2024）；整词层级词连 `tier` 一起找；赛事名里含「全国」不会搜出整个国家级；每页条数只认白名单；分页链接带住 `q` 与 `per_page` |
| `CertificateArchiveTests` | 只打证书（参赛图不进包）；下载名与 UTF-8；重名补序号；游客 302、GET 405；未勾选／无证书／超条数的提示；伪造 id 不炸；缺文件跳过；勾选框只给成员、且只在有证书时出现 |
| `TierRulesTests` | 省一等奖／东北赛区一等奖折成同一记号、名次词保留、赛事名不被折叠吃掉；`derive_tier` 看名次词前的限定词并会回退到下一个文本 |
| `AwardTierBackfillTests` | 迁移 `0006` 的回填执行路径：认得出的写、认不出的留空并打印 |
| `AwardSimilarityTests` | 归一化（全半角、大小写、空白、标点）；完全相同、错一字、换层级、省级措辞、换人、加人、跨年、跨赛事各自的结论；老记录空字段仍参与比较、空层级不否决、新记录留空不绕过；`exclude_pk`；无年份；几百条时仍有界 |
| `DuplicateAwardReportTests` | 报告的分组口径（只差措辞、赛事名里的赛区、无层级老记录都归组）且**不改数据** |
| `MemberAwardCreateTests` | 成员带图加记录、图片进共享媒体库、写审计；各类重复被拒并指名已有那条；年份越界；六个文本字段必填（模型层同样）；层级落库、指导老师可空；图片超张数、非图片被拒；年份默认今年 |
| `AwardFormTranslationTests` | 表单标签、`tier` 选项、提示语全是惰性译文（英文界面不冒中文），且不复用模型的 `verbose_name` |

### 已知限制 / 当前不支持

- **判重没有数据库约束**：不变量全靠 `create_award` 一条路把守；后台保存、脚本、直接
  `QuerySet.update` 都能造出两条同身份的记录。发现历史重复用
  `manage.py report_duplicate_awards`（只读，按比判重更严的口径分组——靠相似度才拦下的
  错别字那一档不报），合并要人判断，命令不替人做决定。
- **判重不带编辑场景**：`find_similar_award` 有 `exclude_pk`，但生产代码里没有调用方
  （只有测试用）；平台也没有前台编辑入口——成员加错了要管理员在后台处理。
- **后台删除不写审计**：`admin.py` 只覆写 `save_model`，`delete_model` / `delete_queryset`
  没动，删一条获奖或页面不留审计行。
- **日志没有监控与告警**：`content` 的 logger 已经配好、`logger.warning`（如
  `content.awards.archive.missing`）落 `logs/django.log`，但没人盯着这个文件——出问题仍然要
  有人主动去翻。
- **`certificates` 限图片只在校验层**：`limit_choices_to` 只约束后台表单的可选项；
  用 ORM 直接 `award.certificates.add(<视频>)` 能加进去，打包时那段视频会被**分块（1 MiB）抄进
  临时文件再写进 zip**——`archives.py` 是流式的，不会把它整个读进内存；真正的代价是临时文件
  长大（占磁盘）。这条限制的意义是「压缩包里不该出现大视频」，不是内存保护。
- **`HomeSlide` 的图片类型只有 `clean()` 把关**：没有 `save()` 覆写，也没有数据库约束，
  `objects.create()` 可以塞一段视频进去；后台表单会走到 `clean()`。
- **前台只收图片**：`AwardForm` 两个字段都是 `MultipleImageField`（`accept="image/*"`），
  视频只能从后台挂——`Award.photos` 本身不限类型。
- **打包的几条硬上限**：一次最多 `MAX_ARCHIVE_AWARDS` 条（`award` 是请求参数，条数由请求方
  说了算，不设上限一次请求就能把磁盘塞满）；条目名截断到固定长度，因为整条路径太长在
  Windows 上解不开；同名条目靠序号而不是覆盖。
- **搜索是 `icontains`**：用不上索引；`year__icontains` 还要把整数列转成文本。这是为了
  「一个框搜全部」与「24 也命中 2024」付的代价，当前量级（几百条）够用。
- **`per_page` 非法值静默回落**，页面上不提示——参数来自地址栏，不为此打断浏览。
- **历史空值与历史重复都在**：`tier` / `level` / `winners` 的必填只作用于校验层，
  迁移 `0005` 之前录进来的空行不会被改写；判重对它们「不比这一项」，也就拦不住。
- **`pg_trgm` 是硬依赖**：迁移 `0004_pg_trgm` 建扩展，只装 PostgreSQL server、没装 contrib
  的机器上这一步会失败（`deploy/` 的脚本在 migrate 前会先探一次并给出安装命令）。
