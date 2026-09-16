"""Acceptance tests for the review app, one module per feature.

The review domain is two stages (初审 and 评审) plus the machinery around them
(请假、改派、提醒、超级评审、后台). Each module here covers one of those, so a
change to the 初审 gate has an obvious place to look and an obvious place to add
an assertion. 共用件只有两个：

* :mod:`reviews.tests.factories` —— 造对象（用户、项目组、上传文件）；
* :mod:`reviews.tests.base` —— ``ReviewTestCase``：临时 MEDIA_ROOT 与「把一轮
  送审推过两道关」的动作。

夹具（谁在这个组的里、谁是评审人）刻意留在各个测试类自己的 ``setUp`` 里：
抽签结果取决于候选人数，夹具一旦由基类统一发放，某个类的断言就会因为多了
一个候选账号而变得时灵时不灵。
"""
