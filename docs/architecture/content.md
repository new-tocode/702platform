# 6.3 content（公开展示页）

> 公开展示页与媒体库：社团简介、获奖、风采、首页轮播，以及统一的上传与校验。

**什么时候看**：加一个公开栏目，或改上传的类型／大小口径。

---

```
ContentPage（通用内容页，如「社团简介」）
  - slug           页面标识（唯一，如 about）
  - title          标题
  - content        正文（Markdown/富文本）
  - is_published   是否发布
  - updated_at
  - attachments    M2M(MediaFile, blank=True)  配图/视频

Award（历年获奖）
  - title          奖项名称
  - competition    赛事名称
  - year           年份
  - tier           获奖层级（national/provincial/school，判重身份的一部分，必填）
  - level          证书上的级别写法（自由文本，如「东北赛区一等奖」，必填；只作展示与搜索）
  - winners        获奖人/团队描述（必填）
  - advisor        指导老师（自由文本，可空）
  - certificates   M2M(MediaFile, blank=True, 限图片)  获奖证书——可打包下载的那一类
  - photos         M2M(MediaFile, blank=True)          参赛图片——现场图、参赛留影、视频
  - created_at

Showcase（成员风采）
  - member         FK(User)  展示的成员
  - intro          简介文字
  - sort_order     排序
  - is_active      是否启用
  - photo          FK(MediaFile)  展示照片/视频

HomeSlide（首页轮播）
  - image          FK(MediaFile, 限图片)  滚动区用图，取自共享媒体库
  - title          说明文字（可空，回退到图片 caption）
  - sort_order     排序
  - is_active      是否启用
  - created_at
```

> 平台概览数字（在册成员／项目组／开放竞赛／在借设备）由 `core/stats.py` 提供，
> 只对管理员与项目组联系人呈现，展示在成员中心；公开首页不再展示这些内部规模数据。

#### 获奖页的四件事

改动这块时要看住的四条口径，细节在各模块的 docstring 里：

- **搜索与分页**（`selectors.py` / `views.py`）：一个关键字在奖项、赛事、级别、获奖人、
  指导老师之间 OR，年份单独按整数列的文本匹配（「24」也命中 2024）；整词命中
  「省级/国家级/赛区」这类词时连结构化层级一起找——页面上那条写的是「东北赛区一等
  奖」，字面上并不含「省级」。每页条数只认
  10／20／40 三个值——`per_page` 来自地址栏，白名单之外一律回落默认，否则
  `?per_page=100000` 就是一次全表渲染。
- **附件分两类**（`models.py`）：`certificates` 与 `photos` 不是「图片／视频」那种
  类型划分，而是**用途**划分——证书要能勾选打包下载，参赛图只在页面上看。所以
  证书限定只收图片（一段 500 MB 的视频不该混进压缩包），视频待在参赛图那边。
  迁移 `0003` 按类型分派历史附件：图片进证书，视频进参赛图。
- **打包下载**（`archives.py`）：写临时文件而不是攒内存；`ZIP_STORED` 而不是 Deflate
  （证书是 JPEG/PNG，再压一遍几乎不减小体积）；条目名 `年份-奖项名` 并在重名时补
  序号；盘上缺的文件跳过而不是让整包下不成。入口只对登录成员开放，一次最多 100 条。
- **层级与获奖人必填**（`models.py`）：两者各自撑着页面上的一件事——层级是判重身份
  与浏览时的分辨依据（页面上挂在标题旁的小标），获奖人是「我的获奖」按姓名搜索所
  依附的那一项。`level`（证书上的写法）与 `winners` 都是必填，但 `blank=False` 只管
  校验层（两列本来就是 NOT NULL），所以历史行里空着的还在，模板的
  `{% if award.tier %}` / `{% if award.level %}` 与判重里「任一侧为空就不比这一项」
  的规矩都因此保留。
- **判重**（`similarity.py`）：口径是「同一年份 + 同一赛事 + 同一批获奖人 + 同一层级」。
  层级是结构化字段（`tier`）而不是证书上的写法——「省一等奖」与「东北赛区一等奖」
  是同一层，措辞差别不算差别；同一层级下只允许一条，确实是另一条的（换个赛道之类）
  走后台那条放行的路。**逐字段**比而不是给整串打分——整串相似度会被长字段稀释，
  赛事名几十个字、获奖人几个字，合在一起算，短字段上换个人也未必跌破阈值。相似度
  用 PostgreSQL 的 `pg_trgm`（迁移 `0004` 建扩展），年份是硬判据因而也是预筛条件，
  走的正是 `Award.Meta.indexes` 里已有的那个索引；层级是精确相等，空值不否决
  （回填时认不出层级的老记录）。措辞的折叠与推断在 `tier_rules.py`：纯文本、不碰
  模型，迁移回填直接引它。写入侧的锁与这里用的是同一个身份串（`identity_key`），
  改动时两者不能分开改。已经录进去的重复不会自己消失：`manage.py
  report_duplicate_awards` 按同一口径把重复组列出来（只读），人工在后台留下一条、
  删除其余。

> 添加表单是**成员用的前台表单**，标签在 `AwardForm.Meta.labels` 里点名、提示语的数字
> 走 `format_lazy`——两条都是「英文界面上不能出现中文」的老坑，见
> [development.md 的双语一节](../development.md)。

> **成员在前台加记录**（`views.award_create` → `services.create_award`）与后台
> （`admin.py`）是两条并行的路：前台判重、后台不判——「确实是另一条」的例外由管理员
> 在后台放行，这是刻意留的后门，不是漏掉的检查。

---

### 6.9 media（媒体库）

```
MediaFile（统一媒体库，供各内容模型通过 M2M/FK 引用）
  - file          FileField(upload_to='uploads/%Y/%m/')
  - kind          image | video
  - caption       说明文字（可选）
  - uploader      FK(User)
  - file_size     文件大小（字节）
  - sha256        file 的 SHA-256 指纹（上传时自动算，见 [core.md](core.md)）
  - created_at
```
