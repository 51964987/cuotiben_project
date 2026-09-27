"""启动入口：先清理 8000 端口的占用进程，再启动错题本服务。"""
import subprocess
import sys
import time

import uvicorn

HOST = "0.0.0.0"
PORT = 8000


def find_listener_pids(port: int) -> list:
    """用 netstat 找出监听指定端口的进程 PID（Windows）。"""
    out = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True
    ).stdout
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        # 形如: TCP  0.0.0.0:8000  0.0.0.0:0  LISTENING  12345
        if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].endswith(f":{port}"):
            pids.add(parts[4])
    return sorted(pids)


def free_port(port: int) -> None:
    """端口被占用时结束占用进程，确保随后能正常绑定。"""
    pids = find_listener_pids(port)
    if not pids:
        return
    for pid in pids:
        print(f"端口 {port} 被进程 {pid} 占用，正在结束…")
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
    time.sleep(1)
    if find_listener_pids(port):
        print(f"错误：无法释放端口 {port}（可能需要管理员权限），请手动结束相关进程后重试。")
        sys.exit(1)
    print(f"端口 {port} 已释放。")


if __name__ == "__main__":
    free_port(PORT)
    uvicorn.run("app.main:app", host=HOST, port=PORT)
