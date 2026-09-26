# 6.1 accounts

> 账号与个人资料：自定义 User、Profile、个人图册，以及强制改密与身份目录。

**什么时候看**：改账号字段、动个人资料页、碰资格字段或身份名册。

---

```
User（继承 AbstractUser，项目自定义，经 AUTH_USER_MODEL 生效）
  - 复用默认字段：username / password / is_staff / is_active / groups / date_joined
  - must_change_password   bool  首次登录强制改密标记（默认 True）
  - is_reviewer           bool  评审资格（默认 False）
  - is_preliminary_reviewer bool 初审资格（默认 False）
  - is_super_reviewer     bool  超级评审资格（默认 False）
  - 权限口径以用户上的布尔标志表达（is_staff／is_reviewer／is_preliminary_reviewer／is_super_reviewer），不新增 role 字段；
    Django auth.Group 只用于内部通知的投递范围

Profile（User 一对一扩展）
  - user          OneToOne(User)
  - full_name     姓名（单一字段）
  - avatar        头像（图片，≤2 MB；圆形只是展示层的裁切，原图不动）
  - student_id    学号（唯一）
  - college       学院
  - major         专业
  - specialty     特长（自由文本，可写多项）
  - phone         手机号
  - contact       其他联系方式（可选）
  - bio           个人简介（≤1000 字）
  - created_at / updated_at

GalleryImage（个人图册里的一张图，随 Profile 级联删除）
  - profile       FK(Profile)
  - image         图片（≤5 MB；一个人的全部图像合计 ≤100 MB）
  - layout        normal（普通）| wide（大图，占两格）| full（整行铺满）
  - sort_order    用户逐张调出来的顺序，页面按 (sort_order, id) 排
  - file_size     文件大小（字节）
  - created_at
```

- 管理员创建账号时设置初始密码（默认建议设为学号/工号，并在文档中提示安全改密）。
- 成员可修改 Profile 中的单一 `full_name` 姓名字段及其他个人资料、头像、个人图册与本人密码；管理员可在 Admin 中重置任意用户密码（Django 内置功能）。
- 自定义 User 仍继承 Django `AbstractUser` 的底层 `first_name` / `last_name` 数据列，但它们不再出现在任何用户界面，也不作为业务姓名使用；历史数据会在迁移中合并到 `Profile.full_name`。
- **个人信息页**（`/member/profile/`）左栏是资料表单、右栏是头像与只读的「当前身份」、下方整幅宽度是个人图册。表单的分行与宽窄由 `ProfileForm.field_rows`／`narrow_fields` 声明、`rows()` 装配，模板只按行逐格渲染——排布是这张表单自己的事，散进模板就得在那边按字段名做判断。
- **上传件的写入口只有两个**：`accounts.services.set_avatar`／`clear_avatar` 与 `accounts.services.add_gallery_image`／`move_gallery_image`／`set_gallery_layout`／`delete_gallery_image`。换头像、删图都连磁盘上的文件一起处理（文件系统不在事务里，删除一律放在提交之后：出错顶多多留一个旧文件，不会出现「库里还指着、磁盘上没了」）。
- **图册的 100 MB 是合计上限**，求和前先 `select_for_update` 锁住账号那一行：同一个人开两个标签页同时上传时，不加锁会双双读到还没涨上去的用量。单张 5 MB 与头像的 2 MB 走同一套图片校验（`core.uploads.validate_image_upload`），差别只是上限。
- **「当前身份」只读**：全局身份问各应用 `permissions` 的判定，项目组联系人／成员带组名，来自 `projects.selectors`——后台那六张名册的排法在这里同样成立，没持有的身份不出现。
- **强制改密流程**：首次登录后若 `must_change_password=True`，重定向到改密页；改密成功后置 `False`，之后才能访问其他成员功能。
