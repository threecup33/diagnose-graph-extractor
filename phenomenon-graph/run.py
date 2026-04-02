#!/usr/bin/env python3
"""Start the Phenomenon Graph web server.

Usage:
    python run.py                   # localhost:8000
    python run.py --host 0.0.0.0    # accessible on LAN/IP
    python run.py --host 0.0.0.0 --port 8080
"""
import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="现象因果图分析系统 Web Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0，可通过 IP 访问）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    parser.add_argument("--reload", action="store_true", help="开发模式：文件变更时自动重载")
    args = parser.parse_args()

    print(f"\n  现象因果图分析系统")
    print(f"  ➜ 本地访问：http://localhost:{args.port}")
    print(f"  ➜ 网络访问：http://<your-ip>:{args.port}")
    print(f"  ➜ API 文档：http://localhost:{args.port}/docs\n")

    uvicorn.run(
        "src.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
