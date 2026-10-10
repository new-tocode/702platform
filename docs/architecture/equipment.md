# equipment

> 设备台账与借用。**模块说明（职责、接口、不变量、失败模式、测试与限制）在
> [`equipment/README.md`](../../equipment/README.md)**——表结构、规则与坑都搬去了那里。
>
> 这一篇只留**跨模块口径与由来**。

**什么时候看**：改库存口径、动借用门槛，或弄清「为什么归还比借用宽」。

---

## 跨模块口径

- **借用的门槛在项目组侧**：`projects.permissions.can_use_equipment`（staff 或任一项目组成员）；本模块**没有 `permissions.py`**，只在自己那几张视图里调它。
- **归还刻意比借用宽**：归还只要求登录 + 是本人的记录（管理员可代还），**不查项目组归属**——被移出组的人仍要能还掉手里的设备，否则权限就把人锁死了。`is_active=False` 的设备同理必须还能还。
- **可见范围不是判定函数，而是在查询里收窄**：本人只看自己的借用记录，管理员看全部——没有对应的 `permissions` 函数（[permissions.md](permissions.md) 已按此更正）。
- **后台代还的门槛是模型权限**：`permissions=["change_equipmentborrow"]`，不是 `is_admin`——那个 admin 类的 `has_change_permission` 被覆写成 `is_admin`，动作声明必须跟着它，否则只挂 `view_equipmentborrow` 的只读账号就能改别人的借还、把库存加回去。

## 由来

- **为什么没有审批、预约、续借、逾期**：社团规模下这几件事没有争议性，加状态机与待办的收益不抵成本（见 [overview.md](overview.md) §1.1）。台账只回答「现在谁手上有什么」。
- **为什么库存不变式落在数据库**：`available_count <= total_count` 由 CHECK 约束 `equipment_available_lte_total` 兜住，而不是只靠服务层——库存错了会让「还能不能借」这个判断整体失真。
- **为什么重复归还不重复回补**：归还流程在**行锁内**先复查状态、再改任何东西；这一条是「已归还的借用点两次不会把库存加两遍」的唯一依据。回补前的 `available_count < total_count` 守卫是给管理员手工改过台账的情形准备的。
