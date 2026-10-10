# 第三方许可证原文

这里放**运行时依赖**的许可证原文，与 [`requirements.txt`](../requirements.txt) / [`requirements-prod.txt`](../requirements-prod.txt) 的锁文件一一对应。义务评估见 [`docs/licenses.md`](../docs/licenses.md)。

| 包 | 许可证 | 文件 |
|---|---|---|
| Django | BSD-3-Clause | `Django.txt` |
| django-axes | MIT | `django-axes.txt` |
| bleach | Apache-2.0 | `bleach.txt` |
| Markdown | BSD-3-Clause | `Markdown.txt` |
| Pillow | MIT-CMU（HPND） | `Pillow.txt` |
| psycopg / psycopg-binary | LGPL-3.0 | `psycopg-LGPL-3.0.txt` |
| gunicorn | MIT | `gunicorn.txt` |
| asgiref | BSD-3-Clause | `asgiref.txt` |
| sqlparse | BSD-3-Clause | `sqlparse.txt` |
| webencodings | BSD-3-Clause | `webencodings.txt` |
| packaging | Apache-2.0 或 BSD-2-Clause（择一） | `packaging-Apache-2.0.txt`、`packaging-BSD-2-Clause.txt` |

**怎么更新**：依赖升级后，从虚拟环境里重新取原文，别手抄——

```bash
cp .venv/lib/python3.13/site-packages/<包>-<版本>.dist-info/licenses/LICENSE  THIRD_PARTY_LICENSES/<包>.txt
```

（较新的包把原文放在 `dist-info/licenses/` 下，旧包直接放在 `dist-info/` 下。文件名不都是 `LICENSE`。）
