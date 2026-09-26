# 6.6 equipment

> 设备台账与借用：库存事务、行锁、归还回补。

**什么时候看**：改库存口径或借用门槛。

---

```
Equipment
  - name           设备名称
  - category       分类（文本）
  - total_count    总量
  - available_count 当前可借数量（必须 ≤ 总量，且不得小于已借出数量约束）
  - description    说明
  - is_active      是否上架
  - created_at
  - updated_at

EquipmentBorrow
  - equipment      FK(Equipment)
  - borrower       FK(User)  借用人
  - borrow_date    借用日期
  - planned_return_date  计划归还日期
  - actual_return_date   实际归还日期（已归还时必填）
  - status         borrowed（已借用）| returned（已归还）
  - remark         备注
  - created_at
  - updated_at
```

- 借用入口仅对**项目组成员**开放（未加入任何项目组的成员看不到入口、访问返回 403）。
- 无审批：成员直接登记借用；服务在数据库事务内锁定设备记录、创建借用记录并扣减 `available_count`。
- 成员仅可查看和归还自己的借用记录；管理员可查看全部记录并代归还。
- 归还不受项目组归属限制：成员被移出项目组后仍可归还既有设备，避免权限锁死。
- 归还操作在事务内锁定借用记录和设备，状态改为 `returned` 后才回补库存；重复归还不会重复回补。
