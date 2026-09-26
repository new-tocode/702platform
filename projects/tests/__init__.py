"""项目组的验收测试，一个模块一个主题。

原先三类挤在 667 行的单文件里，其中 ``ProjectGroupAcceptanceTests`` 一个类 407 行
23 个用例，混着「浏览」「入组」「转让」「管理」四件事，所以按这四件拆开：

* ``test_browsing`` —— 谁看得到哪个组、详情页显示什么
* ``test_membership`` —— 申请入组与成员变更
* ``test_contact_transfer`` —— 联系人转让
* ``test_group_management`` —— 管理页与组信息维护

另两个主题各自成模块：申请建组（``test_group_create_requests``）与成员名册
（``test_member_roster``）。

共用件只有 ``base.ProjectViewTestCase``（四种身份各一个账号 + 两个项目组）。夹具
可以共用：项目组没有抽签，夹具不决定任何随机结果。
"""
