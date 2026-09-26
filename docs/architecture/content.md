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
  - level          获奖级别（国家级/省级/校级等，自由文本）
  - winners        获奖人/团队描述
  - created_at
  - attachments    M2M(MediaFile, blank=True)  奖状/现场图/视频

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

---

### 6.9 media（媒体库）

```
MediaFile（统一媒体库，供各内容模型通过 M2M/FK 引用）
  - file          FileField(upload_to='uploads/%Y/%m/')
  - kind          image | video
  - caption       说明文字（可选）
  - uploader      FK(User)
  - file_size     文件大小（字节）
  - created_at
```
