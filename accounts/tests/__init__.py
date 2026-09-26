"""账号相关的验收测试，一个模块一个主题。

账号这一块有三件事混在一起，拆开之后各自有明确的去处：

* **账号本身**——建号、发密码、首次登录强制改密（``test_models_and_auth``、
  ``test_admin_provisioning``、``test_login_lockout``）；
* **个人资料**——资料页的字段排布与校验、头像、图册（``test_profile_pages``、
  ``test_avatar_and_gallery``）；
* **身份**——页面上怎么显示、后台怎么授予与查看（``test_identity_panels``、
  ``test_role_roster``）。

共用件只有 :mod:`accounts.tests.factories`（造账号与上传件，外加两个临时媒体
根）。夹具本身留在各个类自己的 ``setUp`` 里，与 ``reviews/tests`` 同一条理由：
断言依赖「这个人是什么身份」，由基类统一发放会让断言随夹具变化而时灵时不灵。
"""
