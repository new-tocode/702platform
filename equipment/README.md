# equipment 模块

> 设备台账与借用登记：`Equipment` 与 `EquipmentBorrow` 两张表，前台两个命名空间
> （`equipment:list` / `equipment:borrow` 与 `equipment_borrows:list` / `:return`）加后台台账维护与批量代归还。
> **不做审批**（登记即生效，没有待审状态）、**不做预约／续借／逾期**（`planned_return_date` 只是记录）、
> **不做数量维度**——一条借用记录恒对应一件设备，没有部分归还。
> 本模块**没有 `permissions.py`**：「谁能借」问 `projects.permissions.can_use_equipment`，
> 「谁算管理员」问 `core.permissions.is_admin`。
> 依赖它的只有两处：`core.registry` 的两个入口卡片与 `core.stats.platform_overview` 的在借计数。

**什么时候看**：改库存口径、动借用／归还规则、碰后台设备表单或代归还动作，
或回答「谁能借、归还回补多少」时。

---

## 1. 职责与边界

| 面 | 落点 |
|---|---|
| 两张表、两条 `CheckConstraint`、两个 `clean()` | `models.py` |
| 写操作：`create_borrow`、`return_borrow`（事务、行锁、领域异常） | `services.py` |
| 前台表单 `EquipmentBorrowForm`、后台表单 `EquipmentAdminForm` | `forms.py` |
| 四个页面入口与两个命名空间的路由 | `views.py`、`urls.py`、`borrow_urls.py`（挂载于 `config/urls.py` 的 `member/equipment/` 与 `member/borrows/`） |
| 台账维护、借用记录只读页、动作 `mark_returned` | `admin.py` |
| 成员中心入口卡片（key `equipment.borrow` / `equipment.records`） | `apps.py` |
| 模板与顶栏归属（`MEMBER_NAMESPACES` 含两个命名空间） | `templates/equipment/`、`core/context_processors.py` |

**明确不做**：

| 不做 | 落在哪 |
|---|---|
| 「谁能借」「谁算管理员」 | `projects.permissions.can_use_equipment`（= `is_admin` 或 `is_project_member`）、`core.permissions.is_admin`。本模块只调用，不重写 |
| 审批流 | 有意不做：登记即生效（`docs/architecture/overview.md` 的「刻意不做」表） |
| 替成员登记借用 | 没有任何入口：`EquipmentBorrowAdmin.has_add_permission` 恒为 `False`，前台借用人恒为 `request.user`。**只有归还可以代做** |
| 逾期 | 不做：`planned_return_date` 只入库展示，不改状态、不提醒、不挡归还 |
| 删除借用记录 | `EquipmentBorrowAdmin.has_delete_permission` 恒为 `False`——删掉一条在借记录会让库存凭空少一件 |

**没有的模块**：没有 `permissions.py`、`selectors.py`、`panels.py`。
借用记录的可见范围**不是判定函数**（本 app 没有 `permissions.py`，也没有 `can_view_borrow` 这个函数——[permissions.md](../docs/architecture/permissions.md) 曾误列它，已更正），而是在查询里收窄：
`views.borrow_list` 按 `borrower` 过滤，`views.borrow_return` 在 `get_object_or_404` 里带 `borrower`。
上游是 `core`（`permissions`／`audit`／`registry`／`stats`）与 `projects.permissions`；
`projects` 侧只在文档里把本模块列为下游，代码上不反向依赖。

---

## 2. 关键接口与失败模式

| 入口 | 语义 | 前置条件 | 失败模式 |
|---|---|---|---|
| `views.equipment_list` | GET 设备列表，只列 `is_active=True` | 登录 + `can_use_equipment` | 匿名 → 302 登录页；非组员 → **403**；POST → 405 |
| `views.equipment_borrow` | GET 表单／POST 登记借用 | 同上；设备存在且上架 | 不存在或 `is_active=False` → **404**；无库存 → 200 + 表单顶部错误；日期非法 → 200 + 字段错误 |
| `views.borrow_list` | GET 借用记录：管理员见全部，成员见本人 | **仅登录**，刻意不查项目组 | 匿名 → 302；POST → 405 |
| `views.borrow_return` | POST 归还（`@require_POST`） | 仅登录；记录归属本人或调用者是管理员 | GET → 405；别人的记录 → **404**（不是 403）；已归还 → 302 + warning |
| `services.create_borrow(*, equipment_id, borrower, planned_return_date, remark, actor)` | 锁设备行 → 建记录 → 扣 1 | 设备存在且 `is_active=True` | 无库存 → `EquipmentUnavailable`；设备不存在／已下架 → `Equipment.DoesNotExist`（**视图只捕 `EquipmentUnavailable`**） |
| `services.return_borrow(*, borrow_id, actor)` | 锁记录行 → 置 `returned` → 有条件地回补 1 | 调用方已确认归属 | 非本人且非管理员 → `ReturnNotAllowed`；已归还 → `BorrowAlreadyReturned` |
| `admin.EquipmentAdmin` | 台账增／改／删 | 管理员 | 删除有借用记录的设备（含已归还）→ 被 `PROTECT` 挡下（`ProtectedError`） |
| `admin.EquipmentBorrowAdmin.mark_returned` | 选中若干记录批量代归还 | **`equipment.change_equipmentborrow` 模型权限**，不是 `is_admin` | 只读 staff：动作不出现，直接 POST 也无效；已归还的计入 warning 计数 |

`mark_returned` 的门槛刻意绕开 `permissions=["change"]`：本类的 `has_change_permission` 被覆写成 `is_admin`
（即 `is_staff`），任何工作人员都通过，那正是要挡住的只读观察者。改这条权限声明前先读 `admin.py` 里那段注释。

---

## 3. 状态与不变量

| 表 | 字段要点 |
|---|---|
| `Equipment` | `total_count`（默认 1）、`available_count`（默认 1）、`is_active`（默认 `True`）、`category`（自由文本）、`description` ≤ 2000 |
| `EquipmentBorrow` | `status` ∈ `borrowed` / `returned`、`borrow_date`（默认当天）、`planned_return_date`（必填）、`actual_return_date`（可空）、`remark` ≤ 1000 |

**库存不变式：`available_count <= total_count`。**这是唯一一条由数据库保证的库存规则
（`CheckConstraint` `equipment_available_lte_total`），模型 `Equipment.clean()` 再算一遍并加了更强的一条。

**`available_count` 是「现在还能借几件」的唯一真相源，且是增量维护的**（借 −1、还 +1），
**不是**由 `total_count − 在借数` 推出来的。所以 `total_count - available_count` 只在没人动过台账时
才等于在借数量；要数在借，数 `EquipmentBorrow.objects.filter(status=BORROWED)`——`core.stats` 就是这么做的。

**必须成立的断言**

- **模型层的第二条库存规则**：`Equipment.clean()` 在行已存在时还要求
  `available_count + 在借数 <= total_count`，挡的是「把总量改小到低于已借出数量」。
  这条只在模型层（`save()` 无条件跑 `full_clean()`），**数据库没有它**。
- **`EquipmentBorrow` 的状态与日期必须自洽**：`borrow_status_matches_return_date` 约束
  「`borrowed` 不带 `actual_return_date`、`returned` 必须带」。模型 `clean()` 与表单说的是同一件事。
- **一条记录 = 一件设备**：`create_borrow` 恒扣 1，没有数量字段；别把它当「一次借多件」的模型。
- **`is_active=False` 是下架，不是删除**：列表隐藏、借用页 404、`create_borrow` 也带 `is_active=True` 过滤
  （纵深防御）；但**已借出的记录仍可归还**，`return_borrow` 不看 `is_active`。
- **外键一律 `PROTECT`**：`EquipmentBorrow.equipment` / `.borrower` 都是，所以有借用记录的设备删不掉
  （哪怕全部已归还），有借用记录的账号也删不掉。退役设备走 `is_active=False`。
- **借与还的增量只能走 `services.py` 的两个函数**：直接改字段（尤其绕过 `save()` 的
  `QuerySet.update()`）会让库存与借用记录脱节，新增写入口要接在这两个函数上。
  **例外**：后台表单能直改 `available_count`（那是给人修台账用的，见 §6），
  所以「这一列只被服务层写」这句话不成立——`return_borrow` 的回补守卫正是为它准备的。
- **回补是有条件的**（见 §4）。
- **审计 action 一旦发布不再改**，清单见 §5。

---

## 4. 数据流与时序

**借用**（`POST /member/equipment/<pk>/borrow/`）：

1. `@login_required` → 匿名 302；`_require_equipment_access` → `can_use_equipment` 为假时记
   `equipment.permission.denied` 并 403。
2. `get_object_or_404(Equipment, pk=pk, is_active=True)` → 不存在或已下架 404。
3. `EquipmentBorrowForm` 校验 `planned_return_date`（不早于今天）。
4. `create_borrow(...)`，`@transaction.atomic` 内：`select_for_update()` 锁 `Equipment` 行 →
   `available_count < 1` 则抛 `EquipmentUnavailable`（**先记日志、后抛，未建任何记录**）→
   建 `EquipmentBorrow`（`borrow_date=today`、`status=borrowed`）→ `available_count -= 1` 并保存。
5. 成功：视图写审计 `equipment.borrow` → `messages.success` → 302 回 `equipment_borrows:list`。
   `EquipmentUnavailable` 则 `form.add_error(None, ...)` 后原页 200，**不写审计**。

**锁的是 `Equipment` 行**，所以两个请求同时争最后一件时，后到的那个在锁释放后读到 `available_count == 0`，
得到 `EquipmentUnavailable`。这是 `ConcurrentEquipmentBorrowTests` 钉的场景。

**归还**（`POST /member/borrows/<pk>/return/`）：

1. `@login_required` + `@require_POST` → GET 405。
2. `get_object_or_404`：非管理员额外限定 `borrower=request.user`，所以别人的记录是 404。
3. `return_borrow(...)`，`@transaction.atomic` 内，顺序是**先锁记录、再复查、最后才动库存**：
   取借用记录时 `select_for_update()` 上锁 → 归属复查（`ReturnNotAllowed` 兜底）→
   **已 `returned` 则抛 `BorrowAlreadyReturned`** → 锁 `Equipment` 行 → 写 `status=returned` 与
   `actual_return_date=today` → 回补。
4. 回补**有前提**：`available_count < total_count` 才 +1；否则只记一条
   `equipment.return.inventory_invariant` 警告、库存不动。这条守卫是为「管理员手工改过台账」准备的——
   宁可跳过回补，也不让归还把 `available_count` 顶过 `total_count` 而撞上数据库约束。
5. 成功：审计 `equipment.return` → `messages.success` → 302；`BorrowAlreadyReturned` → `messages.warning` + 302。

**重复归还为什么不重复回补**：状态复查在**行锁内、且在改任何东西之前**；第二次调用读到的是已 `returned`
的那一行，直接抛异常，`available_count` 一个字节都不动。串行点是那行借用记录上的锁。
**注意实际锁的范围**：取借用记录那句是 `select_for_update().select_related("equipment")`，
不带 `of=` 的 `FOR UPDATE` 在 PostgreSQL 下**连设备行一起锁**——副作用是「同一台设备的不同借用记录
并发归还时会互相等」，以及它与只锁设备行的 `create_borrow` 共享同一把设备锁（不成环，但别把它当纯粹的借用行锁看）。

**后台代归还**（`mark_returned`）：对选中的每条 pk **逐条**调同一个 `return_borrow`（每条各自一个事务），
成功写审计 `equipment.return.admin`，已归还的只累加计数，最后分别报 success / warning。

---

## 5. 错误处理与诊断

**领域异常只有三个**，都在 `services.py`。

| 异常 | 谁抛 | 表现 |
|---|---|---|
| `EquipmentUnavailable` | `create_borrow` | 视图翻成表单顶部错误「该设备当前没有可借数量。」，页面 200 |
| `BorrowAlreadyReturned` | `return_borrow` | 前台翻成 warning + 302；后台计入 warning 计数 |
| `ReturnNotAllowed` | `return_borrow` | **兜底断言**，两条调用路径都先做了归属过滤，正常走不到；真被触发说明有新调用方绕过了权限检查。领域层不抛 HTTP 异常，所以它不叫 `PermissionDenied` |

| 情形 | 表现 |
|---|---|
| 匿名访问任一前台入口 | 302 登录页 |
| 非项目组成员访问设备列表／借用页 | **403**（`core.permissions.require`，event `equipment.permission.denied`，**由 `core.permissions` 这个 logger 记录**，不在 `equipment.*` 下） |
| 未进组／已被移出组的成员访问借用记录页、归还 | **不拦**：`equipment_borrows:*` 只查登录。被移出组的人仍能归还既有借用，别「顺手补上」 `can_use_equipment` |
| 设备不存在或 `is_active=False` | 404，管理员也一样 |
| 非管理员打开别人的归还入口 | **404**（查询里带 `borrower`，不是 403） |
| 库存为 0 时提交借用 | 200 + 表单顶部错误，不建记录、不扣库存 |
| `planned_return_date` 早于今天 | 200 + 字段错误「计划归还日期不能早于今天。」 |
| 重复归还 | 302 回记录页 + warning，库存不动 |
| GET 打归还入口；POST 打列表入口 | 405 |

**审计 action**（发布后不再改）：

| action | 写入点 | target / detail |
|---|---|---|
| `equipment.borrow` | `views.equipment_borrow` | 新建的借用记录；`equipment_id` |
| `equipment.return` | `views.borrow_return` | 借用记录；`equipment_id` |
| `equipment.return.admin` | `admin.mark_returned` | 借用记录；`equipment_id`，逐条写 |
| `equipment.create` / `equipment.update` | `EquipmentAdmin.save_model` | 设备；`total_count`、`available_count`、`is_active` |

**后台删除设备不写审计**（`delete_model` 未覆盖，走 Django 默认动作）。库存不足的借用、表单校验失败、
已归还的重复归还——这三条路径都只留日志，不写审计。

**日志**：三个 logger `equipment.views` / `equipment.services` / `equipment.admin`
（`config/settings.py` 的 LOGGING 给 `equipment` 前缀单开了一级，`propagate=False`）。
视图层记的都带 `request_id`（归还视图本身不记日志）；**服务层不带**——那里没有 request 对象，别在服务日志里找它。

| 锚点 | 含义 |
|---|---|
| `equipment.list.view count=` / `equipment.borrow_list.view scope=all\|own count=` | 列表访问 |
| `equipment.borrow.success ... available_after=` | 借用成功（服务层） |
| `equipment.borrow.failure ... reason=out_of_stock` / `... errors=` | 借用失败：库存不足（服务层记一条、视图再记一条）/ 表单校验失败 |
| `equipment.return.success ... available_after=` | 归还成功 |
| `equipment.return.denied ... reason=not_owner` | 归属兜底被触发（**出现即意味着有调用方绕过了权限**） |
| `equipment.return.failure ... reason=already_returned` | 重复归还 |
| `equipment.return.inventory_invariant available= total=` | **库存被人工改过，这次归还跳过了回补**——排查「还了但可借数没涨」先看这条 |
| `admin.equipment.save operator= ... created=` | 后台台账增改 |

审计写入本身另由 `core.audit` 记一条 `audit.record`。

---

## 6. 测试要点与已知限制

| 类 | 钉住什么 |
|---|---|
| `EquipmentAcceptanceTests` | 只列上架设备；无组员看不到入口且 403；被移出组后仍能归还；匿名 302；借用扣减 + 建记录 + 审计；库存 0 拒绝；下架设备 404；计划归还日期不能早于今天；成员只见本人记录；归还回补并写实际归还日期；不能还别人的（404）；管理员见全部并代还；重复归还不再回补；总量不能低于可借 + 在借；借用记录状态与日期必须匹配；后台只读观察者拿不到 `mark_returned`（看得到与提交得动同源）；非 staff 进不去后台 |
| `ConcurrentEquipmentBorrowTests` | `create_borrow` 发出的 SQL 必须含 `FOR UPDATE`；两个线程争最后一件时恰好一个成功、一个 `EquipmentUnavailable`，可借数落到 0。用 `TransactionTestCase`，依赖 PostgreSQL 的行锁 |

跨模块另有两处钉着本模块：`core/tests/test_registry_and_audit.py`（入口 key `equipment.borrow` /
`equipment.records` 的注册与可见性——前者按 `can_use_equipment` 隐藏，后者所有登录成员可见）、
`core/tests/test_upload_validation.py`（`EquipmentBorrow.remark` 上限 1000，模型与表单一致）。

### 已知限制 / 当前不支持

- **服务层不保证设备还在**：视图先 `get_object_or_404` 取一次、服务再按 pk 取一次，两次之间设备被下架或删除时，
  `create_borrow` 抛的是 `Equipment.DoesNotExist` 而不是 `EquipmentUnavailable`，视图不捕 → 500。
  `return_borrow` 的 `EquipmentBorrow.DoesNotExist` 同理。
- **归还是「当天」**：`actual_return_date` 恒取 `timezone.localdate()`，没有指定日期的入口，也不能补登过去的归还。
- **「不早于今天」只在表单里**：模型只校验 `planned_return_date >= borrow_date`。新增非表单写入口要自己带这道校验。
- **没有逾期概念**：过了 `planned_return_date` 不改状态、不提醒、也不挡归还。
- **管理员不能替成员登记借用**：后台 `has_add_permission` 为 `False`，前台借用人恒为 `request.user`；只有归还可以代做。
- **后台批量归还可能作用于「全部筛选结果」**：Django admin 自带跨页全选——勾一条之后会出现「全选 N 项」，点它提交的 `select_across=1` 会让动作拿到**整个筛选结果集**（`ModelAdmin` 里 `if not select_across` 才会按 pk 过滤）。所以「我只还了这一页」是错觉：动这个动作前先看清筛选条件与那个链接的提示。
- **`available_count` 会被人工改**：后台表单能把可借数调大（只要求 `可借 + 在借 <= 总量`），此后
  「总量 − 可借数」就不等于在借数了。`return_borrow` 的 `available_count < total_count` 守卫因此宁可跳过回补；
  代价是那次归还不会增加可借数，只留一条 `equipment.return.inventory_invariant`（见 §4）。
- **`Equipment.save()` 无条件跑 `full_clean()`**：`QuerySet.update()` 或批处理会绕过模型层那条
  「总量 ≥ 可借 + 在借」的校验（数据库那条 `available_count <= total_count` 仍在）。改库存请走 `services`。
- **`EquipmentBorrowForm.__init__` 收下 `equipment` 但当前没用到**（`self.equipment` 只存不读）：
  是预留位，别以为表单校验依赖它。
