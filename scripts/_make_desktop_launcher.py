# 生成桌面一键启动器（bat 需 GBK 编码，cmd 才能正确解析中文路径）
from pathlib import Path

content = (
    "@echo off\r\n"
    "title QQ Chat Assistant Launcher\r\n"
    "powershell -NoProfile -ExecutionPolicy Bypass -File \"D:\\小编程\\qq-assistant\\scripts\\start_all.ps1\"\r\n"
)

p = Path(r"C:\Users\a3132\Desktop\QQ机器人一键启动.bat")
p.write_bytes(content.encode("gbk"))
print("written:", p)
print("--- GBK 解码校验 ---")
print(p.read_bytes().decode("gbk"))
