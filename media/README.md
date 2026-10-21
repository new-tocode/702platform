# media 模块

> 共享媒体库：一张表 `MediaFile`，登记已上传的图片与视频，供各内容模型通过 M2M／FK 引用。
> **它只是文件的登记处**：不判「谁能上传」、不存引用关系、不提供取件地址——文件落
> `mediafiles/`，由 Nginx 的 `/media/` 直出。
> 用它的是 `content` 与 `notices`；`discussion` 的帖子图**不是**它（受保护件，另一个模型 `PostImage`）。

**什么时候看**：改上传校验（扩展名／大小／MIME／签名）、动 `MediaFile` 的字段或后台表单、
碰 `/media/` 直出与体积上限，或要回答「这张图删了会怎样」时。

---

## 1. 明确不做什么

| 不做 | 落在哪 |
|---|---|
| 「谁能上传／引用」的判定 | 各引用方自己的后台表单与权限；本 app 没有 `permissions.py` |
| 引用关系 | 全在引用方：`content` 的展示模型与 `notices.models.Notice.attachments` |
| 取件、地址、模板 | 没有 `views.py` / `urls.py` / `templates/`：文件由 Nginx 的 `location /media/` 直出，页面自己写 `{{ media.file.url }}` |
| 图片校验的实现 | `core.uploads.validate_image_upload`（头像、图册、帖子图共用同一份）；本 app 只出上限与视频那一半 |
| SHA-256 的算法 | `core.hashing.FileDigestMixin`；模型只声明 `digest_field = "file"` |

一个 `ModelAdmin` 加一个校验器就是全部代码。

## 2. 必须成立的断言

- **校验只有 `save()` 一个把关点**：`save()` 里 `full_clean()`，所以每次保存都重跑一遍上传校验
  （含只改 `caption` 的那次）；`QuerySet.update()` / `bulk_create` 绕过 `save()`，也就绕过了校验。
- **`kind` 必须与文件真实类型一致**：扩展名、MIME、二进制签名三关都对着 `kind` 比。
- **它是公开件那一类**：消费方都是对匿名访客开放的页面，所以文件落 `mediafiles/`，
  `{{ media.file.url }}` 正常给地址。**别把需要判权限的文件放进来**——`/media/` 直出没有任何权限判定；
  需要判权限的图（帖子图、头像、图册）刻意不进这里。
- **单张上限**：图片 10 MB、视频 500 MB；nginx 的 `client_max_body_size` 为视频留了余量——
  **改上限要同时看它**。超过 `FILE_UPLOAD_MAX_MEMORY_SIZE` 的上传走临时文件，不占内存；
  指纹也是分块读，500 MB 的视频不整份进内存。
- **删不掉的是上传人，不是引用**：`uploader` 是 `PROTECT`，有媒体记录的账号删不掉；
  但 M2M 引用不保护——删一张挂在 `Award.certificates` 上的图，中间行跟着消失，证书会**静默**
  从获奖页少一张。

## 3. 已知限制 / 当前不支持

- **`sha256` 是校验值，不是去重键**：没有唯一约束也没有查重，同一份文件传两次就是两行、
  两份盘上文件。指纹在媒体库上只活在后台与数据层，不像项目资料那样随响应头送出。
- **后台删除不写审计**：`MediaFileAdmin` 只覆写 `save_model`，删行不留痕（与 `content` 同款）。
- **原文件名会进 URL**：公开件不做 uuid 换名，上传时叫什么，`/media/uploads/<年>/<月>/…` 里就是什么
  ——名字带人名、组名就会原样出现在地址栏与备份里。要藏文件名就得落受保护件。
- **校验只在 `save()` 上**：`QuerySet.update()`、`bulk_create` 这类不调用 `save()` 的写法一律绕过。
- **`limit_choices_to` 只管后台表单的可选项**：`HomeSlide.clean()` 在图片类型上又查一次，
  `Award.certificates` 没有这一道，ORM 能塞进视频。
- **删引用的后果分两种**：挂 `Showcase.photo` / `HomeSlide.image` 的会被 `PROTECT` 挡下；
  挂 M2M 的不会——中间行跟着删，证书静默消失。
- **本期不做视频转码／多码率**：校验只认扩展名与文件头魔数，**编解码格式本身不校验**——
  HEVC 封进 MP4 一样能过，浏览器放不放得出来平台不管。所以要传 MP4（H.264）或 WebM 是**约定**，
  不是强制。播放由 Nginx 静态直出并支持 Range 拖动。
- **`file_size` 在每次 `save()` 时从盘上重取**：盘上文件被手工删掉时这一步会直接抛 `FileNotFoundError`，
  保存失败而不是留下一个旧数字。
