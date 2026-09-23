# 个人信息页改造 · 任务清单

分支：`feature/profile-avatar-gallery`（自 `refactor/layers-and-roles` 切出）

目标：把「个人信息」页从一张单列表单，改成「左侧资料表单 + 右侧头像与身份 + 下方个人图册」。
每个阶段自成一个提交，阶段内保持 `check`／`makemigrations --check`／`test` 全绿。

## 阶段 1 · 资料表单改版

- [ ] `Profile.bio`（个人简介）字段 + 迁移
- [ ] `ProfileForm` 字段顺序与排布声明（姓名｜学号、学院｜专业两列；手机号收窄并前移到特长之前；特长保持单行）
- [ ] `profile.html` 左列按表单声明的排布渲染，个人简介置于最下方
- [ ] `app.css` 新增两列栅格与窄栏类，窄屏回落单列
- [ ] 测试 + `.po` 补译

## 阶段 2 · 头像

- [ ] `Profile.avatar`（`ImageField`）+ 迁移
- [ ] 图片校验下沉到 `core/uploads.py`，`media` 与原校验复用（头像 ≤2 MB）
- [ ] `accounts.services.set_avatar` / `clear_avatar`：换头像删旧文件、删头像删文件，均留审计
- [ ] 上传／更换／删除三个入口（视图 + 路由 + 模板 + 表单）
- [ ] 圆形展示（CSS 裁切，非正方形图不变形）
- [ ] 测试 + `.po` 补译

## 阶段 3 · 当前身份（只读）

- [ ] `projects.selectors`：按人取项目组（联系人／成员，带组名）
- [ ] `accounts.selectors.member_identities`：按身份目录顺序收敛出该用户持有的身份
- [ ] 头像区下方的只读面板：全局身份成标签、对象身份带组名，没有的不出现
- [ ] 测试 + `.po` 补译

## 阶段 4 · 个人图册

- [ ] `GalleryImage`（图像、排布、顺序、大小）+ 迁移
- [ ] 每张 ≤5 MB（字段校验器）、每人合计 ≤100 MB（服务层行锁 + 配额）
- [ ] `accounts.services`：上传、上移／下移、改排布、删除（均留审计，删图删文件）
- [ ] 页面整幅宽度分区：上传、逐张的排序／排布／删除控件、用量显示
- [ ] `app.css` 图册栅格（普通／大图占两格／整行），窄屏回落
- [ ] 测试 + `.po` 补译

## 阶段 5 · 文档与收尾

- [ ] `README.md`、`docs/architecture.md`、`docs/development.md` 同步
- [ ] 全量 `manage.py test` + `check` + `makemigrations --check`
- [ ] 本地起服务、真实浏览器点一遍（`run-local`）
