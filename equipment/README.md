# equipment 模块

> 设备台账与借用登记：`Equipment` 与 `EquipmentBorrow` 两张表，前台两个命名空间
> 加后台台账维护与批量代归还。
> **不做审批**（登记即生效）、**不做预约／续借／逾期**（`planned_return_date` 只是记录）、
> **不做数量维度**——一条借用记录恒对应一件设备，没有部分归还。
> 本模块**没有 `permissions.py`**：「谁能借」问 `projects.permissions.can_use_equipment`，
> 「谁算管理员」问 `core.permissions.is_admin`。

**什么时候看**：改库存口径、动借用／归还规则、碰后台设备表单或代归还动作，
或回答「谁能借、归还回补多少」时。

---

## 1. 明确不做什么

| 不做 | 落在哪 |
|---|---|
| 「谁能借」「谁算管理员」 | `projects.permissions.can_use_equipment`、`core.permissions.is_admin`。本模块只调用，不重写 |
| 审批流 | 有意不做：登记即生效 |
| 替成员登记借用 | 没有任何入口：`EquipmentBorrowAdmin.has_add_permission` 恒为 `False`，前台借用人恒为 `request.user`。**只有归还可以代做** |
| 逾期 | 不做：`planned_return_date` 只入库展示，不改状态、不提醒、不挡归还 |
| 删除借用记录 | `EquipmentBorrowAdmin.has_delete_permission` 恒为 `False`——删掉一条在借记录会让库存凭空少一件 |
| 「借用的记录谁能看」 | **不是判定函数**（本 app 没有 `permissions.py`，也没有 `can_view_borrow`），而是在查询里收窄：`views.borrow_list` 按 `borrower` 过滤，`views.borrow_return` 在 `get_object_or_404` 里带 `borrower` |

## 2. 必须成立的断言

- **库存不变式 `available_count <= total_count`**：数据库有 `CheckConstraint` 兜住，
  模型 `Equipment.clean()` 再算一遍并加了更强的一条——行已存在时还要求
  `available_count + 在借数 <= total_count`，挡的是「把总量改小到低于已借出数量」。**后一条只在模型层**。
- **`available_count` 是「现在还能借几件」的唯一真相源，且是增量维护的**（借 −1、还 +1），
  **不是**由 `total_count − 在借数` 推出来的。所以 `total_count - available_count` 只在没人动过台账时
  才等于在借数量；要数在借，数 `EquipmentBorrow.objects.filter(status=BORROWED)`。
- **借与还的增量只能走 `services.py` 的两个函数**：直接改字段（尤其绕过 `save()` 的
  `QuerySet.update()`）会让库存与借用记录脱节。**例外**：后台表单能直改 `available_count`
  （那是给人修台账用的），所以「这一列只被服务层写」这句话不成立——`return_borrow` 的回补守卫正是为它准备的。
- **回补是有条件的**：`available_count < total_count` 才 +1，否则只记一条
  `equipment.return.inventory_invariant` 警告、库存不动。宁可跳过回补，也不让归还把
  `available_count` 顶过 `total_count` 而撞上数据库约束。
- **`is_active=False` 是下架，不是删除**：列表隐藏、借用页 404、`create_borrow` 也带过滤（纵深防御）；
  但**已借出的记录仍可归还**，`return_borrow` 不看 `is_active`。
- **`EquipmentBorrow` 的状态与日期必须自洽**：CHECK 约束「`borrowed` 不带 `actual_return_date`、
  `returned` 必须带」，模型 `clean()` 与表单说的是同一件事。
- **锁的粒度比看上去大**：取借用记录那句是 `select_for_update().select_related("equipment")`，
  不带 `of=` 的 `FOR UPDATE` 在 PostgreSQL 下**连设备行一起锁**——副作用是「同一台设备的不同借用记录
  并发归还时会互相等」，以及它与只锁设备行的 `create_borrow` 共享同一把设备锁（不成环，但别把它当纯粹的
  借用行锁看）。重复归还之所以不重复回补，靠的是状态复查在**行锁内、且在改任何东西之前**。

## 3. 已知限制 / 当前不支持

- **服务层不保证设备还在**：视图先 `get_object_or_404` 取一次、服务再按 pk 取一次，两次之间设备被下架或
  删除时，`create_borrow` 抛的是 `Equipment.DoesNotExist` 而不是 `EquipmentUnavailable`，视图不捕 → 500。
  `return_borrow` 的 `EquipmentBorrow.DoesNotExist` 同理。
- **归还是「当天」**：`actual_return_date` 恒取 `timezone.localdate()`，没有指定日期的入口，
  也不能补登过去的归还。
- **「不早于今天」只在表单里**：模型只校验 `planned_return_date >= borrow_date`。
  新增非表单写入口要自己带这道校验。
- **没有逾期概念**：过了 `planned_return_date` 不改状态、不提醒、也不挡归还。
- **管理员不能替成员登记借用**：后台 `has_add_permission` 为 `False`，前台借用人恒为 `request.user`；
  只有归还可以代做。
- **后台批量归还可能作用于「全部筛选结果」**：Django admin 自带跨页全选——勾一条之后会出现
  「全选 N 项」，点它提交的 `select_across=1` 会让动作拿到**整个筛选结果集**。所以「我只还了这一页」
  是错觉：动这个动作前先看清筛选条件与那个链接的提示。
- **`available_count` 会被人工改**：后台表单能把可借数调大（只要求 `可借 + 在借 <= 总量`），此后
  「总量 − 可借数」就不等于在借数了。
- **`Equipment.save()` 无条件跑 `full_clean()`**：`QuerySet.update()` 或批处理会绕过模型层那条
  「总量 ≥ 可借 + 在借」的校验（数据库那条 `available_count <= total_count` 仍在）。改库存请走 `services`。
- **`EquipmentBorrowForm.__init__` 收下 `equipment` 但当前没用到**：是预留位，别以为表单校验依赖它。
- **被移出组的人仍能归还既有借用**：`equipment_borrows:*` 只查登录，别「顺手补上」
  `can_use_equipment`——否则权限会把人锁死。

## 4. 由来

- **为什么库存不变式落在数据库**：`available_count <= total_count` 由 CHECK 约束兜住，而不是只靠服务层
  ——库存错了会让「还能不能借」这个判断整体失真。
- **为什么重复归还不重复回补**：归还流程在**行锁内**先复查状态、再改任何东西；回补前的
  `available_count < total_count` 守卫是给管理员手工改过台账的情形准备的。
