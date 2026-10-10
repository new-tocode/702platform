# media 模块

> 共享媒体库：一张表 `MediaFile`，登记已上传的图片与视频，供各内容模型通过 M2M／FK 引用。
> **它只是文件的登记处**：不判「谁能上传」、不存引用关系、不提供取件地址——文件落
> `mediafiles/`，由 Nginx 的 `/media/` 直出。
> 用它的是 `content`（首页轮播、历年获奖、成员风采、公开页配图、证书打包）与 `notices`
> （公告配图）；`discussion` 的帖子图**不是**它（受保护件，另一个模型 `PostImage`）。

**什么时候看**：改上传校验（扩展名／大小／MIME／签名）、动 `MediaFile` 的字段或后台表单、
碰 `/media/` 直出与体积上限，或要回答「这张图删了会怎样」时。

---

## 1. 职责与边界

| 面 | 落点 |
|---|---|
| 一张表 `MediaFile`（字段见 §3） | `models.py` |
| 上传校验：`validate_media_file(uploaded_file, kind)`、`IMAGE` / `VIDEO`、两个上限常量、视频签名 | `validators.py` |
| 后台入口 `MediaFileAdmin`：列表、筛选、搜索、审计与日志 | `admin.py` |
| app 配置（`verbose_name="媒体库"`；无 `ready()`，不向 `core.registry` 登记入口） | `apps.py` |

**明确不做**：

| 不做 | 落在哪 |
|---|---|
| 「谁能上传／引用」的判定 | 各引用方自己的后台表单与权限；本 app 没有 `permissions.py` |
| 引用关系 | 全在引用方：`content.models` 的 `ContentPage.attachments`、`Award.certificates` / `photos`、`Showcase.photo`、`HomeSlide.image`，与 `notices.models.Notice.attachments` |
| 取件、地址、模板 | 没有 `views.py` / `urls.py` / `templates/`：文件由 Nginx 的 `location /media/` 直出，页面自己写 `{{ media.file.url }}` |
| 图片校验的实现 | `core.uploads.validate_image_upload`（头像、图册、帖子图共用同一份）；本 app 只出上限与视频那一半 |
| SHA-256 的算法 | `core.hashing.FileDigestMixin`；模型只声明 `digest_field = "file"` |

**没有的模块**：`views` / `urls` / `permissions` / `services` / `selectors` / `panels` /
`forms` 一个都没有——一个 `ModelAdmin` 加一个校验器就是全部代码。

**依赖方向**：上游 `core.hashing`、`core.uploads`、`core.audit`；下游 `content` 与 `notices`
（加载期 `from media.models import MediaFile`，模型外键是分层约定允许的例外），
`content/validators.py` 还直接引 `media.validators.IMAGE_MAX_BYTES`。

---

## 2. 关键接口与失败模式

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `MediaFile.save()` | 唯一的写路径：写 `file_size` → `full_clean()` → 算 `sha256` → 落盘 | — | 校验不过抛 `ValidationError`（**不是数据库约束**，也不是 500） |
| `MediaFile.clean()` | 有文件时调 `validate_media_file(self.file, self.kind)` | — | 文案见 §5 |
| `validators.validate_media_file(file, kind)` | 扩展名 → 大小 → MIME 家族 → 二进制签名 | — | 一律抛 `ValidationError`；`kind` 既非 `image` 也非 `video` → `媒体类型无效。` |
| `validators.IMAGE_MAX_BYTES` | 图片单张上限；`content/validators.py` 拿它当 `MAX_IMAGE_BYTES`（理由：这些图上传后进的就是媒体库，两边不一致会出现后台能传、前台不能传） | — | 常量，不会失败 |
| `MediaFileAdmin` | 后台上传、改说明、删行；`uploader` / `file_size` / `sha256` / `created_at` 只读，新建时 `uploader` 填当前管理员 | Django 后台的门槛（`is_staff` + 模型权限），本 app 不另判 | 删除**不写审计**（见 §6） |
| `validators.IMAGE` / `VIDEO` | 字符串 `"image"` / `"video"`；`MediaFile.IMAGE` / `VIDEO` 是同一批值 | — | — |

**前台唯一写入口不在本 app**：`content.services._store_images` 为成员添加获奖时直接
`MediaFile.objects.create(file=upload, kind=MediaFile.IMAGE, uploader=提交者)`，走的是同一个
`save()` 与同一套校验。

---

## 3. 状态与不变量

| 字段 | 决定什么 |
|---|---|
| `file` | `FileField(upload_to="uploads/%Y/%m/")`，落 `MEDIA_ROOT`（`mediafiles/`）；必填；**原文件名保留**（uuid 换名只针对受保护件，见 `docs/glossary.md`） |
| `kind` | `image` / `video` 二选一：决定走哪套校验，也是引用方 `limit_choices_to` 的筛选依据 |
| `caption` | ≤255、可空；后台列表与 `__str__` 用它，页面拿它当 `alt`／说明 |
| `uploader` | FK `User`，`PROTECT`，`related_name="uploaded_media"`；后台只读 |
| `file_size` | `editable=False`；每次 `save()` 都从 `self.file.size` 重写（**盘上文件被手工删掉时，这一步会直接抛 `FileNotFoundError`**，保存失败而不是留下一个旧数字） |
| `sha256` | 来自 `FileDigestMixin`，`editable=False`；每次 `save()` 让指纹跟上文件 |
| `created_at` | `auto_now_add`；`Meta.ordering` 是 `("-created_at", "-id")` |

**必须成立的断言**

- **校验只有 `save()` 一个把关点**：`save()` 里 `full_clean()`，所以每次保存都重跑一遍
  上传校验（含只改 `caption` 的那次）；`QuerySet.update()` / `bulk_create` 绕过 `save()`，
  也就绕过了校验。`media/tests.py` 正是靠 `save()` 抛 `ValidationError` 来钉规则的。
- **`kind` 必须与文件真实类型一致**：扩展名、MIME、二进制签名三关都对着 `kind` 比。
  图片的扩展名集合是 `core.uploads.IMAGE_EXTENSIONS`（`gif/jpeg/jpg/png/webp`），
  视频是 `validators.VIDEO_EXTENSIONS`（`mp4`／`webm`）。
- **它是公开件那一类**：消费方都是对匿名访客开放的页面，所以文件落 `mediafiles/`，
  `{{ media.file.url }}` 正常给地址（`docs/development.md` §3.3：公开媒体「因为它本来就
  对匿名访客开放」由 Nginx 直出）。需要判权限的图（帖子图、头像、图册）刻意不进这里，
  它们落 `protected_media/` 且模板要走 `|file_url`。
- **单张上限**：图片 10 MB、视频 500 MB；nginx 的 `client_max_body_size 520m` 为视频留了
  余量——**改上限要同时看它**。超过 `FILE_UPLOAD_MAX_MEMORY_SIZE`（5 MB）的上传走临时文件，
  不占内存；指纹也是分块读（`core.hashing.CHUNK_SIZE`），500 MB 的视频不整份进内存。
- **删不掉的是上传人，不是引用**：`uploader` 是 `PROTECT`，有媒体记录的账号删不掉；
  但 M2M 引用不保护——删一张挂在 `Award.certificates` 上的图，中间行跟着消失，
  证书会静默从获奖页少一张（见 §6）。

---

## 4. 数据流与时序

**后台上传一张图 → 被内容模型引用 → Nginx 直出**

1. 管理员在 `/admin/media/mediafile/add/` 提交 `file` / `kind` / `caption`；从
   `ContentPage.attachments`、`Award.certificates`、`Notice.attachments` 这些 M2M 字段旁的
   「+」进来也是同一张表单。
2. `MediaFile.save()`：先写 `file_size`，再 `full_clean()`（字段层的 choices 与 `max_length`
   → `clean()` → `validate_media_file` 的扩展名／大小／MIME／签名），再由 `FileDigestMixin.save()`
   算 `sha256`，最后落盘到 `mediafiles/uploads/<年>/<月>/<原文件名>`。
3. `MediaFileAdmin.save_model`：新建时把 `uploader` 填成当前管理员，写 `media.create`
   （改则 `media.update`）审计与一条 `admin.media.save` 日志。
4. 在内容模型的后台表单里把它挂上 M2M／FK——**引用不复制文件**，同一张图可以被多处引用。
5. 页面渲染 `{{ media.file.url }}` → `/media/uploads/<年>/<月>/<原文件名>`
   （`MEDIA_URL` + `upload_to`）。
6. 浏览器请求该地址 → Nginx `location /media/ { alias …/mediafiles/; }` 直出
   （`expires 7d; access_log off;`），**不经过 Django，也没有权限判定**。

**成员前台加获奖**走 `content.views.award_create` → `content.services.create_award` →
`_store_images` 建 `MediaFile`，其余环节与上面第 2、4–6 步完全相同。

---

## 5. 错误处理与诊断

**拒绝形态**：校验不过一律抛 `ValidationError`，后台表单把它显示成表单错误（文案可直接
展示），脚本与 ORM 写入则在 `save()` 处直接抛异常。**没有领域异常、没有取件视图**——
文件是公开件，任何拿到 URL 的人都能取，不需要（也不该）在取件路上加判定。

| 情形 | 文案（`media/validators.py` 与 `core/uploads.py`） |
|---|---|
| 没选文件 | `请选择要上传的文件。` |
| 图片扩展名不在白名单 | `图片仅支持 gif、jpeg、jpg、png、webp 格式。` |
| 图片超 10 MB | `图片不能超过 10 MB。` |
| 图片 MIME 不是 `image/` | `文件类型与图片不符，请确认选的是图片。` |
| 内容不是真图片 | `上传文件不是有效的图片。` |
| 图片像素超 `MAX_IMAGE_PIXELS`（6400 万） | `图片过大（W×H 像素），请压缩后再上传。` |
| 视频扩展名不是 mp4／webm | `video 类型仅支持：mp4, webm。` |
| 视频超 500 MB | `video 文件不能超过 500 MB。` |
| 视频 MIME 不是 `video/` | `文件 MIME 类型与所选媒体类型不匹配。` |
| mp4 前 64 字节没有 `ftyp`；webm 头不是 EBML 魔数（`\x1a\x45\xdf\xa3`） | `上传文件不是有效的 MP4 视频。` / `上传文件不是有效的 WebM 视频。` |

**诊断锚点**

| 类型 | 值 |
|---|---|
| 审计 action（发过不再改） | `media.create` / `media.update`；detail 是 `{"kind", "file_size"}` |
| 日志锚点 | `admin.media.save`（带 `request_id`、`media_id`、`filename`、`kind`、`size`、`created`） |
| 校验出问题先看哪 | 文案出自哪个文件——图片那几支在 `core/uploads.py`（头像、图册共用），视频全在 `media/validators.py` |

**注意文案里的码值**：视频那两支是 `f"{VIDEO} …"` 拼的，`VIDEO = "video"`，所以页面上
看到的是「video 类型仅支持…」，不是「视频」。这一支没有接 gettext——`media/validators.py`
不引 gettext，媒体库只在后台用，而后台不在双语范围内（`content/validators.py` 的注释
记的是同一个口径）。

---

## 6. 测试要点与已知限制

**测试**：`media/tests.py` 的 `MediaValidationAcceptanceTests` 覆盖——合法 PNG 落
`uploads/`、`file_size > 0`、盘上真有文件；`sha256` 等于上传字节的 SHA-256；合法 MP4 能存；
扩展名、MIME、二进制签名（图片与视频各一）不匹配都被拒；图片当视频、视频当图片都被拒；
超 10 MB 的图被拒且文案含「不能超过 10 MB」。跨模块另有两处钉着本模块：
`core/tests/test_upload_validation.py`（`validate_media_file(..., IMAGE)` 也挡解压炸弹）与
`content/tests.py`（走后台上传口 `admin:media_mediafile_add` 并断言 `uploader` 记成当前管理员；
若干测试建 `MediaFile` 供内容模型引用）。

### 已知限制 / 当前不支持

- **`sha256` 是校验值，不是去重键**：没有唯一约束也没有查重，同一份文件传两次就是两行、
  两份盘上文件。指纹在媒体库上只活在后台与数据层（模型注释里写着它管的是「这张照片还是
  当初上传的那张吗」），不像项目书那样随响应头送出。
- **后台删除不写审计**：`MediaFileAdmin` 只覆写 `save_model`，删行不留痕（与 `content` 同款）。
- **原文件名会进 URL**：公开件不做 uuid 换名（`docs/glossary.md` 的「落盘名」条目只覆盖
  受保护件），上传时叫什么，`/media/uploads/<年>/<月>/…` 里就是什么——名字带人名、组名
  就会原样出现在地址栏与备份里。要藏文件名就得落受保护件。
- **校验只在 `save()` 上**：`QuerySet.update()`、`bulk_create` 这类不调用 `save()` 的写法
  一律绕过；`kind` 与文件真实类型的一致性由它兜着，绕过就没有兜底。
- **`limit_choices_to` 只管后台表单的可选项**：`HomeSlide.clean()` 在图片类型上又查一次，
  `Award.certificates` 没有这一道，ORM 能塞进视频（`content` 的 README 记了这条）。
- **删引用的后果分两种**：挂 `Showcase.photo` / `HomeSlide.image` 的会被 `PROTECT` 挡下；
  挂 M2M 的不会——中间行跟着删，证书静默消失。
- **媒体库不判权限**：能上传的只有后台账号（Django 的 `is_staff` + 模型权限），前台唯一的
  写入口是成员添加获奖时收图（`content.services._store_images`）。**别把需要判权限的文件
  放进来**——`/media/` 直出没有任何权限判定。
- **本期不做视频转码／多码率**：校验只认扩展名与文件头魔数（MP4 查 `ftyp`、WebM 查 EBML），
  **编解码格式本身不校验**——HEVC 封进 MP4 一样能过，浏览器放不放得出来平台不管。所以要
  传 MP4（H.264）或 WebM 是**约定**，不是强制。由 Nginx 静态直出并支持 Range 拖动播放；
  视频量大了以后再引入 ffmpeg 转码或对象存储。
- **「统一媒体库」的用意**：公开页、通知、风采引用同一份文件，将来切对象存储只改一处存储配置。
