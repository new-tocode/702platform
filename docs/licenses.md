# 依赖与许可清单

> 用了什么、什么许可、分发时有什么义务。**这张表跟着 `requirements*.txt` 走**——依赖一变就更新它。

**什么时候看**：加依赖之前（先看义务）、交付或公开之前、有人问「这个能不能拿去用」。

---

## 1. 本项目自身

**MIT**，原文见仓库根的 [`LICENSE`](../LICENSE)。版权行写的是「702platform contributors」——要换成具体的人名或组织名，改那一行即可。

## 2. 运行时依赖

版本以 `requirements.txt` / `requirements-prod.txt` 的**锁文件**为准（`pip-compile --generate-hashes` 生成，安装一律带 `--require-hashes`）。许可证原文收在 [`THIRD_PARTY_LICENSES/`](../THIRD_PARTY_LICENSES/)。

| 包 | 许可证 | 分发义务 |
|---|---|---|
| Django | BSD-3-Clause | 保留版权与许可声明 |
| django-axes | MIT | 保留声明 |
| bleach | Apache-2.0 | 保留声明与 NOTICE（若有） |
| Markdown | BSD-3-Clause | 保留声明 |
| Pillow | MIT-CMU（HPND） | 保留声明 |
| **psycopg / psycopg-binary** | **LGPL-3.0** | **弱传染**：以库的形式导入、未修改其源码，分发时随附 LGPL 原文即可，本项目不必开源 |
| gunicorn（`requirements-prod`） | MIT | 保留声明 |
| asgiref / sqlparse / webencodings | BSD-3-Clause | 保留声明 |
| packaging（`requirements-prod`） | Apache-2.0 **或** BSD-2-Clause（双许可，择一） | 两份原文都收在 `THIRD_PARTY_LICENSES/`，保留所选那份的声明 |

**义务评估**：强传染（GPL／AGPL）**没有**；唯一带传染性的是 psycopg 的 LGPL，按上表处理即可；其余都是宽松许可，保留声明就够。

**分发边界**：自己几台机器之间传递不触发义务；**给第三方就触发**——这个仓库是公开的，所以义务现在成立，`THIRD_PARTY_LICENSES/` 必须跟着仓库一起在。

## 3. 构建与开发工具（不随交付物分发，故不附原文）

`pip-tools`（BSD）、`pip-audit`（Apache-2.0）、`Playwright`（Apache-2.0，本地验证用）、`pip`／`setuptools`／`wheel`。它们不在 `requirements*.txt` 里，也不会进入部署环境。

## 4. 有意排除的依赖（免得后人重复评估）

| 没有它 | 为什么 |
|---|---|
| `djangorestframework` | 曾作为「为后续 API 预留」空装着（零路由、零视图），按「不留不用的依赖」移除。要开放 API 时先引入，再按 [architecture/interfaces.md](architecture/interfaces.md) 登记接口 |
| `tinycss2` | bleach 只在它的 `css` extra 里需要，本项目不用那部分 |
| HTMX、富文本编辑器组件 | 有意不做，理由见 [architecture/overview.md](architecture/overview.md) §1.1 |
| ffmpeg／对象存储 SDK | 不做视频转码、不切对象存储（同上） |

## 5. SBOM

**当前没有**机器可读的 SBOM（CycloneDX／SPDX）。底子是现成的：锁文件里已有每个包的精确版本与全部哈希，`pip-audit` 每次 PR 都会按它扫漏洞（CI 的 `audit` job）。真要出一份 SBOM，用读锁文件的工具生成即可：

```bash
.venv/bin/pip install cyclonedx-bom
.venv/bin/cyclonedx-py requirements requirements.txt -o sbom.json
```

生成后放仓库根、跟着版本一起打 tag——它描述的是**锁文件那一刻**的依赖，锁文件变了就要重新生成。
