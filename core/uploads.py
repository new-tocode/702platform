"""上传文件的通用处理。

两件事每个上传校验都要做：按扩展名认类型、读完文件头再把指针拨回开头。
media 与 projects 两处 validators 各写过一遍、逐字相同，所以收到这里。
"""

from pathlib import Path


def file_extension(name):
    """文件名的扩展名：小写、不带点；没有扩展名时返回空串。"""
    return Path(name or "").suffix.lower().lstrip(".")


def reset_file_position(uploaded_file):
    """把上传文件的读指针拨回开头。

    不支持 seek 的对象（内存里的文件、测试替身）安静跳过——它们本来就在开头。
    """
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError):
        return
