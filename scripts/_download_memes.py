# 下载表情包候选图到 data/memes（临时名），人工查看后再定名
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://image-search-mcp-cn-beijing.oss-cn-beijing.aliyuncs.com/image-search-mcp/images-ppt"
CANDIDATES = [
    ("_tmp1.jpg", "6533bcee3bb5.jpeg"),   # 猫: 成年人做牛做马
    ("_tmp2.jpg", "c33aa33e9bfe.jpg"),    # 猫: 你好坏
    ("_tmp3.jpg", "21706a2d9b6c.jpg"),    # 猫: 到点下班冲
    ("_tmp4.jpg", "97e532a8245f.jpeg"),   # 兔狲: 注意你的言词
    ("_tmp5.jpg", "b1102a5f81a5.jpg"),    # 猫: 偷看
    ("_tmp6.jpg", "c318dfc1b393.jpeg"),   # 猫: 看见我巴掌了吗
    ("_tmp7.jpg", "fd77fdb9bd94.jpg"),    # 熊猫头候选
    ("_tmp8.jpg", "efe7d283230e.jpeg"),   # 熊猫头候选
    ("_tmp9.jpg", "f9827bb59c97.jpeg"),   # 熊猫头候选
    ("_tmp10.jpg", "ea9c6eeaa31a.jpeg"),  # 熊猫头候选
    ("_tmp11.jpg", "0448ae4a0d9d.png"),   # 熊猫头候选
]

out_dir = Path(r"D:\小编程\qq-assistant\data\memes")
out_dir.mkdir(parents=True, exist_ok=True)

ok = []
with httpx.Client(timeout=30, follow_redirects=True) as c:
    for fname, key in CANDIDATES:
        try:
            r = c.get(f"{BASE}/{key}")
            p = out_dir / fname
            p.write_bytes(r.content)
            # 用Pillow验证是真图片且尺寸合理
            from PIL import Image
            img = Image.open(p)
            img.verify()
            w, h = Image.open(p).size
            print(f"{fname}: OK {r.status_code} {len(r.content)//1024}KB {w}x{h}")
            ok.append(fname)
        except Exception as e:
            print(f"{fname}: FAIL {type(e).__name__} {str(e)[:60]}")
            (out_dir / fname).unlink(missing_ok=True)
print(f"\n{len(ok)} usable")
