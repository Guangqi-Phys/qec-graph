# 固定 arXiv 回归集

> **中文** · [English](README.md)

[manifest](arxiv_sources.json) 记录六个精确 arXiv 版本、每个来源归档的 SHA-256、
规范化来源树哈希，以及预期 entrypoints 和 graph labels。它链接到 arXiv 上每个
版本列出的许可证。仓库分发 manifest 和观察到的结构结果。来源归档请从列出的
arXiv source URL 获取，或使用已有的内容寻址 workspace 副本。

在仓库根目录、已安装 QEC Graph 的环境中运行：

```sh
python tools/reproduce_golden.py \
  --archive-dir /path/to/workspace/archive/blobs/sha256 \
  --out build/golden-arxiv.json
```

输入目录也可为每个条目放一个 `<arxiv-id>.source` 文件，字节必须与 manifest 记录
完全一致。Replay 拒绝变化的归档字节。它把副本导入临时 workspace，验证 release
和归档字节，并检查来源路径和 label kinds。

[2308.07915v2](https://arxiv.org/abs/2308.07915v2) 的补充材料也支持独立编译。
Replay 检查 sync 保留这个有歧义的包，然后把固定 main entrypoint 加入临时
workspace config，并检查 included supplement 中的表格。
[2009.03921v2](https://arxiv.org/abs/2009.03921v2) 检查段落假设的引用仍为
source references。

输入使用 [arXiv distribution license](https://arxiv.org/licenses/nonexclusive-distrib/1.0/)
或 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。
Replay 测量结构抽取和证据绑定。
